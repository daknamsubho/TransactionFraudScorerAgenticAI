"""Cloudflare Tunnel (cloudflared) helper for exposing the FastAPI Gateway."""

import logging
import platform
import re
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

TRYCLOUDFLARE_REGEX = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")


def ensure_cloudflared_binary(install_dir: str = "/tmp") -> str:
    """Locate `cloudflared` on PATH or download the standalone binary for Linux/macOS."""
    existing = shutil.which("cloudflared")
    if existing:
        return existing

    target_path = Path(install_dir) / "cloudflared"
    if target_path.exists():
        target_path.chmod(0o755)
        return str(target_path)

    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "linux":
        arch = "arm64" if machine in ("aarch64", "arm64") else "amd64"
        download_url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}"
        logger.info("Downloading cloudflared from %s ...", download_url)
        urllib.request.urlretrieve(download_url, str(target_path))
        target_path.chmod(0o755)
        return str(target_path)

    raise FileNotFoundError(
        "cloudflared binary not found on PATH. Install it via `brew install cloudflared` (macOS) "
        "or download from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
    )


def start_cloudflare_tunnel(
    port: int = 8000,
    host: str = "127.0.0.1",
    timeout_seconds: float = 25.0,
) -> tuple[subprocess.Popen[str], str]:
    """Start a Cloudflare Quick Tunnel pointing to `http://{host}:{port}`.

    Returns:
        Tuple of (Popen process handle, public https://*.trycloudflare.com URL).
    """
    binary = ensure_cloudflared_binary()
    local_url = f"http://{host}:{port}"

    cmd = [binary, "tunnel", "--url", local_url, "--no-autoupdate"]
    logger.info("Starting Cloudflare Quick Tunnel for %s ...", local_url)

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    deadline = time.monotonic() + timeout_seconds
    public_url: str | None = None

    if process.stdout is not None:
        while time.monotonic() < deadline:
            line = process.stdout.readline()
            if not line:
                if process.poll() is not None:
                    break
                time.sleep(0.1)
                continue

            match = TRYCLOUDFLARE_REGEX.search(line)
            if match:
                public_url = match.group(0)
                break

    if not public_url:
        process.terminate()
        raise RuntimeError(f"Timed out waiting for Cloudflare Tunnel URL after {timeout_seconds}s.")

    logger.info("Cloudflare Tunnel active at %s", public_url)
    return process, public_url
