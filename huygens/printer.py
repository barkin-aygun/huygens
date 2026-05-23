"""Public API for interacting with an SDCP-compatible printer.

All functions return plain dataclasses or raise descriptive exceptions.
Neither the CLI nor a future GUI should need to touch _transport directly.
"""

import os
from dataclasses import dataclass, field

from . import _transport

# ---------------------------------------------------------------------------
# Cmd constants
# ---------------------------------------------------------------------------

CMD_STATUS = 0
CMD_START_PRINT = 128
CMD_LIST_FILES = 258
CMD_VIDEO_URL = 386

# ---------------------------------------------------------------------------
# Ack error map (shared across commands)
# ---------------------------------------------------------------------------

ACK_ERRORS = {
    1: "Device busy",
    2: "File not found",
    3: "MD5 verification failed",
    4: "File read failed",
    5: "Resolution mismatch",
    6: "Unrecognised file format",
    7: "Machine model mismatch",
}

# ---------------------------------------------------------------------------
# Status label maps
# ---------------------------------------------------------------------------

MACHINE_STATUS_LABELS = {
    0: "Idle",
    1: "Printing",
    2: "File transfer",
    3: "Exposure test",
    4: "Self-check",
}

PRINT_STATUS_LABELS = {
    0: "Idle",
    1: "Resetting",
    2: "Descending",
    3: "Exposing",
    4: "Lifting",
    5: "Pausing",
    6: "Paused",
    7: "Stopping",
    8: "Stopped",
    9: "Completed",
    10: "Checking file",
}

PRINT_ERROR_LABELS = {
    0: "None",
    1: "Temperature too high",
    2: "Motor fault",
    4: "Media IO error",
    8: "Projector fault",
    16: "Fan fault",
    32: "Resin level low",
}

TIMELAPSE_STATUS_LABELS = {
    0: "Off",
    1: "Recording",
}

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PrinterInfo:
    id: str
    ip: str
    name: str
    machine_name: str
    brand: str
    mainboard_id: str
    protocol_version: str
    firmware_version: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @staticmethod
    def from_dict(d: dict) -> "PrinterInfo":
        return PrinterInfo(**d)


@dataclass
class PrintStatus:
    machine_status: int
    print_status: int
    filename: str | None
    current_layer: int
    total_layers: int
    elapsed_ms: int
    total_ms: int
    uv_led_temp: float | None
    box_temp: float | None
    release_film_count: int
    timelapse_status: int
    error_number: int
    task_id: str | None

    @property
    def machine_status_label(self) -> str:
        return MACHINE_STATUS_LABELS.get(self.machine_status, f"Unknown ({self.machine_status})")

    @property
    def print_status_label(self) -> str:
        return PRINT_STATUS_LABELS.get(self.print_status, f"Unknown ({self.print_status})")

    @property
    def error_label(self) -> str:
        return PRINT_ERROR_LABELS.get(self.error_number, f"Error {self.error_number}")

    @property
    def timelapse_label(self) -> str:
        return TIMELAPSE_STATUS_LABELS.get(self.timelapse_status, f"Unknown ({self.timelapse_status})")

    @property
    def remaining_ms(self) -> int:
        return max(0, self.total_ms - self.elapsed_ms)

    @property
    def progress_pct(self) -> float | None:
        if not self.total_layers:
            return None
        return self.current_layer / self.total_layers * 100


@dataclass
class FileEntry:
    name: str
    used_size: int
    total_size: int
    storage_type: int   # 0 = internal, 1 = external (USB)
    is_folder: bool

    @property
    def storage_label(self) -> str:
        return "USB" if self.storage_type == 1 else "Local"


# ---------------------------------------------------------------------------
# API functions
# ---------------------------------------------------------------------------

