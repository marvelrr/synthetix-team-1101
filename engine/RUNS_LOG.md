# Measured engine runs

Synthetic simulation — not real user research.

Times are measured, not capacity promises. Average seconds per user includes recorded attempts. Tokens are returned usage only; failed provider calls may have unavailable token usage.

| Date (HKT) | Run | Mode / version | Model | Concurrency | Requested | Completed | Failed | Cancelled | Wall s | Avg s/user | Input / output tokens | Cost HKD |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-10-17T01:31:00+08:00 | run-20261017-013100-81b3 | concept / concept-1 | synthetix-local | 1 | 1 | 1 | 0 | 0 | 7.271 | 6.963 | 863 / 287 | unknown |
| 2026-10-17T01:42:01+08:00 | run-20261017-014201-0b85 | interactive / stub-1 | synthetix-local | 5 | 1 | 0 | 1 | 0 | 2.032 | 0.001 | 0 / 0 | unknown |
| 2026-10-17T02:40:14+08:00 | run-20261017-024014-9c5c | interactive / v1 | synthetix-local | 5 | 1 | 0 | 1 | 0 | 56.357 | 54.054 | 9384 / 324 | unknown |
| 2026-10-17T02:43:24+08:00 | run-20261017-024324-5f27 | interactive / v1 | synthetix-local | 5 | 1 | 0 | 1 | 0 | 103.335 | 101.081 | 18460 / 687 | unknown |
| 2026-10-17T02:51:47+08:00 | run-20261017-025147-17a0 | interactive / v1 | synthetix-qwen2.5-1.5b | 5 | 1 | 0 | 1 | 0 | 207.623 | 205.925 | 30330 / 866 | unknown |
| 2026-10-17T12:55:53+08:00 | run-20261017-125553-048a | interactive / v1 | synthetix-qwen2.5-1.5b | 5 | 1 | 0 | 1 | 0 | 446.615 | 445.309 | 41343 / 1013 | unknown |
| 2026-10-17T13:04:15+08:00 | run-20261017-130415-4512 | interactive / v1 | synthetix-qwen2.5-1.5b | 5 | 1 | 1 | 0 | 0 | 611.318 | 610.045 | 39352 / 964 | unknown |
| 2026-10-17T13:17:49+08:00 | run-20261017-131749-2233 | interactive / v1 | synthetix-qwen2.5-1.5b | 5 | 1 | 1 | 0 | 0 | 789.220 | 787.935 | 39250 / 1103 | unknown |
| 2026-10-17T13:32:15+08:00 | run-20261017-133215-bea2 | interactive / v2 | synthetix-qwen2.5-3b | 5 | 1 | 1 | 0 | 0 | 118.752 | 115.426 | 2170 / 420 | unknown |
| 2026-10-17T13:37:43+08:00 | run-20261017-133743-2cfb | interactive / v1 | synthetix-qwen2.5-3b | 5 | 1 | 0 | 1 | 0 | 3635.991 | 3633.802 | 118049 / 3162 | unknown |
| 2026-10-17T19:53:03+08:00 | run-20261017-195303-6987 | interactive / v1 | synthetix-qwen2.5-3b | 5 | 1 | 1 | 0 | 0 | 384.711 | 380.272 | 57773 / 1927 | unknown |
| 2026-10-18T01:08:10+08:00 | run-20261018-010810-d087 | concept / v2-concept-demo | deepseek-flash | 1 | 1 | 1 | 0 | 0 | 21.145 | 20.074 | 5436 / 3244 | unknown |

## Notes


- run-20261017-013100-81b3: Real one-user local-model concept integration check. No browser interaction; all tasks not_attempted. Wall time is the database created-to-settled interval. This does not establish interactive capacity.

- run-20261017-014201-0b85: Actual interactive startup attempt against the static engine test stub, not the demo product. Chromium Mach service registration was denied by the macOS execution sandbox. No page opened and no model call occurred. The user failed after two attempts at stage browser startup. Timings measure startup/bookkeeping, not browser performance.

