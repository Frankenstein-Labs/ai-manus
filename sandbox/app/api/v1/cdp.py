"""Authenticated CDP relay; Chrome's DevTools port is never exposed directly."""
import asyncio
import hmac
import json
import os
from urllib.parse import urlsplit

import httpx
import websockets
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

router = APIRouter()
CHROME_CDP_HTTP = "http://127.0.0.1:8222"
CHROME_CDP_WS = "ws://127.0.0.1:8222"


def _authorized(value: str | None) -> bool:
    expected = os.getenv("SANDBOX_ACCESS_TOKEN", "")
    if not expected:
        return True  # Local Docker compatibility; production Vercel mode requires a token.
    raw = value or ""
    supplied = raw[7:] if raw.lower().startswith("bearer ") else ""
    return bool(supplied) and hmac.compare_digest(supplied, expected)


def _rewrite_urls(value, ws_base: str):
    if isinstance(value, dict):
        return {
            key: (f"{ws_base}/devtools/{urlsplit(item).path.split('/devtools/', 1)[-1]}"
                  if key == "webSocketDebuggerUrl" and isinstance(item, str) and "/devtools/" in item
                  else _rewrite_urls(item, ws_base))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_rewrite_urls(item, ws_base) for item in value]
    return value


@router.get("/{path:path}")
async def cdp_http_proxy(path: str, request: Request):
    if not _authorized(request.headers.get("authorization")):
        return Response(status_code=401, content="Unauthorized")
    query = request.url.query
    upstream_url = f"{CHROME_CDP_HTTP}/{path}"
    if query:
        upstream_url += f"?{query}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        upstream = await client.get(upstream_url)
    body = upstream.content
    content_type = upstream.headers.get("content-type", "")
    if "json" in content_type:
        try:
            proto = request.headers.get("x-forwarded-proto", request.url.scheme)
            host = request.headers.get("x-forwarded-host", request.url.netloc)
            ws_scheme = "wss" if proto == "https" else "ws"
            ws_base = f"{ws_scheme}://{host}/api/v1/cdp"
            body = json.dumps(_rewrite_urls(upstream.json(), ws_base)).encode()
        except (ValueError, TypeError):
            pass
    return Response(
        content=body,
        status_code=upstream.status_code,
        media_type=content_type.split(";", 1)[0] or None,
        headers={key: value for key, value in upstream.headers.items()
                 if key.lower() in {"cache-control", "content-disposition"}},
    )


@router.websocket("/devtools/{path:path}")
async def cdp_websocket_proxy(websocket: WebSocket, path: str):
    if not _authorized(websocket.headers.get("authorization")):
        await websocket.close(code=4401, reason="Unauthorized")
        return
    query = websocket.url.query
    upstream_url = f"{CHROME_CDP_WS}/devtools/{path}"
    if query:
        upstream_url += f"?{query}"
    try:
        async with websockets.connect(upstream_url, max_size=None, ping_interval=20) as upstream:
            await websocket.accept()

            async def client_to_chrome():
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        return
                    if message.get("text") is not None:
                        await upstream.send(message["text"])
                    elif message.get("bytes") is not None:
                        await upstream.send(message["bytes"])

            async def chrome_to_client():
                async for message in upstream:
                    if isinstance(message, str):
                        await websocket.send_text(message)
                    else:
                        await websocket.send_bytes(message)

            tasks = [asyncio.create_task(client_to_chrome()), asyncio.create_task(chrome_to_client())]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*done, return_exceptions=True)
            await asyncio.gather(*pending, return_exceptions=True)
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await websocket.close(code=1011, reason="CDP upstream unavailable")
        except Exception:
            pass
