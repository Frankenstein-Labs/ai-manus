from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import cdp
from app.core.security import require_sandbox_token


def _test_app():
    app = FastAPI()
    app.middleware("http")(require_sandbox_token)
    app.include_router(cdp.router, prefix="/api/v1/cdp")

    @app.get("/api/v1/private")
    async def private_endpoint():
        return {"ok": True}

    return app


def test_sandbox_api_rejects_missing_bearer_token(monkeypatch):
    monkeypatch.setenv("SANDBOX_ACCESS_TOKEN", "s" * 40)
    with TestClient(_test_app()) as client:
        response = client.get("/api/v1/private")
    assert response.status_code == 401


def test_cdp_relay_rejects_missing_bearer_token(monkeypatch):
    monkeypatch.setenv("SANDBOX_ACCESS_TOKEN", "s" * 40)
    with TestClient(_test_app()) as client:
        response = client.get("/api/v1/cdp/json/version")
    assert response.status_code == 401
