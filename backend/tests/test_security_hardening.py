from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.application.errors.exceptions import UnauthorizedError
from app.application.services.auth_service import AuthService
from app.core.config import Settings
from app.interfaces import dependencies


def test_production_rejects_placeholder_jwt_secret():
    settings = Settings(
        api_key="test-api-key",
        app_env="production",
        cors_allowed_origins="https://app.example.com",
        session_cookie_secure=True,
    )
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        settings.validate()


def test_production_rejects_wildcard_auth_mode():
    settings = Settings(
        api_key="test-api-key",
        app_env="production",
        cors_allowed_origins="https://app.example.com",
        session_cookie_secure=True,
        jwt_secret_key="x" * 40,
        auth_provider="none",
    )
    with pytest.raises(ValueError, match="AUTH_PROVIDER=none"):
        settings.validate()


@pytest.mark.asyncio
async def test_websocket_rejects_untrusted_origin_before_auth(monkeypatch):
    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: SimpleNamespace(
            allowed_origins=["https://app.example.com"],
            auth_provider="password",
            session_cookie_name="session_id",
        ),
    )

    websocket = SimpleNamespace(
        headers={"origin": "https://attacker.example"},
        cookies={},
    )
    with pytest.raises(UnauthorizedError, match="origin"):
        await dependencies.resolve_ws_user(websocket, auth_service=AsyncMock())


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["change", "reset"])
async def test_password_change_revokes_all_sessions(operation):
    user = SimpleNamespace(
        id="user-1",
        is_active=True,
        password_hash="old-hash",
        updated_at=None,
    )
    repository = SimpleNamespace(
        get_user_by_id=AsyncMock(return_value=user),
        get_user_by_email=AsyncMock(return_value=user),
        update_user=AsyncMock(),
    )
    sessions = SimpleNamespace(delete_all_for_user=AsyncMock(return_value=2))
    service = object.__new__(AuthService)
    service.user_repository = repository
    service.session_store = sessions
    service.settings = SimpleNamespace(auth_provider="password")
    service._verify_password = lambda password, stored: password == "current-password"
    service._hash_password = lambda password: "new-hash"

    if operation == "change":
        await service.change_password("user-1", "current-password", "new-password")
    else:
        await service.reset_password("person@example.com", "new-password")

    assert user.password_hash == "new-hash"
    sessions.delete_all_for_user.assert_awaited_once_with("user-1")