- 10- and 50-user interactive runs have not been performed. A limited v2 price-only run passed its task and saved an evaluation, but all ratings were not assessable. Full three-task runs have not established reliable task execution or feedback quality.
- Local models: synthetix-local used Qwen2.5 0.5B weights; synthetix-qwen2.5-1.5b uses Qwen2.5 1.5B weights. Both run on CPU.
- Unit-test fixtures live only in temporary databases and are not included in this log or the development database.

- run-20261017-024014-9c5c: Demo v1 interaction. No user completed. Any startup-failure timings measure bookkeeping, not browser task performance. Larger sizes were not attempted.

- run-20261017-024324-5f27: Demo v1 interaction. No user completed. Any startup-failure timings measure bookkeeping, not browser task performance. Larger sizes were not attempted.

- run-20261017-025147-17a0: Demo v1 interaction. No user completed. Any startup-failure timings measure bookkeeping, not browser task performance. Larger sizes were not attempted.

- run-20261017-125553-048a: Demo v1 interaction. No user completed. Any startup-failure timings measure bookkeeping, not browser task performance. Larger sizes were not attempted.

- run-20261017-130415-4512: Demo v1 integration diagnostic, two attempts. The schema proxy compatibility format was corrected during the second attempt. One valid evaluation was saved; T1/T2/T3 all failed and all five ratings were not assessable. Browser back actions timed out. This mixed-runtime diagnostic is not a clean capacity benchmark.

- run-20261017-131749-2233: Full three-task v1 check with compatible JSON constraints and Chromium 153. One user completed on its first attempt, but T1 was blocked, T2 hit the step limit, T3 was blocked and all five ratings were not assessable. No browser back timeout recurred. Another local model was briefly started and smoke-tested during this run, so wall time includes CPU contention and is not a clean throughput benchmark.

- run-20261017-133215-bea2: LIMITED v2 integration check: one user and T1 price lookup only. Price is displayed on the v2 home page. This is not the full three-task benchmark or evidence of improved user demand. Local Qwen2.5 3B CPU model; temperature 0.2.

- run-20261017-133743-2cfb: Full v1 diagnostic using Qwen2.5 3B on CPU. One user failed after two attempts because evaluation returned InternalServerError. Latest saved results: T1 failed at 15 steps; T2 passed its code success check in one step; T3 failed at 15 steps. No valid evaluation was saved, so this user is excluded from metrics. Proxy HTTP retry handling changed during the run; this is not a clean throughput benchmark. Larger sizes were not attempted.

- run-20261017-195303-6987: Native Chromium / Qwen2.5 3B Metal diagnostic. One user completed on its first attempt with a valid saved evaluation and 31 screenshots. T1 and T3 failed at 15 steps; T2 passed in one step. All ratings were not assessable; evaluation wrongly denied observed failures and attached a price-task problem to completed T2. These feedback defects are flagged in report metadata. Tests ran concurrently, so this is not a clean throughput benchmark. Local inference was stopped afterwards at the user's request due to heat.

- run-20261018-010810-d087: DeepSeek concept-only pitching example. One authored persona reviewed supplied v2 material; no browser was started and all three tasks were not_attempted. This is not an interactive capacity benchmark.

## 19 October 2026 — authorized five-profile judging concept run

Run `run-20261019-005227-7dfe`; DeepSeek `deepseek-flash`; concept mode; concurrency1. Requested5 / completed5 / failed0 / cancelled0. Wall129.481s, average25.896s per completed profile including repairs. Model calls8; input tokens20,583; output tokens21,983. Cost: unknown (pricing unset). Browser visits0; local inference disabled. Five distinct authored profiles reviewed identical supplied RefillHK material. Code-computed keyword concern index, no model grouping call. This is one measured concept run, not a browser-capacity benchmark. Recorded after the slide submission.
