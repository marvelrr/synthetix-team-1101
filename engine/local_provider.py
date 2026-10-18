"""Start a loopback-only llama.cpp server using local CPU or Metal inference."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time
from urllib.parse import urlsplit
from urllib.request import urlopen

from dotenv import load_dotenv


def main() -> None:
    load_dotenv()
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-file", type=Path)
    parser.add_argument("--runtime", type=Path)
    configured = urlsplit(os.environ.get("LLM_BASE_URL", "http://127.0.0.1:11435/v1"))
    default_port = (configured.port or 11435) if configured.hostname in {"localhost", "127.0.0.1"} else 11435
    parser.add_argument("--port", type=int, default=default_port)
    parser.add_argument("--ollama-model", default=os.environ.get("SYNTHETIX_LOCAL_MODEL_TAG", "qwen2.5:0.5b"))
    parser.add_argument("--alias", default=os.environ.get("LLM_MODEL", "synthetix-local"))
    parser.add_argument("--device", choices=("cpu", "metal"),
                        default=os.environ.get("SYNTHETIX_LOCAL_DEVICE", "cpu"))
    parser.add_argument("--plain-json", action="store_true", help="Disable local schema-constrained decoding")
    args = parser.parse_args()
    if os.environ.get("SYNTHETIX_LOCAL_INFERENCE_ALLOWED") == "0":
        parser.error("Local model execution is disabled at the user's request because the laptop became hot. Review recorded results instead; obtain explicit user approval before enabling local inference.")
    if not 1024 <= args.port <= 65534:
        parser.error("port must be in 1024..65534")
    if args.device not in {"cpu", "metal"}:
        parser.error("SYNTHETIX_LOCAL_DEVICE must be cpu or metal")
    runtime = args.runtime or shutil.which("llama-server") or Path("/opt/homebrew/opt/ollama/libexec/lib/ollama/llama-server")
    if not Path(runtime).is_file():
        parser.error("llama-server not found; specify --runtime or install llama.cpp/Ollama")
    model = args.model_file
    if model is None:
        store = root / "work/ollama/models"
        if not re.fullmatch(r"[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+", args.ollama_model):
            parser.error("--ollama-model must be a local library model:tag, or use --model-file")
        model_name, model_tag = args.ollama_model.split(":")
        manifest = store / "manifests/registry.ollama.ai/library" / model_name / model_tag
        if not manifest.is_file():
            parser.error(f"model not downloaded; specify --model-file or download {args.ollama_model} with workspace Ollama storage")
        layers = json.loads(manifest.read_text())["layers"]
        digest = next(layer["digest"] for layer in layers if layer["mediaType"] == "application/vnd.ollama.image.model")
        model = store / "blobs" / digest.replace(":", "-")
    if not model.is_file():
        parser.error("local model file does not exist")
    backend_port = args.port if args.plain_json else args.port + 1
    device_flags = (["--device", "MTL0", "--n-gpu-layers", "all", "--kv-offload",
                     "--op-offload", "--flash-attn", "auto", "--fit", "on"]
                    if args.device == "metal" else
                    ["--device", "none", "--n-gpu-layers", "0", "--no-kv-offload",
                     "--no-op-offload", "--fit", "off"])
    command = [str(runtime), "--model", str(model), "--alias", args.alias, "--host", "127.0.0.1",
               "--port", str(backend_port), *device_flags, "--ctx-size", "8192", "--parallel", "1",
               "--threads", "4", "--threads-batch", "4", "--n-predict", "1024",
               "--offline", "--no-webui", "--log-disable"]
    label = "Metal" if args.device == "metal" else "CPU"
    print(f"Starting local {label} provider on 127.0.0.1:{args.port}; provider logging is disabled.", flush=True)
    if args.plain_json:
        os.execv(str(runtime), command)
    from engine.schema_provider import serve_proxy
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        upstream = f"http://127.0.0.1:{backend_port}"
        for _ in range(360):
            if process.poll() is not None:
                raise RuntimeError(f"local runtime stopped during startup (exit {process.returncode})")
            try:
                with urlopen(upstream + "/health", timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                pass
            time.sleep(0.25)
        else:
            raise RuntimeError("local runtime did not become healthy within 90 seconds")
        print("Schema-constrained action and evaluation decoding enabled; model responses and usage are forwarded unchanged.", flush=True)
        serve_proxy(upstream, args.port)
    except KeyboardInterrupt:
        pass
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
