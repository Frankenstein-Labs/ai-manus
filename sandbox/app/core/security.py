import hmac
import os

from fastapi import Request
from fastapi.responses import JSONResponse


async def require_sandbox_token(request: Request, call_next):
    """Require a constant-time compared Bearer secret on the sandbox API."""
    expected = os.getenv("SANDBOX_ACCESS_TOKEN", "")
    if expected and request.url.path.startswith("/api/v1/"):
        authorization = request.headers.get("authorization", "")
        supplied = authorization[7:] if authorization.lower().startswith("bearer ") else ""
        if not supplied or not hmac.compare_digest(supplied, expected):
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)
