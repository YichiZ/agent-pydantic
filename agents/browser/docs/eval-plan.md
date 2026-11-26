# Browser agent eval: BU Bench V2.1 task 52

Status: plan, not built.

## Goal

A baseline score for the browser agent, unchanged, on task `bu2-052` of
[BU Bench V2.1](https://github.com/browser-use/benchmark), scored by the benchmark's own judge code so the
number means what a BU Bench number means.

Not in scope: other tasks, changes to the agent (prompt, tools, model settings, prompt caching), a subcommand
on `python -m agents browser`, screenshots as evidence, saved runs, a baseline file.

## Decisions

| Question | Decision |
|---|---|
| Framework | Pydantic Evals: one `Dataset`, one `Case`, one custom `Evaluator`, `repeat` for trials. |
| Judge | The benchmark's `evaluation.judge_trace`, unmodified: `gpt-5.6-luna`, their prompt, their scoring. |
| How their code is loaded | The user clones the benchmark once into a gitignored folder (command in the README). The judge runs in a subprocess inside the clone's own environment (`uv run --project`), so `browser-use` never becomes a dependency of this repo and none of their code is copied in. |
| Task and rubric | Read from the clone's `BU_Bench_V2.enc`, decrypted in memory. Our process reads only the task text; the rubric is read only inside the judge subprocess. |
| Evidence | From the Pydantic AI message history: every tool call, tool result and piece of assistant text as a step, plus the final answer. No thinking, no screenshots. |
| Trials | One argument: the number of trials, default 1. The baseline is 3. |
| Baseline | A line in `agents/browser/README.md`: each trial's score, the date, the benchmark commit. Compared by eye. |
| Cost | About $3.72 per trial for the agent plus one judge call. Baseline of 3: about $11 plus judge calls. |
| Invocation | `uv run --env-file .env python -m agents.browser.eval [trials]`. `agent.py` and `agents/__main__.py` are not touched. |

Approaches considered for the judge: our own judge on GPT or on Claude with the same rubric and arithmetic
(nothing to fetch, but the score would not be a BU Bench score), and the official code (chosen). Adding
`browser-use==0.11.5` to this repo's dependencies to import the judge directly was rejected: it pins its own
model SDK versions, and the benchmark repo has no licence.

## Files

```
agents/browser/eval.py                  # the whole eval, about 60 lines
agents/browser/tests/test_eval.py       # one offline test
agents/browser/.benchmark/              # gitignored: the user's clone of the benchmark
```

Also: `.gitignore` gets `.benchmark/`, `pyproject.toml` declares `cryptography` (already installed, used to
read the task text), and `agents/browser/README.md` gets the setup command, the run command and the baseline.

## How one trial runs

1. If `.benchmark/` is missing, exit with the clone command.
2. Decrypt `.benchmark/BU_Bench_V2.enc` and take the `task` text of `bu2-052`.
3. The task function runs `agent.run(task_text)` and returns the trace the judge expects:
   - `agent_steps`: one string per tool call (name and arguments as JSON), per tool result (its text) and per
     piece of assistant text, in order;
   - `final_result`: the agent's answer;
   - `screenshots_b64`: empty.
4. The evaluator writes the trace to a temporary file and runs, with the clone as the working directory,
   `uv run --project .benchmark python -c <snippet> bu2-052 <trace file>`. The snippet is a five-line constant
   in `eval.py` that calls the benchmark's `load_tasks`, `create_judge` and `judge_trace` and prints the result
   as JSON.
5. The evaluator returns one pass/fail per rubric item (met or not, with the judge's evidence as the reason)
   and `score`. A judge error fails the trial; it is not scored as zero.

## Commands and output

```bash
git clone https://github.com/browser-use/benchmark agents/browser/.benchmark   # once
git -C agents/browser/.benchmark checkout 77b4df3                              # the pinned commit
uv run --env-file .env python -m agents.browser.eval 3                         # three trials
```

Prints the Pydantic Evals report: per trial, ten pass/fail items with the judge's reasons and a score, then the
averages.

## Test

One offline test, no network and no model: a small hand-built message history becomes the expected
`agent_steps` and `final_result`.

## Build order

1. `eval.py` trace building and its test.
2. The judge subprocess and the evaluator. Check that the clone's environment installs with `uv run --project`.
3. One live trial, about $4. Needs the user's go-ahead.
4. Two more trials for the baseline, about $8. Needs the user's go-ahead. Write the baseline into the README.

## Known limits

- One task, ten all-or-nothing items: the score moves in steps of 6 to 18 points, and 3 trials give a rough
  mean, not a tight one.
- The live web and web.archive.org change and rate-limit; a trial can fail for reasons outside the agent.
- No screenshots: the judge sees page text from tool results only. Add them if the agent starts relying on
  screenshots.
- Runs are not saved: a failed judge call loses that trial's agent run. Add a saved trace and a re-judge
  option if that happens more than once.
