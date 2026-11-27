# Full benchmark runs

Runs of the browser agent on many tasks of BU Bench V2.1 (200 tasks, `bu2-001` to `bu2-200`). Only scores and
numbers are recorded here: no task text, no rubric items, no judge evidence. The per-task lines with the judge's
evidence stay in `../.reports/` (gitignored, local only).

## 2026-11-27: gpt-6.1-terra on the Codex subscription, pilot of 10 tasks

**Mean score 0.29** over 10 tasks, none failed. This is a pilot to test running tasks in parallel, not a benchmark
result: 10 of 200 tasks, one trial each.

### Parameters

| | |
|---|---|
| Repo commit | `2aefd79` |
| Command | `uv run --env-file .env python -m agents.browser.evals.run --model 6.1-terra-codex --tasks 1-10 --concurrency 5 --save agents/browser/evals/.reports/2026-11-27-terra-full.jsonl` |
| When | 06:50:59 to 06:57:22 UTC, wall time 382 s |
| Tasks | `bu2-001` to `bu2-010`, one trial each, 5 at a time |
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
| **Mean** | **0.29** | 51 s | 9.4 | $0.028 | $0.023 |
| **Total** | | 506 s | 94 | $0.28 | $0.23 |

Per task the agent used about 98,000 input tokens (79,000 of them read from cache) and 1,200 output tokens.

### What the pilot showed

- **No failures and no limit errors.** All 10 tasks were run and judged. There was no rate-limit, quota, usage-limit
  or auth error from the Codex backend at 5 in parallel.
- **Sites blocked the browser.** In 6 of the 10 tasks (`001`, `002`, `006`, `007`, `009`, `010`) the judge's
  evidence reports a bot check or an access-denied page from the target site. In several the block came on the
  first page opened. The mean score of those six is 0.25; of the other four, 0.35. The pilot cannot tell whether
  running 5 browsers from one IP made this worse: there is no solo run of these tasks to compare with.
- **The runs were short.** The agent made 4 to 17 model requests per task and stopped, against 45 to 65 on task
  `bu2-052`. Blocked pages explain part of it. Whether the model also behaves differently on the Codex backend
  than on the API was not tested.
- **Speed per request** was about 5.4 s (506 s over 94 requests), against about 4 s on the solo `bu2-052` runs. The
  tasks and pages differ, so this is weak evidence either way.
- **The judge takes most of the wall time.** The agent's runs took at most 80 s, but two rounds of five tasks took
  382 s, so a judge call is on the order of two minutes.

### Projection for the remaining 190 tasks

At 5 in parallel, from this pilot's rate of 38 s of wall time per task:

| | If tasks are like these 10 | If tasks are like `bu2-052` |
|---|---|---|
| Wall time | about 2 hours | about 4 hours |
| Judge cost (spent) | about $4.40 | about $8.50 |
| Agent cost (notional, not spent) | about $5.30 | about $36 |
| Agent input tokens | about 19 million | about 285 million |

The second column uses the measured `bu2-052` figures: $0.19 agent, $0.045 judge, about 220 s and 1.5 million
input tokens per task. The pilot gives no measure of the subscription's quota: 10 tasks used about 1 million input
tokens without a limit signal, which says little about 19 to 285 million.
