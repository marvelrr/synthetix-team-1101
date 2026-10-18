"""Start or reuse the local Synthetix prototype: python -m app.launch."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


HTTP = build_opener(ProxyHandler({}), NoRedirect())


def _read(url: str, key: str | None = None) -> bytes | None:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        with HTTP.open(Request(url, headers=headers), timeout=1) as response:
            return response.read(65536) if response.status == 200 else None
    except (OSError, ValueError):
        return None


def _local(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        parsed.port  # Validate the configured port without opening a connection.
        return (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
                and not parsed.username and not parsed.password
                and not parsed.query and not parsed.fragment)
    except ValueError:
        return False


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-browser", action="store_true",
                        help="Use worker-launched native Chromium and skip Docker/CDP browser startup")
    args = parser.parse_args()
    os.chdir(ROOT)
    children: list[tuple[str, subprocess.Popen]] = []
    container_name = None

    def spawn(label: str, arguments: list[str]) -> subprocess.Popen:
        # Raw provider, request and page content never enters launcher logs.
        process = subprocess.Popen(arguments, cwd=ROOT, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
        children.append((label, process))
        return process

    def wait_ready(label: str, ready, process: subprocess.Popen, timeout: float = 60,
                   exits_when_ready: bool = False) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if ready():
                return
            code = process.poll()
            if code is not None and (code != 0 or not exits_when_ready):
                raise RuntimeError(f"{label} stopped during startup (exit {code}).")
            time.sleep(0.25)
        raise RuntimeError(f"{label} did not become ready within {timeout:g} seconds.")

    try:
        print("Synthetic simulation — not real user research", flush=True)
        for relative in ("app/main.py", "demo_product/v1/index.html", "demo_product/v2/index.html"):
            if not (ROOT / relative).is_file():
                raise RuntimeError(f"Required prototype file is missing: {relative}")

        if os.environ.get("SYNTHETIX_LOCAL_INFERENCE_ALLOWED") == "0":
            raise RuntimeError("Local model execution is disabled at the user's request because the laptop became hot. Review recorded results instead; obtain explicit user approval before enabling local inference.")
        base = os.environ.get("LLM_BASE_URL", "").rstrip("/")
        model = os.environ.get("LLM_MODEL", "")
        key = os.environ.get("LLM_API_KEY")
        if not _local(base):
            raise RuntimeError("This launcher uses a local model only. Set LLM_BASE_URL to an http://127.0.0.1:<port>/v1 endpoint and LLM_MODEL to its model alias in .env.")
        if not model.strip():
            raise RuntimeError("Set LLM_MODEL to the configured local model alias in .env.")

        def provider_ready() -> bool:
            payload = _read(base + "/models", key)
            if payload is None:
                return False
            try:
                return any(item.get("id") == model for item in json.loads(payload).get("data", []))
            except (ValueError, AttributeError, TypeError):
                return False

        if provider_ready():
            print("Reusing the configured local model service.", flush=True)
        else:
            parts = urlsplit(base)
            port = parts.port or 80
            if port < 1024 or parts.path.rstrip("/") != "/v1":
                raise RuntimeError("Configured local model is unavailable. Automatic engine.local_provider startup needs a local HTTP port in 1024..65535 and the /v1 path.")
            tag = os.environ.get("SYNTHETIX_LOCAL_MODEL_TAG") or "qwen2.5:0.5b"
            print("Starting the configured local model service.", flush=True)
            process = spawn("Local model service", [sys.executable, "-m", "engine.local_provider",
                                                     "--port", str(port), "--alias", model,
                                                     "--ollama-model", tag])
            wait_ready("Local model service; check the installed runtime and model weights with python -m engine.local_provider", provider_ready, process, timeout=90)

        # The product demo always uses the real engine; fake fixtures are opt-in
        # only when developers start Streamlit separately.
        os.environ["SYNTHETIX_FAKE_ENGINE"] = "0"
        if args.native_browser:
            os.environ["SYNTHETIX_CDP_URL"] = ""
            print("Native Chromium mode; browser startup happens in each worker.", flush=True)
        else:
            cdp = os.environ.get("SYNTHETIX_CDP_URL", "http://127.0.0.1:9222").rstrip("/")
            if not _local(cdp) or urlsplit(cdp).port != 9222 or urlsplit(cdp).path not in {"", "/"}:
                raise RuntimeError("Set SYNTHETIX_CDP_URL=http://127.0.0.1:9222 for the dedicated local browser service.")
            os.environ["SYNTHETIX_CDP_URL"] = cdp

            def browser_ready() -> bool:
                payload = _read(cdp + "/json/version")
                try:
                    return bool(payload and json.loads(payload).get("webSocketDebuggerUrl"))
                except (ValueError, AttributeError):
                    return False

            if browser_ready():
                print("Reusing the dedicated local Chromium service.", flush=True)
            else:
                if not shutil.which("docker"):
                    raise RuntimeError("Docker CLI is missing. Install and start Docker Desktop, then pull the configured browser image; or use --native-browser.")
                image = os.environ.get("SYNTHETIX_BROWSER_IMAGE", "synthetix-browser:alpine-3.22")
                if not image or image.startswith("-") or any(character.isspace() for character in image):
                    raise RuntimeError("SYNTHETIX_BROWSER_IMAGE must be a Docker image name.")
                try:
                    available = subprocess.run(["docker", "image", "inspect", image],
                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                               timeout=15, check=False).returncode == 0
                except subprocess.TimeoutExpired:
                    available = False
                if not available:
                    raise RuntimeError("Browser image is unavailable or Docker Desktop is stopped. Start Docker Desktop and pull the configured image explicitly: "
                                       f"docker pull {shlex.quote(image)}")
                container_name = f"synthetix-launcher-{os.getpid()}-{secrets.token_hex(3)}"
                print("Starting the dedicated local Chromium service.", flush=True)
                process = spawn("Browser service", [sys.executable, "-m", "engine.browser_service",
                                                    "--image", image, "--port", "9222", "--name", container_name])
                wait_ready("Browser service", browser_ready, process, timeout=90, exits_when_ready=True)
                if process.wait(timeout=10):
                    raise RuntimeError("Browser service helper failed during startup.")
                children.remove(("Browser service", process))

        for version, port in (("v1", 8101), ("v2", 8102)):
            url = f"http://127.0.0.1:{port}/index.html"
            ready = lambda url=url: b"RefillHK" in (_read(url) or b"")
            if ready():
                print(f"Reusing RefillHK {version} on port {port}.", flush=True)
                continue
            process = spawn(f"RefillHK {version}", [sys.executable, "-m", "http.server", str(port),
                                                    "--bind", "127.0.0.1", "--directory", f"demo_product/{version}"])
            wait_ready(f"RefillHK {version}; port {port} must be free", ready, process, timeout=15)

        health = "http://127.0.0.1:8501/_stcore/health"
        if _read(health) is not None:
            print("Reusing Streamlit on port 8501.", flush=True)
        else:
            process = spawn("Streamlit", [sys.executable, "-m", "streamlit", "run", "app/main.py",
                                          "--server.address", "127.0.0.1", "--server.port", "8501",
                                          "--server.headless", "true", "--browser.gatherUsageStats", "false"])
            wait_ready("Streamlit; port 8501 must be free", lambda: _read(health) is not None, process, timeout=45)
        print("\nOpen Synthetix: http://127.0.0.1:8501\nRefillHK v1: http://127.0.0.1:8101\nRefillHK v2: http://127.0.0.1:8102\nPress Ctrl+C to stop services started by this launcher.", flush=True)
        while True:
            for label, process in children:
                if process.poll() is not None:
                    raise RuntimeError(f"{label} stopped (exit {process.returncode}).")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping services started by this launcher.", flush=True)
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Prototype could not start: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        for _, process in reversed(children):
            if process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                except OSError:
                    pass
        if container_name:
            try:
                subprocess.run(["docker", "stop", "--time", "5", container_name], timeout=15,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            except (OSError, subprocess.TimeoutExpired):
                print(f"Stop the launcher's browser container manually: docker stop {container_name}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
