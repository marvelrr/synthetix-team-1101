# Synthetix product layer

> **Local compute stopped at the user’s request (17 October 2026).** The laptop became hot. Local model inference and intensive tests must remain off unless the user explicitly authorizes them again. The private configuration now sets `SYNTHETIX_LOCAL_INFERENCE_ALLOWED=0`; model startup and local API runs refuse to proceed. Use the existing UI to inspect recorded results. No remote inference provider is configured. The setup commands below are reference instructions, not authorization to run them.


A local Streamlit prototype for configuring synthetic product tests, inspecting recorded browser evidence, and reporting early signals. Every view labels the output **Synthetic simulation — not real user research**.

## Run the prototype

Run all commands from the repository root. Use the same Python 3.11 environment for Streamlit and the engine so the background worker has its dependencies.

```sh
python -m pip install -r requirements.txt
python -m streamlit run app/main.py --server.port 8501
```

For the prepared workspace environment, replace `python` with `work/venv/bin/python`. Open `http://localhost:8501`.

The preferred setup on this Mac is `python -m app.launch --native-browser`. It starts or reuses the local model, demo products and UI while each worker launches its own native Chromium; Docker is skipped. Install Chromium with `python -m playwright install chromium`. The native flag overrides the inherited CDP setting, and the launcher explicitly selects the real engine; no `.env` CDP edit is required. Restart an existing Streamlit process when changing launcher flags.

Apple Silicon can use local Metal acceleration: set `SYNTHETIX_LOCAL_DEVICE=metal` for `engine.local_provider`, or start that helper with `--device metal`. Leave this option unset for its CPU default. Native Chromium startup and a Metal model smoke call have passed; a full accelerated product test has not yet been verified.

The default `python -m app.launch` keeps the Docker/CDP path for compatibility. For that mode, start Docker Desktop, pull `mcr.microsoft.com/playwright/python:v1.63.0-noble`, and configure `SYNTHETIX_BROWSER_IMAGE` plus `SYNTHETIX_CDP_URL=http://127.0.0.1:9222` in `.env`. The launcher checks its image but does not download it. See `app/launch.README.md` for additional Docker setup.

Start the test product in separate terminals:

```sh
python -m http.server 8101 --directory demo_product/v1
python -m http.server 8102 --directory demo_product/v2
```

The real engine requires a running local model endpoint and Playwright Chromium or the configured browser service. See `engine/README.md` for provider and browser setup. This UI calls only `engine.api.start_run`, `cancel_run`, and `estimate_run`. It reads results through the frozen `contracts.db` store.

## Use it

1. **New test:** keep the supplied RefillHK tasks, choose one user, and check that the product URL responds. The starter Hong Kong audience is illustrative; all uncited traits are explicitly authored assumptions.
2. **Review plan:** inspect mode, assumptions, approximate segment allocation, task success checks and the estimate. An unavailable estimate is shown honestly.
3. **Launch test:** one background worker is started and the UI opens **Runs → Progress**. Counts and evidence refresh every two seconds while users remain unsettled. Cancellation stops new scheduling and lets users in flight finish.
4. **Report:** inspect task outcomes, ratings, denominators and individual traces. **Build / refresh evidence themes** explicitly asks the local model to label problem themes; supporting counts are calculated in code. A failed theme call falls back to grouping by task and severity.
5. **Compare:** select two runs to inspect means, signals and saved findings. Configuration differences are listed. An absent synthetic finding is not proof that a real-world issue is fixed.
6. Download CSV/PDF, or mark a completed run as a saved example. Saved and interim labels remain visible.

A completed synthetic user means the engine saved their task results and a valid evaluation. Their individual tasks may still have failed or been blocked. Failed users never enter report metrics, but their saved traces remain inspectable for diagnosis.

## Environment

`app/main.py` loads repo-root `.env` values without overriding existing process environment. Explicit launcher choices therefore take precedence, including native-browser mode and the real engine. Restart Streamlit after changing `.env` or launcher flags; a reused existing UI retains its previous environment. The client selects its backend on each call using that environment. The root shared `.env.example` is frozen; the local-provider example is in `engine/local.env.example`.

