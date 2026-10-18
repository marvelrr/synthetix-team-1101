# Synthetix engine

> **Local compute stopped at the user’s request (17 October 2026).** The laptop became hot. Local model inference and intensive tests must remain off unless the user explicitly authorizes them again. The private configuration now sets `SYNTHETIX_LOCAL_INFERENCE_ALLOWED=0`; model startup and local API runs refuse to proceed. Use the existing UI to inspect recorded results. No remote inference provider is configured. The setup commands below are reference instructions, not authorization to run them.


Synthetic simulation — not real user research.

The initial engine-only scope was expanded by the user to include `app/` and
`demo_product/`. The complete local interface starts with `python -m app.launch`.
The seven shared v1.0 files match the supplied bytes; the contract test freezes
their SHA-256 hashes. No shared model, DB schema or API interface was changed.

## Verified status

- Live provider smoke tests passed using local Qwen2.5 3B weights on CPU and Metal. The latest Metal connectivity call returned valid JSON in 1.104 seconds (30 input, 6 output tokens); this is not a task throughput benchmark.
- One real concept user completed through `start_run`, the background worker,
  SQLite and a validated model evaluation. All tasks were `not_attempted` and
  ease of use was not assessable.
- Native Chromium initially failed under restricted macOS execution. With the current execution permissions, Chromium 156 opens the demo successfully. The earlier dedicated Linux Chromium container remains an optional fallback. Both browser paths have run the integration tests, including form submission and screenshots.
- A limited one-user v2 price check completed with an actual click, a passing
  code check, a screenshot and a valid saved evaluation. Its ratings were all
  not assessable, and its model feedback included a non-issue as a problem.
  The recorded report flags that quality defect. Earlier full v1 runs saved
  valid evaluations but completed no product tasks. The full CPU 3B run failed after two attempts at evaluation; its latest T2 task passed, while T1/T3 hit step limits. The one-user native-browser/Metal run completed with a valid evaluation, T2 passed, and T1/T3 failed at step limits. All ratings were not assessable and the evaluation contains attribution errors. The 10- and 50-user measurements remain deferred.
  See `engine/RUNS_LOG.md` for actual outcomes.

## Setup from the repository root

Use Python 3.11. The current workspace already has `work/venv`; on a fresh machine
create it with `python3.11 -m venv work/venv`.
Keep generated `work/` files out of Git through `.git/info/exclude`; this workspace
already does so. The frozen root `.gitignore` must remain unchanged.

```sh
source work/venv/bin/activate
python -m pip install -r requirements.txt
export PLAYWRIGHT_BROWSERS_PATH="$PWD/work/ms-playwright"
python -m playwright install chromium
```

The shared `.env.example` is unchanged. For local inference on a fresh setup,
copy `engine/local.env.example` to `.env`. Preserve any existing configured `.env`.
Model weights, runtimes, private configuration, SQLite data and screenshots are
not included in the source handoff.

### Dedicated Docker browser

When native Chromium cannot launch in this macOS execution environment, use
the installed Docker Desktop for a dedicated Linux browser:

```sh
docker desktop start
docker pull mcr.microsoft.com/playwright/python:v1.63.0-noble
export SYNTHETIX_BROWSER_IMAGE=mcr.microsoft.com/playwright/python:v1.63.0-noble
python -m engine.browser_service
export SYNTHETIX_CDP_URL=http://127.0.0.1:9222
```

The service publishes its debugging port only on host loopback, mounts no host
files or credentials, and suppresses browser and relay traffic logs. It is a
disposable browser, separate from personal browser profiles. Each engine user
still gets its own isolated context. The service reads `SYNTHETIX_BROWSER_IMAGE`;
an explicit `--image` argument overrides it. The official image's Chromium 153
passed the guarded back-navigation probe. The Alpine image's older Chromium 142
timed out waiting for `domcontentloaded` after back navigation even though the
home URL and completed document were visible. Use the configured official image
for this prototype; `engine/browser.Dockerfile` remains available as a compact
fallback.
Stop the dedicated service with `python -m engine.browser_service --stop`.

