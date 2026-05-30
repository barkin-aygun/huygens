"""Public API for interacting with an SDCP-compatible printer.

All functions return plain dataclasses or raise descriptive exceptions.
Neither the CLI nor a future GUI should need to touch _transport directly.
"""

import os
from dataclasses import dataclass

from . import _transport

# ---------------------------------------------------------------------------
# Cmd constants
# ---------------------------------------------------------------------------

CMD_START_PRINT  = 128
CMD_PAUSE_PRINT  = 129
CMD_STOP_PRINT   = 130
CMD_RESUME_PRINT = 131
CMD_LIST_FILES   = 258
CMD_DELETE_FILES = 259
CMD_VIDEO        = 386

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
    1: "File MD5 check failed",
    2: "File read failed",
    3: "Resolution mismatch",
    4: "Format mismatch",
    5: "Machine model mismatch",
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
class PrinterAttributes:
    video_streams_used: int
    video_streams_max: int
    usb_present: bool
    remaining_memory: int          # bytes free on internal storage
    release_film_max: int          # FEP service-life limit; current count is in PrintStatus
    resolution: str                # e.g. "11520x5120"
    xyz_size: str                  # build volume "211.68x118.37x220" (mm)
    supported_file_types: list[str]
    network: str                   # "wlan" | "eth"
    firmware: str
    capabilities: list[str]
    devices_status: dict           # per-component health (1 = OK)

    @staticmethod
    def from_dict(a: dict) -> "PrinterAttributes":
        return PrinterAttributes(
            video_streams_used=a.get("NumberOfVideoStreamConnected", 0),
            video_streams_max=a.get("MaximumVideoStreamAllowed", 0),
            usb_present=a.get("UsbDiskStatus", 0) == 1,
            remaining_memory=a.get("RemainingMemory", 0),
            release_film_max=a.get("ReleaseFilmMax", 0),
            resolution=a.get("Resolution", ""),
            xyz_size=a.get("XYZsize", ""),
            supported_file_types=a.get("SupportFileType", []),
            network=a.get("NetworkStatus", ""),
            firmware=a.get("FirmwareVersion", ""),
            capabilities=a.get("Capabilities", []),
            devices_status=a.get("DevicesStatus", {}),
        )


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


def get_status(
    ip: str, mainboard_id: str, timeout: float = 10.0, brand_id: str = ""
) -> PrintStatus:
    """Query the printer's current machine and print status."""
    raw = _transport.ws_get_status(ip, mainboard_id, timeout, brand_id)
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
    brand_id: str = "",
) -> None:
    """Start printing a file. Raises ValueError on printer-reported errors."""
    resp = _transport.ws_command(
        ip, mainboard_id, CMD_START_PRINT,
        {"Filename": filename, "StartLayer": start_layer},
        timeout, brand_id,
    )
    ack = resp.get("Data", {}).get("Ack", resp.get("Ack", 0))
    if ack != 0:
        raise ValueError(ACK_ERRORS.get(ack, f"Printer error (Ack={ack})"))


def _print_control(
    ip: str, mainboard_id: str, cmd: int, timeout: float, brand_id: str = ""
) -> None:
    """Send a parameterless print-control command (pause/resume/stop)."""
    resp = _transport.ws_command(ip, mainboard_id, cmd, {}, timeout, brand_id)
    ack = resp.get("Data", {}).get("Ack", resp.get("Ack", 0))
    if ack != 0:
        raise ValueError(ACK_ERRORS.get(ack, f"Printer error (Ack={ack})"))


def pause_print(ip: str, mainboard_id: str, timeout: float = 10.0, brand_id: str = "") -> None:
    """Pause the running print job."""
    _print_control(ip, mainboard_id, CMD_PAUSE_PRINT, timeout, brand_id)


def resume_print(ip: str, mainboard_id: str, timeout: float = 10.0, brand_id: str = "") -> None:
    """Resume a paused print job."""
    _print_control(ip, mainboard_id, CMD_RESUME_PRINT, timeout, brand_id)


def stop_print(ip: str, mainboard_id: str, timeout: float = 10.0, brand_id: str = "") -> None:
    """Stop (cancel) the running print job."""
    _print_control(ip, mainboard_id, CMD_STOP_PRINT, timeout, brand_id)