def discover(timeout: float = 5.0) -> list[PrinterInfo]:
    """Broadcast M99999 and return all responding printers."""
    raw_results = _transport.broadcast_discover(timeout)
    printers = []
    for msg, sender_ip in raw_results:
        d = msg.get("Data", {})
        ip = d.get("MainboardIP") or sender_ip
        printers.append(PrinterInfo(
            id=msg.get("Id", ""),
            ip=ip,
            name=d.get("Name", ""),
            machine_name=d.get("MachineName", ""),
            brand=d.get("BrandName", ""),
            mainboard_id=d.get("MainboardID", ""),
            protocol_version=d.get("ProtocolVersion", ""),
            firmware_version=d.get("FirmwareVersion", ""),
        ))
    return printers


def get_status(ip: str, mainboard_id: str, timeout: float = 10.0) -> PrintStatus:
    """Query the printer's current machine and print status."""
    raw = _transport.ws_get_status(ip, mainboard_id, timeout)
    print_info = raw.get("PrintInfo", {})

    current_status = raw.get("CurrentStatus", [0])
    machine_code = current_status[0] if isinstance(current_status, list) else current_status

    return PrintStatus(
        machine_status=machine_code,
        print_status=print_info.get("Status", 0),
        filename=print_info.get("Filename") or None,
        current_layer=print_info.get("CurrentLayer", 0),
        total_layers=print_info.get("TotalLayer", 0),
        elapsed_ms=print_info.get("CurrentTicks", 0),
        total_ms=print_info.get("TotalTicks", 0),
        uv_led_temp=raw.get("TempOfUVLED"),
        box_temp=raw.get("TempOfBox"),
        release_film_count=raw.get("ReleaseFilm", 0),
        timelapse_status=raw.get("TimeLapseStatus", 0),
        error_number=print_info.get("ErrorNumber", 0),
        task_id=print_info.get("TaskId") or None,
    )


def start_print(
    ip: str,
    mainboard_id: str,
    filename: str,
    start_layer: int = 0,
    timeout: float = 10.0,
) -> None:
    """Start printing a file. Raises ValueError on printer-reported errors."""
    resp = _transport.ws_command(
        ip, mainboard_id, CMD_START_PRINT,
        {"Filename": filename, "StartLayer": start_layer},
        timeout,
    )
    ack = resp.get("Data", {}).get("Ack", resp.get("Ack", 0))
    if ack != 0:
        raise ValueError(ACK_ERRORS.get(ack, f"Printer error (Ack={ack})"))


def upload_file(
    ip: str,
    local_path: str,
    remote_dir: str = "/local/",
    timeout: float = 60.0,
    on_progress=None,
) -> None:
    """Upload a .ctb file to the printer's storage."""
    filename = os.path.basename(local_path)
    _transport.http_upload(ip, local_path, filename, timeout, on_progress)


def get_video_url(ip: str, mainboard_id: str, timeout: float = 10.0) -> str | None:
    """Ask the printer for its RTSP video stream URL (CMD 386)."""
    resp = _transport.ws_command(ip, mainboard_id, CMD_VIDEO_URL, {}, timeout)
    ack = resp.get("Data", {}).get("Ack", resp.get("Ack", -1))
    if ack != 0:
        return None
    return resp.get("Data", {}).get("VideoUrl") or resp.get("VideoUrl")


def list_files(
    ip: str,
    mainboard_id: str,
    path: str = "/local/",
    timeout: float = 10.0,
) -> list[FileEntry]:
    """Return files available for printing at the given storage path."""
    resp = _transport.ws_command(
        ip, mainboard_id, CMD_LIST_FILES,
        {"Url": path},
        timeout,
    )
    entries = []
    for item in resp.get("Data", {}).get("FileList", resp.get("FileList", [])):
        entries.append(FileEntry(
            name=item.get("name", ""),
            used_size=item.get("usedSize", 0),
            total_size=item.get("totalSize", 0),
            storage_type=item.get("storageType", 0),
            is_folder=item.get("type", 1) == 0,
        ))
    return entries