For a product served on this Mac, the container uses `host.docker.internal`
instead of its own `localhost`. The measured stub supports this explicitly:

```sh
python -m engine.measure --counts 1 10 50 --concurrency 5 --browser-host host.docker.internal
```

To test through this browser without changing worker unit-test doubles:

```sh
SYNTHETIX_TEST_CDP_URL=http://127.0.0.1:9222 \
SYNTHETIX_TEST_SITE_HOST=host.docker.internal \
python -m pytest engine/tests -q -rs
```

### Local inference with no external API

The chosen provider is a loopback-only llama.cpp server. CPU mode remains the
default and keeps all offloading disabled. The root execution context now detects
the Apple M2 Metal device with about 5.3 GiB available; a recorded Metal-backed product
run completed with task failures and feedback defects; local inference is now disabled. Earlier restricted execution could not access it.
The current workspace endpoint is `http://127.0.0.1:11446/v1`.

If weights are not downloaded, start installed Ollama in a separate terminal:

```sh
OLLAMA_MODELS="$PWD/work/ollama/models" OLLAMA_NO_CLOUD=1 \
  OLLAMA_HOST=127.0.0.1:11434 ollama serve
```

Then download weights with `OLLAMA_HOST=127.0.0.1:11434 ollama pull qwen2.5:3b`. Downloading requires network
access; inference does not use an external API. Start the CPU server when the
local endpoint is not already running:

```sh
python -m engine.local_provider
```

To use the detected native GPU, run `python -m engine.local_provider --device metal`
or set `SYNTHETIX_LOCAL_DEVICE=metal`. This selects `MTL0`, offloads model layers,
KV cache and supported operations, and keeps one inference slot with an 8,192-token
context. Use `--device cpu` to select the CPU fallback explicitly. Metal startup
fails clearly if that device is unavailable; it does not silently change devices.

The helper discovers `llama-server` on PATH or the installed Homebrew Ollama
runtime. Other installations can supply `--runtime /path/to/llama-server` and
`--model-file /path/to/model.gguf`. It binds to 127.0.0.1, uses one inference slot,
disables provider logging and the web UI, and does not download anything.
`SYNTHETIX_LOCAL_MODEL_TAG=qwen2.5:3b` selects the downloaded local weights.
The helper uses the configured public port and the following port for its local
backend. Its JSON-schema proxy constrains response structure for the exact engine
prompts; the model still chooses all actions, ratings and feedback. Response
content and token usage are forwarded unchanged. It never manufactures repairs.
Use `--plain-json` to run the backend directly without schema constraints.

The local proxy marks error responses as non-retryable at the SDK layer, so the
engine controls its single explicit retry. Its upstream timeout is 170 seconds,
below the engine's default local call timeout of 180 seconds. If you lower
`LLM_TIMEOUT_SECONDS`, also use a shorter proxy `--timeout` value. A disconnected
server can still trigger the SDK's connection-error retry behavior.

