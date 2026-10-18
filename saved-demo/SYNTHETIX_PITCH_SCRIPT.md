# Synthetix pitch and saved-demo script

Synthetic simulation — not real user research

## 90-second pitch

"Hong Kong startups need early feedback before they can recruit a full research panel. Synthetix lets a team define a product, tasks and an audience, then uses authored synthetic profiles to attempt those tasks or review concept material.

Our SDG 12 example is RefillHK: household cleaning refills in reusable bottles. The product is invented. In interactive mode, the engine records actions and uses code success checks to decide task completion. In concept mode, it records that no product interaction occurred and leaves ease of use not assessable.

The report keeps coverage, task evidence and synthetic ratings visible. Missing ratings are excluded. Problems are suggestions to investigate with real people. Synthetic results are early signals; they do not establish market demand."

## Saved-demo walkthrough

1. Open `Synthetix_Recorded_Interactive_DeepSeek_Report.pdf`. Say: "This is recorded browser evidence from 2026-10-17 19:53 HKT, with new DeepSeek feedback from 2026-10-18T01:09:00.432493+08:00. No browser is operating now. The original task records and database evaluation are unchanged."
2. Show the coverage and task evidence. Read the actual task outcomes from the table; do not call a completed evaluation a successful signup.
3. Show the ratings and feedback exactly as exported. Explain that the new reviewer saw the old evidence and did not perform new tasks. Agent difficulty is not automatically product difficulty.
4. Open `Synthetix_Concept_DeepSeek_Report.pdf`. Say: "This fresh concept review used supplied material. Every task is not attempted; ease of use is not assessable."
5. Close with: "The next step is to validate the most important questions with real users."

## Evidence card

| Task | Actual outcome | Recorded steps | Recorded reason | Code success check |
| --- | --- | ---: | --- | --- |
| T1 | failed | 15 | step limit reached | `text_visible:HK$268 per month` |
| T2 | completed | 1 | success check passed | `text_visible:Kwun Tong` |
| T3 | failed | 15 | step limit reached | `url_contains:/welcome.html` |

Do not claim real participants, live browsing, a conversion forecast, improvement between versions, or tested throughput from these saved examples.

## Short concept-first demonstration

1. Open the offline page and jump to the concept example. Explain: "This is one authored synthetic persona reviewing an invented household-refill concept, not a real customer interview."
2. Show the actual concept ratings: appeal 4 of 5, usefulness 4 of 5, trust 3 of 5 and intention to use 3 of 5. Ease of use is not assessable because no product task was attempted.
3. Read the real suggestions: clarify cost per refill, trial terms and bottle-return mechanics. Present them as questions to validate with people.
4. Show the separate recorded-evidence example: delivery checking passed; price discovery and signup hit step limits. Explain that the agent's mistakes are retained rather than converted into success.
5. Say: "Our next milestone is reliable remote browser execution and validation with real users. These two examples are different modes and are not a before/after comparison."
