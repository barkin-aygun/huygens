"""Low-level UDP broadcast and WebSocket communication."""

import asyncio
import hashlib
import json
import os
import socket
import time
import uuid

import websockets

_BROADCAST_PORT = 3000
_WS_PORT = 3030
_DISCOVERY_MSG = b"M99999"


# ---------------------------------------------------------------------------
# UDP discovery
# ---------------------------------------------------------------------------

def broadcast_discover(timeout: float) -> list[dict]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(0.5)
    try:
        sock.sendto(_DISCOVERY_MSG, ("255.255.255.255", _BROADCAST_PORT))
    except OSError as e:
        raise OSError(f"Failed to send broadcast: {e}") from e

    results: list[dict] = []
    seen: set[str] = set()
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            continue
        except OSError:
            break
        try:
            msg = json.loads(data.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        key = msg.get("Id") or addr[0]
        if key in seen:
            continue
        seen.add(key)
        results.append((msg, addr[0]))

    sock.close()
    return results


# ---------------------------------------------------------------------------
# WebSocket helpers
# ---------------------------------------------------------------------------

def _build_msg(cmd: int, mainboard_id: str, data: dict) -> tuple[str, str]:
    request_id = uuid.uuid4().hex
    payload = json.dumps({
        "Id": uuid.uuid4().hex,
        "Data": {
            "Cmd": cmd,
            "Data": data,
            "RequestID": request_id,
            "MainboardID": mainboard_id,
            "TimeStamp": int(time.time()),
            "From": 0,
        },
        "Topic": f"sdcp/request/{mainboard_id}",
    })
    return payload, request_id


async def _recv_topic(ws, topic: str, request_id: str | None, timeout: float) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise TimeoutError(f"Timed out waiting for topic {topic!r}")
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        parsed = json.loads(raw)
        if parsed.get("Topic") != topic:
            continue
        if request_id is not None:
            if parsed.get("Data", {}).get("RequestID") != request_id:
                continue
        return parsed.get("Data", {})


async def _ws_status(ip: str, mainboard_id: str, timeout: float) -> dict:
    url = f"ws://{ip}:{_WS_PORT}/websocket"
    payload, _ = _build_msg(0, mainboard_id, {})
    topic = f"sdcp/status/{mainboard_id}"
    async with websockets.connect(url, open_timeout=timeout) as ws:
        await ws.send(payload)
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise TimeoutError(f"Timed out waiting for topic {topic!r}")
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            parsed = json.loads(raw)
            if parsed.get("Topic") != topic:
                continue
            return parsed.get("Status", {})


async def _ws_command(
    ip: str, mainboard_id: str, cmd: int, data: dict, timeout: float
) -> dict:
    url = f"ws://{ip}:{_WS_PORT}/websocket"
    payload, request_id = _build_msg(cmd, mainboard_id, data)
    async with websockets.connect(url, open_timeout=timeout) as ws:
        await ws.send(payload)
        resp = await _recv_topic(
            ws, f"sdcp/response/{mainboard_id}", request_id, timeout
        )
        return resp


def ws_get_status(ip: str, mainboard_id: str, timeout: float) -> dict:
    return asyncio.run(_ws_status(ip, mainboard_id, timeout))


async def _ws_attributes(ip: str, mainboard_id: str, timeout: float) -> dict:
    url = f"ws://{ip}:{_WS_PORT}/websocket"
    payload, _ = _build_msg(1, mainboard_id, {})   # Cmd 1 = attribute request
    topic = f"sdcp/attributes/{mainboard_id}"
    async with websockets.connect(url, open_timeout=timeout) as ws:
        await ws.send(payload)
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise TimeoutError(f"Timed out waiting for topic {topic!r}")
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            parsed = json.loads(raw)
            if parsed.get("Topic") != topic:
                continue
            return parsed.get("Attributes", {})


def ws_get_attributes(ip: str, mainboard_id: str, timeout: float) -> dict:
    return asyncio.run(_ws_attributes(ip, mainboard_id, timeout))


def ws_command(ip: str, mainboard_id: str, cmd: int, data: dict, timeout: float) -> dict:
    return asyncio.run(_ws_command(ip, mainboard_id, cmd, data, timeout))


# ---------------------------------------------------------------------------
# HTTP file upload (SDCP "Send File" interface)
# ---------------------------------------------------------------------------

_HTTP_PORT = 3030                     # same port as the websocket service
_UPLOAD_PATH = "/uploadFile/upload"
_CHUNK_SIZE = 1024 * 1024             # 1 MB per packet, per the SDCP spec
_CMD_TERMINATE_TRANSFER = 255


def _file_md5(path: str) -> str:
    """Stream the file through MD5 so we never hold the whole thing in memory."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(_CHUNK_SIZE), b""):
            h.update(block)
    return h.hexdigest()


def _upload_error_message(body: dict) -> str:
    """Build a human-readable error from an SDCP failure response body."""
    parts = []
    for m in body.get("messages") or []:
        if isinstance(m, dict):
            field, message = m.get("field", ""), m.get("message", "")
            parts.append(f"{field}: {message}".strip(": ").strip())
    detail = "; ".join(p for p in parts if p)
    code = body.get("code", "?")
    return f"Printer rejected upload (code {code})" + (f": {detail}" if detail else "")


def _terminate_transfer(
    ip: str, mainboard_id: str, transfer_uuid: str, filename: str
) -> None:
    """Best-effort CMD 255 so the printer abandons an interrupted transfer."""
    try:
        asyncio.run(_ws_command(
            ip, mainboard_id, _CMD_TERMINATE_TRANSFER,
            {"Uuid": transfer_uuid, "FileName": filename}, timeout=5.0,
        ))
    except Exception:
        pass


def http_upload(
    ip: str,
    mainboard_id: str,
    local_path: str,
    remote_filename: str,
    timeout: float = 120.0,
    on_progress=None,
) -> None:
    """Upload a file to the printer in 1 MB packets with a full-file MD5 check.

    `timeout` applies per packet. On any failure the partial transfer is
    terminated (CMD 255) so the printer is not left waiting, then the error
    is re-raised.
    """
    import requests

    url = f"http://{ip}:{_HTTP_PORT}{_UPLOAD_PATH}"
    total_size = os.path.getsize(local_path)
    file_md5 = _file_md5(local_path)
    transfer_uuid = uuid.uuid4().hex

    sent = 0
    try:
        # One Session => one keep-alive TCP connection reused for every packet,
        # instead of a fresh handshake per 1 MB chunk. On the printer's slow,
        # high-latency WiFi link that per-packet setup is the avoidable cost.
        with open(local_path, "rb") as f, requests.Session() as session:
            while True:
                offset = sent
                chunk = f.read(_CHUNK_SIZE)
                if not chunk:
                    break
                resp = session.post(
                    url,
                    data={
                        "S-File-MD5": file_md5,
                        "Check": "1",
                        "Offset": str(offset),
                        "Uuid": transfer_uuid,
                        "TotalSize": str(total_size),
                    },
                    files={"File": (remote_filename, chunk, "application/octet-stream")},
                    timeout=timeout,
                )
                if not resp.ok:
                    raise RuntimeError(
                        f"Upload failed: HTTP {resp.status_code} — {resp.text[:200]}"
                    )
                try:
                    body = resp.json()
                except ValueError:
                    raise RuntimeError(
                        f"Upload failed: unexpected response — {resp.text[:200]}"
                    )
                if not body.get("success"):
                    raise RuntimeError(_upload_error_message(body))

                sent += len(chunk)
                if on_progress:
                    on_progress(sent, total_size)
    except Exception:
        _terminate_transfer(ip, mainboard_id, transfer_uuid, remote_filename)
        raise