Compatibility: the bundled llama.cpp build `b10091` uses
`response_format={"type":"json_object","schema":...}` and supports native
top-level `json_schema`. The proxy supplies both with the same schema. In this
older build, `type="json_schema"` expects the nested
`response_format.json_schema.schema`; a sibling `response_format.schema` is
ignored in that form. See the
[parser for the bundled version](https://github.com/ggml-org/llama.cpp/blob/b4d6c7d8f/tools/server/server-common.cpp#L873-L890).

Run the required provider check before using a new provider:

```sh
python -m engine.smoke
```

It calls `contracts.llm.call_json` once and prints JSON and returned usage. On a
failed setup smoke test, stop and resolve the provider before proceeding.
The compact model's browser-task and feedback quality has not been established.

## Environment variables

| Variable | Purpose |
| --- | --- |
| `LLM_BASE_URL` | Required; current local endpoint is `http://127.0.0.1:11446/v1` |
| `LLM_API_KEY` | Required by the frozen wrapper; any dummy value for the local server |
| `LLM_MODEL` | Required; local server alias `synthetix-qwen2.5-3b` |
| `SYNTHETIX_LOCAL_MODEL_TAG` | Local Ollama-store weights used by `engine.local_provider` |
| `SYNTHETIX_LOCAL_DEVICE` | `cpu` by default; `metal` selects native `MTL0` GPU offloading |
| `LLM_JSON_MODE` | JSON-object output when `1`; default `1` |
| `LLM_TEMPERATURE` | Default `0.7` |
| `LLM_PRICE_IN_HKD_PER_1M` | Input price; leave blank if unknown |
| `LLM_PRICE_OUT_HKD_PER_1M` | Output price; leave blank if unknown |
| `SAVE_SCREENSHOTS` | `1` saves screenshots; default `1` |
| `PLAYWRIGHT_BROWSERS_PATH` | Browser installation; local template uses `work/ms-playwright` |
| `SYNTHETIX_FAKE_ENGINE` | Product layer setting; `0` selects this real engine |
| `SYNTHETIX_CDP_URL` | Optional dedicated Chromium CDP endpoint; otherwise launch Chromium |
| `SYNTHETIX_BROWSER_IMAGE` | Docker browser image; configured to the official Playwright Python v1.63.0 image |
| `SYNTHETIX_TEST_CDP_URL` | Browser endpoint for real integration tests only |
| `SYNTHETIX_TEST_SITE_HOST` | Hostname the integration browser uses for the stub; default `127.0.0.1` |

Local provider calls are serialized to match its single inference slot. Browser
user concurrency is still bounded independently by `RunConfig.max_concurrency`.
Unknown cost stays `None`; local inference is not assigned a fictitious zero price.
Budgeted launches require both finite pricing values. In-flight users may finish
after the budget is hit. If a failed/interrupted call leaves cost unknown, the
worker stops scheduling and fails queued users with a budget-accounting reason.

## Start a run from Python

```python
from contracts.models import AudienceSpec, RunConfig, Segment, TaskSpec
from engine.api import start_run, cancel_run, estimate_run

audience = AudienceSpec(
    spec_version="authored-demo-1",
    description="Authored starter profiles; not population research",
    segments=[Segment(
        name="HK household",
        weight=1,
        attributes={"tech comfort": ["moderate", "high"]},
        authored_assumptions=["Profile traits are authored assumptions."],
    )],
)
config = RunConfig(
    product_name="RefillHK", product_version="v1", mode="interactive",
    product_url="http://localhost:8101",
    value_proposition="Cleaning-product refills in reusable bottles",
    objective="Check whether the Basic price can be found",
    audience=audience, user_count=1, max_concurrency=5, seed=42,
    tasks=[TaskSpec(task_id="T1", instruction="Find the monthly price of Basic",
                    success_check="text_visible:HK$268 per month")],
)
estimate = estimate_run(config)  # Same-mode completed users' measured usage only.
run_id = start_run(config)      # Returns immediately; worker is a separate process.
# cancel_run(run_id)            # Stops new scheduling; lets in-flight users finish.
```

Concept mode uses `mode="concept"`, `concept_material="..."`, and no product URL.
It never launches a browser. Every configured task is recorded as `not_attempted`.

Inspect progress/results through the frozen `contracts.db` functions. User
completion is saved only after all results, a valid evaluation and usage exist.
Actual task results are also saved early to retain evidence if evaluation fails.
Only completed users belong in product metrics.

Resume an interrupted worker from the repository root:

```sh
python -m engine.worker --run-id <existing-run-id>
```

Start only one worker for a run at a time. Recovery queues leftover running users
with the same IDs and attempt counts; it does not retry completed users. Two
attempts are allowed. Usage accumulates, including a call-start record persisted
before invoking the provider. A crash during a call leaves cost unknown; tokens
not returned by the frozen provider wrapper cannot be recovered or invented.
Run logs contain status/stage/type information, not prompts or page bodies.
Model and prompt-version metadata is in `data/logs/<run_id>.metadata.json`.

## Browser behavior

Each user/attempt gets a fresh context, closed afterward. Each task opens a new
page. Success is checked in code after actions, using `url_contains:` or
`text_visible:`. A model saying done does not establish success.

Elements have temporary `data-synthetix-id` attributes. Observations include up
to 3,000 body characters and 60 controls; labels are capped at 60 characters.
Page data is escaped inside an untrusted page boundary. Traces store concise
observation summaries, code-extracted literal prices and actual action details.
Screenshots follow `data/traces/<run_id>/<user_id>/<task_id>-<step>.png`.

The agent blocks unsafe controls, unsafe endpoints, off-origin document
navigation and WebSocket connections. Writes are denied except same-origin
signup-form actions explicitly requested by the task. Unknown inputs, passwords,
search phrases or addresses are not invented: only the three supplied test-data
strings may be typed. Unsupported flows may therefore be blocked. Popups are
closed. Safety checks are conservative and may block otherwise harmless controls.
Arbitrary JavaScript cannot be proven harmless by label inspection; use a
disposable test product and its code-checked tasks.

## Tests

```sh
python -m pytest engine/tests -q -rs
```

Tests monkeypatch `contracts.llm.call_json`; live calls are forbidden by an
autouse fixture. Each test gets its own temporary DB, and every saved run is
checked for the accounting invariant after the test. Browser integration tests
serve `engine/tests/stub_site/` with `http.server` on a random port in a thread.
The stub is test data, never a saved demo example.

Native browser launches skip only for the observed macOS Mach-service denial;
other errors fail. The Docker/CDP command above runs the real browser integration
tests here. Browser test success does not establish model quality.

## Approved measurements

From a normal terminal where Chromium can launch:

```sh
python -m engine.measure --counts 1 10 50 --concurrency 5
```

Only the approved sizes 1, 10 and 50 are accepted. The script serves Device 2's
`demo_product/v1` on localhost:8101 when its files/tasks are present; otherwise it
serves the engine test stub on a random port. It records real results in
`engine/RUNS_LOG.md` and stops before larger sizes if no user completes. It never
relabels a startup error as a browser visit or task attempt. Use an optional
`--budget-hkd` only with configured pricing. Estimates use the contract's measured
same-mode average formula and are not guarantees across models, tasks or machines.

## Product-layer handoff

The public integration surface remains exactly:

```python
start_run(config: RunConfig, is_saved_example: bool = False) -> str
cancel_run(run_id: str) -> None
estimate_run(config: RunConfig) -> dict
```

Copy `engine/` into another device's repo alongside the identical contracts.
Set `SYNTHETIX_FAKE_ENGINE=0` there and configure its own local provider/browser.
This workspace also includes the user-authorized product layer in `app/` and
static RefillHK versions in `demo_product/`; see `app/README.md`.

Latest recorded run: `run-20261017-195303-6987`, one requested/completed user, one attempt, 384.711 seconds wall time. T1/T3 failed at step limits; T2 passed. A valid evaluation was saved, but all ratings are not assessable and its task attribution contains errors, flagged in the UI. No 10-/50-user runs were performed. The 140-test pass preceded the lightweight disable guards; tests were not rerun after the user requested stopping intensive work.

## Low-load DeepSeek pitching examples (18 October 2026)

The user authorized one fresh concept example and one retrospective review of recorded browser evidence. DeepSeek returned useful structured feedback, including one validation repair per example. No new browser visits or local model execution occurred. Run `run-20261018-010810-d087` completed one concept user; all tasks are not_attempted and ease of use is not assessable. Recorded source `run-20261017-195303-6987` retains its original task outcomes and database evaluation; new feedback is exported separately. These different modes/configurations are not an A/B comparison or a capacity benchmark. The user-facing offline demo kit is in outputs/Synthetix_Demo_Kit.zip.

Evidence now retains bounded literal page excerpts in database traces, never log files. Evaluation prompts include configured task instructions and coded success checks, and narrow contradiction checks trigger one repair instead of rewriting model ratings or results. Twenty-four mocked evaluator tests and two evidence-helper checks passed; intensive browser tests were not rerun.
