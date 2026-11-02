import hashlib
import hmac
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.infrastructure.external.sandbox import vercel_sandbox as adapter_module
from app.infrastructure.external.sandbox.vercel_sandbox import VercelSandbox


@pytest.mark.asyncio
async def test_create_vercel_sandbox_uses_private_per_sandbox_token_and_expected_routes(monkeypatch):
    master = "m" * 40
    settings = SimpleNamespace(
        sandbox_ttl_minutes=30,
        vercel_sandbox_image="registry.example.com/manus:latest",
        sandbox_access_token=master,
        sandbox_chrome_args="--disable-gpu",
        app_env="test",
        browser_engine="browser_use",
    )
    monkeypatch.setattr(adapter_module, "get_settings", lambda: settings)
    monkeypatch.setattr(adapter_module, "_start_supervisor", AsyncMock())
    monkeypatch.setattr(VercelSandbox, "ensure_sandbox", AsyncMock())

    box = SimpleNamespace(
        name="manus-test-sandbox",
        routes=[
            SimpleNamespace(port=8080, url="https://sandbox-api.example"),
            SimpleNamespace(port=5901, url="https://sandbox-vnc.example"),
        ],
        create_process=AsyncMock(),
        destroy=AsyncMock(),
    )
    create = AsyncMock(return_value=box)
    monkeypatch.setattr(adapter_module.vercel_sandbox, "create_sandbox", create)

    instance = await VercelSandbox.create()
    kwargs = create.await_args.kwargs
    expected_token = hmac.new(master.encode(), kwargs["name"].encode(), hashlib.sha256).hexdigest()
    assert kwargs["image"] == "registry.example.com/manus:latest"
    assert kwargs["ports"] == [8080, 5901]
    assert kwargs["persistent"] is True
    assert kwargs["env"]["SANDBOX_ACCESS_TOKEN"] == expected_token
    assert instance.base_url == "https://sandbox-api.example"
    assert instance.cdp_url == "https://sandbox-api.example/api/v1/cdp"
    assert instance.vnc_url == f"wss://sandbox-vnc.example/?token={expected_token}"
    assert instance.client.headers["Authorization"] == f"Bearer {expected_token}"
    await instance.client.aclose()