def get_attributes(
    ip: str, mainboard_id: str, timeout: float = 10.0, brand_id: str = ""
) -> PrinterAttributes:
    """Query the printer's static-ish attributes (Cmd 1)."""
    raw = _transport.ws_get_attributes(ip, mainboard_id, timeout, brand_id)
    return PrinterAttributes.from_dict(raw)


UPLOAD_EXTENSIONS = (".goo", ".ctb")


def upload_file(
    ip: str,
    mainboard_id: str,
    local_path: str,
    timeout: float = 120.0,
    on_progress=None,
    remote_filename: str | None = None,
    brand_id: str = "",
) -> None:
    """Upload a sliced .goo or .ctb file to the printer's internal storage.

    The file is streamed to the SDCP HTTP endpoint in 1 MB packets with a
    full-file MD5 checksum. `on_progress(sent_bytes, total_bytes)` is called
    after each packet. The printer stores it under `remote_filename` (defaults
    to the basename of `local_path`), which matters when `local_path` is a
    temporary file whose name differs from the original. Raises ValueError for
    an unsupported file type and RuntimeError if the printer rejects the upload.
    """
    filename = remote_filename or os.path.basename(local_path)
    if not filename.lower().endswith(UPLOAD_EXTENSIONS):
        raise ValueError(
            f"Unsupported file type: only {', '.join(UPLOAD_EXTENSIONS)} files can be uploaded"
        )
    _transport.http_upload(
        ip, mainboard_id, local_path, filename, timeout, on_progress, brand_id
    )


VIDEO_ACK_ERRORS = {
    1: "Max video connections exceeded",
    2: "Camera unavailable",
    3: "Unknown error",
}


def start_video_stream(
    ip: str, mainboard_id: str, timeout: float = 10.0, brand_id: str = ""
) -> str:
    """Enable the RTSP stream and return its URL. Raises ValueError on failure."""
    resp = _transport.ws_command(ip, mainboard_id, CMD_VIDEO, {"Enable": 1}, timeout, brand_id)
    data = resp.get("Data", resp)
    ack = data.get("Ack", -1)
    if ack != 0:
        raise ValueError(VIDEO_ACK_ERRORS.get(ack, f"Video error (Ack={ack})"))
    url = data.get("VideoUrl")
    if not url:
        raise ValueError("Printer returned no VideoUrl")
    return url


def stop_video_stream(
    ip: str, mainboard_id: str, timeout: float = 5.0, brand_id: str = ""
) -> None:
    """Disable the RTSP stream, releasing the printer's connection slot."""
    try:
        _transport.ws_command(ip, mainboard_id, CMD_VIDEO, {"Enable": 0}, timeout, brand_id)
    except Exception:
        pass


def list_files(
    ip: str,
    mainboard_id: str,
    path: str = "/local/",
    timeout: float = 10.0,
    brand_id: str = "",
) -> list[FileEntry]:
    """Return files available for printing at the given storage path."""
    resp = _transport.ws_command(
        ip, mainboard_id, CMD_LIST_FILES,
        {"Url": path},
        timeout, brand_id,
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


def delete_files(
    ip: str,
    mainboard_id: str,
    file_paths: list[str],
    folder_paths: list[str] | None = None,
    timeout: float = 10.0,
    brand_id: str = "",
) -> list[str]:
    """Delete files (and optionally folders) from the printer's storage.

    Paths must be exactly as returned by `list_files` (the printer is picky
    about the leading storage prefix). Returns the list of paths the printer
    reported it could not delete; an empty list means everything succeeded.
    Raises ValueError if the printer rejects the whole request.
    """
    resp = _transport.ws_command(
        ip, mainboard_id, CMD_DELETE_FILES,
        {"FileList": file_paths, "FolderList": folder_paths or []},
        timeout, brand_id,
    )
    data = resp.get("Data", resp)
    ack = data.get("Ack", resp.get("Ack", 0))
    failed = data.get("ErrData", resp.get("ErrData", [])) or []
    if ack != 0 and not failed:
        raise ValueError(f"Printer rejected delete request (Ack={ack})")
    return failed
