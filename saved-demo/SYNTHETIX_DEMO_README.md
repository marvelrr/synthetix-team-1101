# Synthetix demo reports

Synthetic simulation — not real user research

Unzip `Synthetix_Demo_Kit.zip`, then open `Synthetix_Demo.html` in your browser. It uses local files only and starts no AI services.

These are offline recorded examples. Opening a PDF or CSV does not start a model, browser, or test run. No local inference is needed to present them.

## Recorded interactive evidence, with new feedback

Saved example — recorded 2026-10-17 19:53 HKT, not live.

Source run: `run-20261017-195303-6987`. Product: RefillHK v1. One requested synthetic user; one completed evaluation. User completion means its task results and evaluation were saved; it does not mean every task succeeded.

Browser evidence was recorded on 17 October 2026. The supplied DeepSeek feedback was generated 2026-10-18T01:09:00.432493+08:00 using `deepseek-flash`. The same source persona and recorded task outcomes were reviewed, with assistant transcriptions of saved screenshots; no new product visits occurred. The original database evaluation and task records remain unchanged.

| Task | Actual outcome | Recorded steps | Recorded reason | Code success check |
| --- | --- | ---: | --- | --- |
| T1 | failed | 15 | step limit reached | `text_visible:HK$268 per month` |
| T2 | completed | 1 | success check passed | `text_visible:Kwun Tong` |
| T3 | failed | 15 | step limit reached | `url_contains:/welcome.html` |

Re-evaluated synthetic ratings (actual supplied JSON):

- Appeal: 3 of 5
- Usefulness: 3 of 5
- Ease Of Use: 2 of 5
- Trust: 2 of 5
- Intention To Use: 2 of 5

Files: `Synthetix_Recorded_Interactive_DeepSeek_Report.pdf` and `Synthetix_Recorded_Interactive_DeepSeek_Report.csv`. The CSV adds provenance columns to every row. No grouped LLM themes or population shares were generated.

## Fresh concept example

Saved example — recorded 2026-10-18 01:08 HKT, not live.

Run: `run-20261018-010810-d087`. One authored synthetic profile reviewed supplied concept material. All configured tasks are `not_attempted`; ease of use is not assessable. No product was operated.

- Appeal: 4 of 5
- Usefulness: 4 of 5
- Ease Of Use: not assessable — no relevant product task attempted
- Trust: 3 of 5
- Intention To Use: 3 of 5

Files: `Synthetix_Concept_DeepSeek_Report.pdf` and `Synthetix_Concept_DeepSeek_Report.csv`.

## Honest demo boundaries

- All ratings and feedback are synthetic; they are early signals, not real user research.
- Recorded task failures may reflect agent limitations, product friction, or both. A new reviewer does not resolve that attribution.
- These examples support no claims about conversion, predicted demand, comparative improvement, or tested capacity at larger counts.
- No browser or local model needs to run during a presentation. Prefer these saved files on a hot laptop.
- The standard report's saved-example banner is applied in the export copy only; this script does not update database flags or records.
- Both PDFs were rendered sequentially at 72 dpi and all five pages were visually inspected. Headers, saved-example labels and footers were checked on every page. The HTML links and CSV provenance were checked without launching a browser.

## Actual remote usage

Four logical DeepSeek calls were made, including one validation repair per example: 15,809 input tokens and 8,023 output tokens. HKD cost is unknown because pricing conversion is not configured. The fresh concept run completed in 21.145 seconds wall time. The recorded review is not a new browser run or a capacity measurement.
