# Recorded judging showcase

This dependency-free static site replays actual saved Synthetix output. It does not request fresh AI feedback, accept private data, load third-party scripts, or contain an API key.

The site expects `assets/refillhk-five-persona.json`, with schema version `1.0`, and these top-level fields:

- `provenance`: run ID, Hong Kong recording timestamp, model, mode, source-material SHA-256, measured wall time, local-inference flag, browser visits and summary method.
- `config`: exact concept material, product name, value proposition, audience and user count.
- `users`, `evaluations`, `usage`, `findings`: serialized shared-contract records.
- `aggregate`: the deterministic output of `app.aggregate.aggregate`.

The separate, optional `assets/deployment.json` may set `live_app_url` to an HTTPS application URL. Without this setting, the page explicitly says live deployment is pending. Never put API credentials in either JSON file.

The Pages artifact should copy the static demonstration product into `refillhk/`, including all pages and local assets. Links use relative paths so the site works under a repository Pages URL.

Every dynamic value is inserted with `textContent`. No model output is interpreted as HTML. The recorded walkthrough supports keyboard tabs and responsive layouts; it has no external runtime dependencies.
