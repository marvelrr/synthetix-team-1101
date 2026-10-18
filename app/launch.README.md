# Local prototype launcher

Synthetic simulation — not real user research.

From the repository root, with the installed Python environment:

```sh
work/venv/bin/python -m app.launch --native-browser
```

The launcher loads the root `.env`, checks the configured local model without generating text, and starts or reuses RefillHK on ports 8101/8102 and Streamlit on port 8501. The native flag clears the inherited CDP endpoint and skips Docker; workers launch native Chromium. The launcher forces the real engine. Those explicit environment choices take precedence over `.env` values without editing the file. Restart an existing Streamlit process after changing configuration or launcher flags; reused UI processes and already-running workers retain their previous environment.

Without `--native-browser`, the default Docker/CDP mode remains available as described below. Native mode needs installed Playwright Chromium but no Docker service. Apple Silicon can use `SYNTHETIX_LOCAL_DEVICE=metal` or the provider helper's `--device metal`; CPU remains the provider default.

Automatic local-model startup accepts a local HTTP endpoint with a port in 1024..65534 and the `/v1` path, and any nonempty `LLM_MODEL` alias. It passes the port, alias and `SYNTHETIX_LOCAL_MODEL_TAG` to `engine.local_provider`. Use the current configured endpoint in `.env` rather than an earlier debugging port. The launcher does not download model weights or select a different model silently.

Keep the configured local API key in `.env`. Install the runtime and matching model weights as described by `engine/README.md`. Already-running local OpenAI-compatible servers can be reused when their `/models` endpoint advertises `LLM_MODEL`. External providers are rejected.

The dedicated browser endpoint is `http://127.0.0.1:9222`. Start Docker Desktop and download the recommended official Playwright Python image explicitly:

```sh
docker pull mcr.microsoft.com/playwright/python:v1.63.0-noble
```

Set this in the repo-root `.env`:

```dotenv
SYNTHETIX_BROWSER_IMAGE=mcr.microsoft.com/playwright/python:v1.63.0-noble
SYNTHETIX_CDP_URL=http://127.0.0.1:9222
SYNTHETIX_FAKE_ENGINE=0
```

The official image supplies the newer browser used for current verification. The older optional Alpine image can be built from `engine/browser.Dockerfile`, but is not the recommended setup: its older Chromium showed navigation timeouts during diagnosis. The launcher checks the configured image locally and does not build or download it. If the image is unavailable, check Docker Desktop and pull the configured image. No project directory, credentials or Docker socket is mounted into Chromium.

The demo URL entered in a test must be reachable by Chromium. With Docker Desktop, use `http://host.docker.internal:8101` for v1 or `http://host.docker.internal:8102` for v2; the human-facing browser URLs remain `http://127.0.0.1:8101` and `http://127.0.0.1:8102`.

Ctrl+C stops only processes and the uniquely named browser container started by this launcher. Reused services, engine worker processes and all stored data remain. Workers still using a model or browser started by this launcher need those services to remain available until the workers finish. The launcher creates no runs or benchmark data and suppresses subprocess output to avoid retaining page content.
