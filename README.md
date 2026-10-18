# Synthetix

**Team 1101 – WoW0** · HK Inter-University GenAI Hackathon for SDGs 2026

**Synthetic simulation**

Synthetix helps Hong Kong SME owners get structured AI feedback on marketing and product copy before spending on a launch. Authored personas can flag possible confusion, hesitation and missing information. The owner decides what to validate with real customers.

The team’s goal is comparative copy feedback. Reliable comparative ranking, Cantonese performance, customer usefulness and willingness to pay are not yet validated.

## See the recorded prototype without starting services

1. Open [`saved-demo/Synthetix_Demo.html`](saved-demo/Synthetix_Demo.html) after downloading this repository. GitHub displays the HTML source rather than running the page.
2. Or view the [actual concept report](saved-demo/Synthetix_Concept_DeepSeek_Report.pdf) directly on GitHub.
3. View the [recorded interactive evidence review](saved-demo/Synthetix_Recorded_Interactive_DeepSeek_Report.pdf).

RefillHK is an invented demonstration business. Synthetix is the cross-sector feedback product.

The concept example uses one authored profile and supplied material. All browser tasks are `not_attempted`, and ease of use is not assessable. The saved browser example records a passed delivery check and failed price-discovery and signup tasks. DeepSeek later reviewed the old evidence. These examples do not establish real customer demand or a before/after improvement.

## What is implemented

- Configurable authored profiles with deterministic generation.
- Concept evaluation and browser-task execution with code success checks.
- Individual browser contexts, bounded actions, safety stops, usage records, retries and cancellation.
- A Streamlit interface, reports, evidence views, comparison interface, and PDF/CSV exports.
- Shared Pydantic models and SQLite storage under the frozen v1.0 contract.

Reliable autonomous navigation remains incomplete. The recorded browser agent used Qwen2.5 3B. Recent concept feedback used DeepSeek `deepseek-flash`. A complete browser run with DeepSeek is not demonstrated.

## Source layout

- `engine/`: profiles, browser agent, evaluation and job worker.
- `app/`: Streamlit product interface, aggregation and exports.
- `demo_product/`: invented RefillHK v1/v2 static sites.
- `contracts/`: unchanged shared models, database and LLM wrapper.
- `saved-demo/`: real saved examples with explicit dates and provenance.

## Optional local setup with a remote provider

Python 3.11 is required. Create a virtual environment outside the repository, then install `requirements.txt`. Copy `.env.example` to a private `.env` and configure an OpenAI-compatible remote provider.

```dotenv
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=YOUR_PRIVATE_KEY
LLM_MODEL=YOUR_PROVIDER_SUPPORTED_MODEL
LLM_JSON_MODE=1
SYNTHETIX_FAKE_ENGINE=0
SYNTHETIX_LOCAL_INFERENCE_ALLOWED=0
```

Never commit `.env` or API keys. The repository contains no API key, model weights, private database or customer data.

```bash
pip install -r requirements.txt
playwright install chromium
streamlit run app/main.py
```

Starting a run may incur provider cost. Keep local inference disabled. The saved demo requires no inference, installation or running service. The legacy local-provider modules remain in the source for provenance; they are not the recommended demo path. `app/launch.py` has older local-provider assumptions, so use the Streamlit command above for remote-provider configuration.

## Tests and measured limits

```bash
python -m pytest engine/tests app/tests
```

Tests use mocked LLM responses. The earlier recorded full suite passed 140 tests. After later evidence changes, 24 mocked evaluator checks and two evidence-helper checks passed; the full browser suite was not rerun. See [`docs/prototype-test-results.txt`](docs/prototype-test-results.txt).

Profile allocation is tested through 10,000 profiles. Browser capacity at that scale is not measured. The proposed 10- and 50-user browser benchmarks have not happened. Unknown HKD cost remains unknown.

## Ethical boundaries and next validation

Synthetic personas are not representative people. No conversion, customer acquisition cost or advertising-return forecast is claimed. Before a pilot, obtain permission for supplied material and establish sensitive-data, provider, retention and redaction controls. Human reviewers must be able to challenge the feedback. Owner interviews and Cantonese/mixed-language validation remain next steps.

## Team

All members are from **City University of Hong Kong**.

- Steven Sie SANTOSA
- Frederico Owen WU
- Marvel Reswanda RAHARDJO
- Harrell Dave GUNAWAN
