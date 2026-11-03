"""Vercel Sandbox adapter for the existing Sandbox gateway contract.

The Vercel Sandbox image must be published to Vercel Container Registry and
contain the existing Manus sandbox services. Public sandbox routes are treated
as untrusted: each sandbox receives its own derived API/CDP/VNC token.
"""
from __future__ import annotations

import hashlib
import hmac
import subprocess
import uuid
from datetime import timedelta
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from vercel import sandbox as vercel_sandbox

from app.core.config import get_settings
from app.infrastructure.external.sandbox.docker_sandbox import DockerSandbox
from app.infrastructure.external.browser.browser_use_browser import BrowserUseBrowser
from app.infrastructure.external.browser.playwright_browser import PlaywrightBrowser

API_PORT = 8080
VNC_PORT = 5901


def _route_url(box, port: int) -> str:
    for route in box.routes:
        if route.port == port:
            return route.url.rstrip("/")
    raise RuntimeError(f"Vercel Sandbox did not expose required port {port}")


async def _start_supervisor(box) -> None:
    """Ensure the image's app/X/Chrome/VNC processes are running after resume."""
    try:
        status = await box.run_process(
            "supervisorctl", ["-c", "/app/supervisord.conf", "status"],
            kill_after=15, capture_output=True,
        )
        if status.returncode == 0:
            if any(word in (status.stdout or "") for word in ("STOPPED", "EXITED", "FATAL")):
                await box.run_process(
                    "supervisorctl", ["-c", "/app/supervisord.conf", "start", "all"],
                    kill_after=30, capture_output=True, check=True,
                )
            return
    except Exception:
        pass
    await box.create_process(
        "supervisord", ["-n", "-c", "/app/supervisord.conf"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


class VercelSandbox(DockerSandbox):
    """Run the repository's sandbox image inside an isolated Vercel microVM."""

    def __init__(self, box, access_token: str):
        self._box = box
        self._access_token = access_token
        self._container_name = box.name
        self.ip = None
        self.client = httpx.AsyncClient(
            timeout=600,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        self.base_url = _route_url(box, API_PORT)
        self._cdp_url = f"{self.base_url}/api/v1/cdp"
        vnc_route = _route_url(box, VNC_PORT)
        parsed = urlsplit(vnc_route)
        ws_scheme = "wss" if parsed.scheme == "https" else "ws"
        self._vnc_url = urlunsplit((ws_scheme, parsed.netloc, "/", "token=" + quote(access_token), ""))

    @property
    def id(self) -> str:
        return self._container_name

    @staticmethod
    def _name() -> str:
        return "manus-" + hashlib.sha256(uuid.uuid4().bytes).hexdigest()[:24]

    @staticmethod
    def _token_for(name: str, master_secret: str) -> str:
        return hmac.new(master_secret.encode(), name.encode(), hashlib.sha256).hexdigest()

    @classmethod
    async def create(cls) -> "VercelSandbox":
        settings = get_settings()
        ttl_seconds = max(60, min((settings.sandbox_ttl_minutes or 30) * 60, 2700))
        name = cls._name()
        access_token = cls._token_for(name, settings.sandbox_access_token)
        box = await vercel_sandbox.create_sandbox(
            name=name,
            image=settings.vercel_sandbox_image,
            ports=[API_PORT, VNC_PORT],
            execution_time_limit=timedelta(seconds=ttl_seconds),
            persistent=True,
            env={
                "SANDBOX_ACCESS_TOKEN": access_token,
                "SERVICE_TIMEOUT_MINUTES": str(settings.sandbox_ttl_minutes or 30),
                "CHROME_ARGS": settings.sandbox_chrome_args or "",
            },
            tags={"application": "ai-manus", "environment": settings.app_env},
        )
        # Start the container services explicitly; do not assume a Docker CMD
        # is launched by Vercel Sandbox.
        await _start_supervisor(box)
        instance = cls(box, access_token)
        await instance.ensure_sandbox()
        return instance

    @classmethod
    async def get(cls, id: str) -> "VercelSandbox":
        settings = get_settings()
        box = await vercel_sandbox.get_sandbox(name=id, include_system_routes=True)
        await _start_supervisor(box)
        access_token = cls._token_for(id, settings.sandbox_access_token)
        instance = cls(box, access_token)
        await instance.ensure_sandbox()
        return instance

    async def destroy(self) -> bool:
        try:
            await self.client.aclose()
            await self._box.destroy()
            return True
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Failed to destroy Vercel Sandbox %s", self.id)
            return False

    async def get_browser(self):
        settings = get_settings()
        headers = {"Authorization": f"Bearer {self._access_token}"}
        if (settings.browser_engine or "browser_use").lower().strip() == "playwright":
            return PlaywrightBrowser(self.cdp_url, headers=headers)
        return BrowserUseBrowser(self.cdp_url, headers=headers)
