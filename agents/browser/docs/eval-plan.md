# Browser agent eval: BU Bench V2.1 task 52

Status: plan, not built.

## Goal

A baseline score for the browser agent, unchanged, on task `bu2-052` of
[BU Bench V2.1](https://github.com/browser-use/benchmark), scored by the benchmark's own judge code so the
number means what a BU Bench number means. Later runs are compared with the saved baseline.

Not in scope: other tasks, changes to the agent (prompt, tools, model settings, prompt caching), a subcommand
on `python -m agents browser`.

## Decisions

| Question | Decision |
|---|---|
| Framework | Pydantic Evals: one `Dataset`, one `Case`, one custom `Evaluator`, `repeat` for trials. |
| Judge | The benchmark's `evaluation.judge_trace`, unmodified: `gpt-5.6-luna`, their prompt, their scoring. |
| How their code is loaded | A clone of the benchmark at a pinned commit in a gitignored folder. The judge runs in a subprocess inside the clone's own environment (`uv run --project`), so `browser-use` never becomes a dependency of this repo. |
| Task and rubric | Read from the clone's `BU_Bench_V2.enc`, decrypted in memory. Never written to disk in plaintext. The rubric is only ever read inside the judge subprocess. |
| Evidence | From the Pydantic AI message history: every tool call and tool result as a step, the final answer, and any screenshots the agent took. Thinking is left out, as the benchmark does. |
| Trials | 1 by default, `--trials N`. The baseline is 3 trials. |
| Baseline | `baseline.json`, committed: benchmark commit, each trial's score, and met counts per item. No judge text, because it can quote the rubric. |
| Cost | About $3.72 per trial for the agent plus one judge call. Baseline of 3: about $11 plus judge calls. |
| Invocation | `uv run --env-file .env python -m agents.browser.evals.bu_bench`. `agent.py` and `agents/__main__.py` are not touched. |

Approaches considered for the judge: our own judge on GPT or on Claude with the same rubric and arithmetic
(no new code to fetch, but the score would not be a BU Bench score), and the official code (chosen). Adding
`browser-use==0.11.5` to this repo's dependencies in order to import the judge directly was rejected: it pins
its own model SDK versions and the benchmark repo has no licence, so its code is fetched, not copied.

## Files

```
agents/browser/evals/
  __init__.py
  bu_bench.py         # the eval: clone, task text, run the agent, build the trace, evaluator, report, baseline
  official_judge.py   # ~15 lines, run inside the clone's environment: trace.json in, judge result JSON out
  baseline.json       # written by --save
  .benchmark/         # gitignored: the clone
  runs/               # gitignored: messages.json and trace.json per trial
agents/browser/tests/test_bu_bench.py
```

Also: `.gitignore` gets the two folders, `pyproject.toml` declares `cryptography` (already installed, used to
read the task text), and `agents/browser/README.md` gets the commands below.

## How one trial runs

1. First run only: `git clone` the benchmark into `.benchmark/` and check out the pinned commit
   (`77b4df3`, a constant in `bu_bench.py`).
2. Decrypt `BU_Bench_V2.enc` and take the `task` text of `bu2-052`. Nothing else from the task is read here.
3. Run `agent.run(task_text)` inside `capture_run_messages()`. Save the messages to `runs/`. If the agent
   crashes, keep the partial messages and judge them with an empty answer.
4. Build the trace the judge expects:
   - `agent_steps`: one string per tool call (`name` and arguments as JSON), per tool result (its text) and
     per piece of assistant text, in order.
   - `final_result`: the agent's answer.
   - `screenshots_b64`: images found in the messages, in order; `screenshot_timing` is `after`.
5. The evaluator writes `trace.json` and runs
   `uv run --project .benchmark python official_judge.py bu2-052 trace.json` with the clone as the working
   directory. That script calls `load_tasks`, `create_judge` and `judge_trace` and prints the result.
6. The evaluator returns one pass/fail per rubric item (met or not, with the judge's evidence as the reason)
   and `score`. A judge error fails the trial loudly; the saved messages can be judged again.

`--rejudge <messages.json>` skips step 3 and judges a saved run. That gives a first score from the run of
2026-11-26 for the price of one judge call, and means a judge failure never costs another agent run.

## Commands and output

```bash
uv run --env-file .env python -m agents.browser.evals.bu_bench                  # one trial, compared with the baseline
uv run --env-file .env python -m agents.browser.evals.bu_bench --trials 3 --save  # write baseline.json
uv run --env-file .env python -m agents.browser.evals.bu_bench --rejudge runs/<file>.json
```

The Pydantic Evals report is printed with reasons, then:

```
bu2-052  score 0.74  (trials: 0.82 0.74 0.66)
Against the baseline: +0.00
```

## Tests

One offline file, no network and no model:

- a small hand-built message history becomes the expected `agent_steps`, `final_result` and screenshots;
- a canned judge result becomes the right per-item results and score, and a judge error is raised, not scored.

## Build order

1. `bu_bench.py` trace building and its test.
2. Clone step, `official_judge.py`, the evaluator and its test.
3. `--rejudge` on the saved run of 2026-11-26: the first live check, one judge call. Needs the user's go-ahead.
4. Report, `--save`, baseline comparison, README.
5. Baseline run, 3 trials, about $11. Needs the user's go-ahead. Commit `baseline.json`.

## Known limits

- One task, ten all-or-nothing items: the score moves in steps of 6 to 18 points, and 3 trials give a rough
  mean, not a tight one.
- The live web and web.archive.org change and rate-limit; a trial can fail for reasons outside the agent.
- The agent rarely takes screenshots, so the judge's evidence is almost all page text from tool results.
