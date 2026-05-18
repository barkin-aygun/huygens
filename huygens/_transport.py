"""Low-level UDP broadcast and WebSocket communication."""

import asyncio
import json
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
    async with websockets.connect(url, open_timeout=timeout) as ws:
        await ws.send(payload)
        data = await _recv_topic(
            ws, f"sdcp/status/{mainboard_id}", None, timeout
        )
        return data.get("Status", data)


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