- `SYNTHETIX_FAKE_ENGINE=0`: real engine; the prepared workspace uses this. Real mode hides development runs whose product name begins `[FAKE]`.
- `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_JSON_MODE`, `LLM_TEMPERATURE`: shared model configuration. A local OpenAI-compatible server works; no cloud provider is required.
- `LLM_PRICE_IN_HKD_PER_1M`, `LLM_PRICE_OUT_HKD_PER_1M`: optional measured pricing. Unknown cost stays unknown. Both prices are required to enforce a run budget.
- `SAVE_SCREENSHOTS=1`: engine saves evidence images; the UI displays images available under `data/traces/`.
- `PLAYWRIGHT_BROWSERS_PATH`: installed Chromium location, when needed by the engine.
- `SYNTHETIX_LOCAL_DEVICE`: optional local inference device; `metal` enables Apple Silicon GPU inference, while the default remains CPU.
- `SYNTHETIX_BROWSER_IMAGE`: Docker-mode browser image; the recommended container is `mcr.microsoft.com/playwright/python:v1.63.0-noble`.
- `SYNTHETIX_CDP_URL`: optional engine browser-service endpoint. When set, the New Test demo URL defaults to `http://host.docker.internal:8101` so a container browser reaches the host product. The UI's reachability check uses the equivalent host-side loopback address. The native launcher flag clears this automatically and uses `http://localhost:8101`; direct Streamlit startup can leave it empty for native mode.

## Development fake mode

Set `SYNTHETIX_FAKE_ENGINE=1` **only for development**, then restart Streamlit directly rather than using the real-demo launcher. `app/engine_client.py` selects `app.fake_engine`; fake names are prefixed `[FAKE]` and every displayed fake run has a development warning. The fake worker advances users over about 20 seconds with its own SQLite connection and provides varied edge cases. Fake data must not be used in the demo or presented as measured evidence.

Switch back to `0` and restart Streamlit for the real prototype, or restart through the launcher, which forces the real engine. No fake run is created automatically. Newly launched real workers inherit the restarted UI's configuration; workers already running keep their original environment. A Streamlit restart also resets the shared LLM wrapper's cached provider client after endpoint or API-key changes.

## Tests

```sh
python -m pytest app/tests -q
python -m pytest engine/tests -q -rs
```

Reporting tests use hand-built records and mock LLM calls. Browser engine tests require a working Chromium environment; a platform sandbox failure is reported as skipped, never as a passing browser action. The UI can also be smoke-tested without starting a run using Streamlit's `streamlit.testing.v1.AppTest`.

## Report interpretation

Only completed users contribute to metrics. Missing and not-assessable ratings are excluded rather than treated as zero. Every percentage includes its numerator and denominator. A one-user report shows individual feedback without shares. Segment statistics are unweighted. Synthetic appeal and intention-to-use ratings are exploratory signals, not conversion or predicted demand.

When evidence themes are built, their grouping method is saved separately in `data/report_metadata/<run_id>.json`. Reports and PDFs restore this method across sessions, including whether fallback grouping was used. Older reports without this record identify the method as unrecorded. Existing run configuration is immutable in the UI.

Latest recorded run: `run-20261017-195303-6987`, one requested/completed user, one attempt, 384.711 seconds wall time. T1/T3 failed at step limits; T2 passed. A valid evaluation was saved, but all ratings are not assessable and its task attribution contains errors, flagged in the UI. No 10-/50-user runs were performed. The 140-test pass preceded the lightweight disable guards; tests were not rerun after the user requested stopping intensive work.

## Appearance

The project `.streamlit/config.toml` supplies the light mint/teal default theme. Custom CSS preserves native Streamlit foreground and background colors, so a saved dark-theme preference stays readable too. Restart only Streamlit after changing theme configuration and refresh the browser. The UI labels paused local AI and disables new model runs and theme-generation buttons while reviewing recorded results.
