from app.core.config import get_settings
from app.infrastructure.external.sandbox.docker_sandbox import DockerSandbox


def get_sandbox_class():
    provider = (get_settings().sandbox_provider or "docker").lower().strip()
    if provider == "docker":
        return DockerSandbox
    if provider == "vercel":
        from app.infrastructure.external.sandbox.vercel_sandbox import VercelSandbox
        return VercelSandbox
    raise ValueError(f"Unsupported SANDBOX_PROVIDER: {provider}")
