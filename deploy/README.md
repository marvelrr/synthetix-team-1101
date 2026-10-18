# Hosting the judging application

The public GitHub Pages showcase replays an actual recorded run. It cannot execute Python or request new AI reviews. A separate Streamlit entry point supports session-isolated live concept reviews.

## Streamlit Community Cloud

Connect this repository and select:

- Branch: `main`
- Main file: `app/judge_demo.py`
- Python: `3.11`

`app/requirements.txt` is a minimal dependency file beside the entry point. The frozen root shared contract files remain unchanged. No Chromium, Docker, local models or private database is required for this judging entry point.

The app can display the real recorded five-profile report without secrets. New reviews stay disabled until the operator explicitly enables them in private cloud settings.

Add these settings only to the cloud platform's private Secrets field, never a repository file:

```toml
LLM_BASE_URL = "https://api.deepseek.com"
LLM_MODEL = "YOUR_SUPPORTED_PROVIDER_MODEL"
LLM_API_KEY = "YOUR_PRIVATE_API_KEY"
SYNTHETIX_LOCAL_INFERENCE_ALLOWED = "0"
SYNTHETIX_JUDGE_LIVE_ENABLED = "0"
SYNTHETIX_JUDGE_ACCESS_CODE = "YOUR_PRIVATE_JUDGING_CODE"
SYNTHETIX_JUDGE_DAILY_PROFILES = "5"
```

After checking the deployment, the operator can set the live flag to `"1"`. Share the access code privately with intended reviewers. It is not part of the public website or source. Keep the live flag off when paid reviews are not intended.

The app allows at most five profiles per submission, one paid run at a time, one schema repair per profile, a 90-second session cooldown and five reserved profiles per UTC day per process by default. The daily counter resets when the process restarts. These are request limits, not a guaranteed monetary ceiling. API usage can be billed; cost is unknown unless both pricing variables are configured. The SDK's automatic network retries are disabled. No additional model call is used to group concerns.

## Privacy boundaries

- Live input and results remain in the current Streamlit session's server memory. They are not saved into the shared SQLite store or public repository.
- Submitted material is sent to the configured DeepSeek service when the visitor explicitly starts a review. Provider processing policies apply.
- The entry point does not fetch submitted URLs, open a browser, accept uploaded files or run local inference.
- Provider errors are sanitized. API keys and judging codes are read only on the server.
- Model and visitor text is rendered as text, not executable HTML.
- The recorded bundle contains only fictional product material, authored profiles and measured output.

Use synthetic or non-sensitive copy for the judging demo. No visitor input is added to the public saved example automatically.

## Connect the live link

Once the actual deployment URL is verified, set `docs/site/assets/deployment.json` to contain that HTTPS `live_app_url`, and add the same URL to the README. Do not publish a guessed or unverified live URL.
