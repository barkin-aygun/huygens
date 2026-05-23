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


def ws_command(ip: str, mainboard_id: str, cmd: int, data: dict, timeout: float) -> dict:
    return asyncio.run(_ws_command(ip, mainboard_id, cmd, data, timeout))


# ---------------------------------------------------------------------------
# HTTP file upload
# ---------------------------------------------------------------------------

_HTTP_PORT = 58883
_UPLOAD_PATH = "/upload"


def http_upload(
    ip: str,
    local_path: str,
    remote_filename: str,
    timeout: float = 60.0,
    on_progress=None,
) -> None:
    import requests

    url = f"http://{ip}:{_HTTP_PORT}{_UPLOAD_PATH}"
    file_size = os.path.getsize(local_path)
    sent = [0]

    class _ProgressFile:
        def __init__(self, f):
            self._f = f

        def read(self, size=-1):
            chunk = self._f.read(size)
            sent[0] += len(chunk)
            if on_progress and chunk:
                on_progress(sent[0], file_size)
            return chunk

    with open(local_path, "rb") as f:
        md5 = hashlib.md5(f.read()).hexdigest()
        f.seek(0)
        wrapped = _ProgressFile(f)
        resp = requests.post(
            url,
            files={"file": (remote_filename, wrapped, "application/octet-stream")},
            data={"md5": md5, "check": "1"},
            timeout=timeout,
        )

    if not resp.ok:
        raise RuntimeError(f"Upload failed: HTTP {resp.status_code} — {resp.text[:200]}")
