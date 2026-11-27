# Full benchmark runs

Runs of the browser agent on many tasks of BU Bench V2.1 (200 tasks, `bu2-001` to `bu2-200`). Only scores and
numbers are recorded here: no task text, no rubric items, no judge evidence. The per-task lines with the judge's
evidence stay in `../.reports/` (gitignored, local only).

## 2026-11-27: gpt-6.1-terra on the Codex subscription, tasks 1 to 20

**Mean score 0.43** over 20 tasks, none failed: 0.29 on tasks 1 to 10 and 0.56 on tasks 11 to 20. This is a pilot
to test running tasks in parallel, not a benchmark result: 20 of 200 tasks, one trial each.

### Parameters

| | |
|---|---|
| Repo commit | `2aefd79` |
| Command | `uv run --env-file .env python -m agents.browser.evals.run --model 6.1-terra-codex --tasks 1-10 --concurrency 5 --save agents/browser/evals/.reports/2026-11-27-terra-full.jsonl`, then the same with `--tasks 11-20` |
| When | Tasks 1 to 10: 06:50:59 to 06:57:22 UTC, wall time 382 s. Tasks 11 to 20: 07:04:26 to 07:15:45 UTC, wall time 678 s. |
| Tasks | `bu2-001` to `bu2-020`, one trial each, 5 at a time |
| Agent | `agents/browser/agent.py`, unchanged: one Pydantic AI `Agent` with `PlaywrightBrowser()` at its defaults (local headless Chromium) |
| Agent model | `openai-codex:gpt-6.1-terra` (config entry `6.1-terra-codex`), default settings. It ran on a Codex/ChatGPT subscription through the Codex CLI login, not on the OpenAI API key. |
| Limits | 200 model requests and 3600 s per task |
| Versions | pydantic-ai 2.75.0, pydantic-ai-harness 0.75.0, pydantic-evals 2.75.0, playwright 1.65.2, Python 3.13.12 |
| Judge | The benchmark's own `judge_trace` at commit `77b4df3`: `gpt-5.6-luna`, reasoning effort `xhigh`, on the OpenAI API key |
| Machine | macOS (Darwin 25.5.0), run locally, one IP address |

### Results

Agent cost is **notional**: the API price of the tokens used. The run was on the subscription, so no money was
spent on the agent. Judge cost was spent.

| Task | Score | Agent run time | Model requests | Agent cost (notional) | Judge cost |
|---|---|---|---|---|---|
| `bu2-001` | 0.00 | 45 s | 8 | $0.038 | $0.016 |
| `bu2-002` | 0.48 | 37 s | 7 | $0.019 | $0.022 |
| `bu2-003` | 0.78 | 74 s | 12 | $0.031 | $0.023 |
| `bu2-004` | 0.32 | 80 s | 16 | $0.025 | $0.022 |
| `bu2-005` | 0.16 | 64 s | 11 | $0.023 | $0.038 |
| `bu2-006` | 0.12 | 19 s | 4 | $0.006 | $0.023 |
| `bu2-007` | 0.04 | 27 s | 8 | $0.017 | $0.012 |
| `bu2-008` | 0.12 | 66 s | 17 | $0.078 | $0.025 |
| `bu2-009` | 0.54 | 74 s | 7 | $0.035 | $0.032 |
| `bu2-010` | 0.32 | 21 s | 4 | $0.009 | $0.016 |
| `bu2-011` | 0.85 | 121 s | 9 | $0.070 | $0.046 |
| `bu2-012` | 0.32 | 61 s | 10 | $0.056 | $0.025 |
| `bu2-013` | 0.12 | 15 s | 3 | $0.010 | $0.005 |
| `bu2-014` | 0.56 | 94 s | 11 | $0.080 | $0.046 |
| `bu2-015` | 0.76 | 96 s | 15 | $0.057 | $0.037 |
| `bu2-016` | 0.50 | 114 s | 26 | $0.099 | $0.036 |
| `bu2-017` | 0.92 | 107 s | 17 | $0.062 | $0.035 |
| `bu2-018` | 0.55 | 101 s | 11 | $0.043 | $0.023 |
| `bu2-019` | 0.64 | 278 s | 44 | $0.158 | $0.041 |
| `bu2-020` | 0.41 | 71 s | 12 | $0.054 | $0.041 |
| **Mean, 1 to 10** | **0.29** | 51 s | 9.4 | $0.028 | $0.023 |
| **Mean, 11 to 20** | **0.56** | 106 s | 15.8 | $0.069 | $0.033 |
| **Mean, all 20** | **0.43** | 78 s | 12.6 | $0.049 | $0.028 |
| **Total, all 20** | | 1,563 s | 252 | $0.97 | $0.56 |

Per task the agent used about 98,000 input tokens on tasks 1 to 10 and 344,000 on tasks 11 to 20, most of them
read from cache, and 1,200 to 2,900 output tokens. The 20 tasks used about 4.4 million input tokens in all.

### What the runs showed

- **No failures and no limit errors.** All 20 tasks were run and judged. There was no rate-limit, quota, usage-limit
  or auth error from the Codex backend at 5 in parallel.
- **Sites blocked the browser.** In 13 of the 20 tasks the judge's evidence reports a bot check, a CAPTCHA or an
  access-denied page: `001`, `002`, `006`, `007`, `009`, `010`, `011`, `013`, `014`, `015`, `016`, `017`, `018`.
  Some blocks came from the task's target site, some from a search engine the agent tried on the way.
- **Seven runs stopped within 8 model requests** (`001`, `002`, `006`, `007`, `009`, `010`, `013`), and all seven
  are among the blocked ones. Their mean score is 0.23; the other thirteen average 0.53. Where only a search engine
  blocked, the agent usually carried on and scored higher.
- The runs cannot tell whether 5 browsers from one IP made the blocking worse: there is no solo run of these tasks
  to compare with.
- **The runs were short.** The agent made 3 to 44 model requests per task, against 45 to 65 on task `bu2-052`.
  Blocked pages explain part of it. Whether the model also behaves differently on the Codex backend than on the
  API was not tested.
- **Speed per request** was about 6.2 s (1,563 s over 252 requests), against about 4 s on the solo `bu2-052` runs.
  The tasks and pages differ, so this is weak evidence either way.
- **The judge takes much of the wall time.** On tasks 1 to 10 the agent's runs took at most 80 s, but two rounds of
  five tasks took 382 s, so a judge call is on the order of two minutes.

### Projection for the remaining 180 tasks

At 5 in parallel, from these 20 tasks: 53 s of wall time, $0.028 of judge cost, $0.049 of notional agent cost and
about 221,000 input tokens per task.

| | If tasks are like these 20 | If tasks are like `bu2-052` |
|---|---|---|
| Wall time | about 2.5 to 3.5 hours | about 3.5 hours |
| Judge cost (spent) | about $5 | about $8 |
| Agent cost (notional, not spent) | about $9 | about $34 |
| Agent input tokens | about 40 million | about 270 million |

The second column uses the measured `bu2-052` figures: $0.19 agent, $0.045 judge, about 220 s and 1.5 million
input tokens per task. The range in the first column is tasks 1 to 20 against tasks 11 to 20 alone, which ran
longer. These runs give no measure of the subscription's quota: 20 tasks used about 4.4 million input tokens
without a limit signal, which says little about 40 to 270 million.
