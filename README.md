# Synthetix

**Team 1101 – WoW0** · HK Inter-University GenAI Hackathon for SDGs 2026

Synthetix gives Hong Kong small businesses AI feedback on marketing and product copy. Several authored customer profiles independently review the same material, then the owner can inspect the feedback, shared concerns and differences.

**Synthetic simulation**

## Judges: start here

### [Open the five-profile demonstration](https://marvelrr.github.io/synthetix-team-1101/)

No download, installation, login or API key is needed to explore the recorded demonstration.

1. **See the product and input:** RefillHK is an invented cleaning-refill business used as a repeatable test case. Open its demonstration website and inspect the exact material reviewed.
2. **Inspect five customer profiles:** price-sensitive, busy, sceptical, first-time refill and sustainability-focused. Their priorities are authored assumptions.
3. **Explore actual results:** compare the independently generated ratings, read every response and inspect the supporting statements behind combined concern counts.

The walkthrough replays **actual saved results**. It does not pretend to make a fresh model request when a visitor advances a step. New reviews of visitors' own copy are not enabled on this recorded site.

| Evidence | Open |
|---|---|
| Guided demonstration | [Public judging showcase](https://marvelrr.github.io/synthetix-team-1101/) |
| Product being reviewed | [RefillHK demonstration website](https://marvelrr.github.io/synthetix-team-1101/site/refillhk/) |
| Complete five-profile report | [PDF](docs/site/assets/refillhk-five-persona-report.pdf) |
| Individual review records | [CSV](docs/site/assets/refillhk-five-persona-reviews.csv) |
| Exact input, profiles, responses and usage | [JSON](docs/site/assets/refillhk-five-persona.json) |

## What this demonstration actually ran

Recorded on **19 October 2026, 00:52 HKT** using remote **DeepSeek `deepseek-flash`**.

| Measurement | Actual result |
|---|---|
| Requested / completed profiles | **5 / 5** |
| Failed / cancelled profiles | **0 / 0** |
| Distinct authored profiles | **5** |
| Execution | Concept review, concurrency 1 |
| Wall time | **129.481 seconds** for this run |
| Model calls | **8**, including schema repairs |
| Input / output tokens | **20,583 / 21,983** |
| Cost in HKD | **Unknown**; pricing was not configured |
| Browser visits / local model execution | **0 / none** |

The sustainability-focused profile rated appeal and intention to use 4/5. The remaining four gave 3/5 on those dimensions. The saved responses show these differences; presentation code does not assign the scores.

Combined concern labels use a transparent keyword index over actual problem statements. Code counts distinct supporting profiles and shows the exact evidence. Topics can overlap. These counts describe the five chosen viewpoints, not a representative customer survey or predicted sales. Ease of use is unassessed because this is a concept review.

This judging-site update and five-profile evidence were prepared **after the 18 October slide submission**, on 19 October. The recording date remains visible. Earlier source history and original reports remain available.

## How the product works

**Product copy → authored profiles → independent DeepSeek reviews → validated structured output → code-computed report**

Profiles are generated reproducibly. Each model review receives the same product material and its own profile. Pydantic validates responses, with at most one repair per evaluation attempt. Code computes ratings, denominators, status accounting and the concern index. Original feedback remains inspectable by user ID.

## Privacy and access

The public judging site serves fictional product material, authored profiles and recorded output. It accepts no private submissions, makes no model requests, uses no analytics or third-party scripts, and contains no API key.

Private `.env` files, authentication configuration, databases and model weights are excluded. Local inference remains disabled.

The optional session-isolated Streamlit entry point at `app/judge_demo.py` is **not hosted or enabled for fresh reviews** in this recorded deployment. Its [deployment guide](deploy/README.md) explains server-side secrets, access control and request limits. The legacy `app/main.py` is a local interface with a shared database; it is not the public judging entry point.

## Run the application

For the recorded judging viewer, use Python 3.11:

```bash
pip install -r app/requirements.txt
streamlit run app/judge_demo.py
```

The recorded report needs no API key. Fresh reviews require separate server configuration and may incur API charges. See [deployment instructions](deploy/README.md). Never commit credentials. For the legacy full local interface, see [app/README.md](app/README.md).

## Source and verification

- `engine/`: reproducible profiles, evidence-constrained evaluation and worker.
- `app/`: aggregation, reports and UI, including the isolated judging entry point.
- `contracts/`: unchanged shared contract v1.0.
- `docs/site/`: recorded judging showcase and actual five-profile evidence.
- `demo_product/`: invented RefillHK test product.
- `saved-demo/`: earlier dated examples.

The new judging support/UI and aggregation checks pass **29 mocked tests** with no model, browser or server calls. They cover independent reviews, failure accounting, repair limits, provider restrictions, secret-safe rendering and session UI behavior. Static checks cover actual-record rendering, indexed evidence, tabs, text insertion and accessibility references.

```bash
python -m pytest app/tests/test_judge_support.py app/tests/test_aggregate.py
```

Earlier receipts remain in [docs/prototype-test-results.txt](docs/prototype-test-results.txt). Five concept reviews do not establish browser capacity or performance at larger counts.

## Earlier saved evidence

- [Original one-profile concept report](saved-demo/Synthetix_Concept_DeepSeek_Report.pdf).
- [Older browser evidence review](saved-demo/Synthetix_Recorded_Interactive_DeepSeek_Report.pdf), preserving its recorded successes and failures.

RefillHK is the demonstration input. Synthetix is the feedback product. No moderated persona debate, validated sales forecast or deterministic CAC/ROAS calculator is claimed as implemented. Real-customer agreement and owner usefulness still need evaluation.

## Team

All members are from **City University of Hong Kong**.

- Steven Sie SANTOSA
- Frederico Owen WU
- Marvel Reswanda RAHARDJO
- Harrell Dave GUNAWAN
