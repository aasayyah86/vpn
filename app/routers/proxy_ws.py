"""
WebSocket reverse proxy for Xray inbounds.

Railway exposes a single port (8000). This router forwards WebSocket
connections arriving at /vmess, /vless, /trojan to the corresponding
local Xray inbound port so all protocols are reachable through the
single Railway domain.
"""

import asyncio

# websockets 13+ has asyncio submodule; 12.x does not — handle both
try:
    from websockets.asyncio.client import connect as ws_connect
except ImportError:
    from websockets.legacy.client import connect as ws_connect  # type: ignore[no-redef]

import websockets
from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

router = APIRouter(tags=["Proxy"])

# Map from URL path → (local Xray inbound port, upstream WS path)
# The path MUST match wsSettings.path in xray_config.json
_WS_ROUTES: dict[str, tuple[int, str]] = {
    "/vmess":  (2095, "/vmess"),
    "/vless":  (2096, "/vless"),
    "/trojan": (2097, "/trojan"),
}


async def _pipe_client_to_upstream(client: WebSocket, upstream):
    try:
        while True:
            data = await client.receive()
            if "bytes" in data and data["bytes"] is not None:
                await upstream.send(data["bytes"])
            elif "text" in data and data["text"] is not None:
                await upstream.send(data["text"])
            else:
                break
    except (WebSocketDisconnect, websockets.exceptions.ConnectionClosed, RuntimeError):
        pass


async def _pipe_upstream_to_client(upstream, client: WebSocket):
    try:
        async for message in upstream:
            if isinstance(message, bytes):
                await client.send_bytes(message)
            else:
                await client.send_text(message)
    except (websockets.exceptions.ConnectionClosed, WebSocketDisconnect, RuntimeError):
        pass


async def _proxy(client: WebSocket, target_port: int, target_path: str):
    await client.accept()

    # BUG FIX: Include the WS path so Xray can match the correct inbound.
    # Previously was f"ws://127.0.0.1:{target_port}" (no path → Xray returned HTTP 404).
    uri = f"ws://127.0.0.1:{target_port}{target_path}"
    try:
        async with ws_connect(uri, ping_interval=None, close_timeout=5) as upstream:
            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(_pipe_client_to_upstream(client, upstream)),
                    asyncio.create_task(_pipe_upstream_to_client(upstream, client)),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
    except (
        websockets.exceptions.ConnectionClosed,
        websockets.exceptions.InvalidStatus,  # BUG FIX: catch 404/non-101 from Xray
        OSError,
    ):
        pass
    finally:
        try:
            await client.close()
        except Exception:
            pass


@router.websocket("/vmess")
async def vmess_ws(websocket: WebSocket):
    port, path = _WS_ROUTES["/vmess"]
    await _proxy(websocket, port, path)


@router.websocket("/vless")
async def vless_ws(websocket: WebSocket):
    port, path = _WS_ROUTES["/vless"]
    await _proxy(websocket, port, path)


@router.websocket("/trojan")
async def trojan_ws(websocket: WebSocket):
    port, path = _WS_ROUTES["/trojan"]
    await _proxy(websocket, port, path)
