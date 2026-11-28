# Browser agent

An agent you chat with in the terminal that browses the web in a real browser. It is a
[Pydantic AI](https://pydantic.dev/docs/ai/overview/) `Agent` with the Playwright browser capability from
`pydantic-ai-harness`, and nothing else: see `agent.py`.

The model and the agent's name come from [config.yaml](config.yaml): one entry per model, each with the full
Pydantic AI model string and a name, and a `default`. Chat and the eval run on the default unless `--model` picks
another entry. The default is `6.1-terra-codex`: gpt-6.1-terra on a Codex/ChatGPT subscription (the Codex CLI
login) instead of `OPENAI_API_KEY`; the cost it reports is then the API-equivalent price, not money spent.

It can open any public page; private and loopback addresses are blocked. The browser closes after each
turn, so the conversation carries between turns but logins and open pages do not.

```bash
uv run python -m agents browser                            # chat on the default; needs the Codex CLI login
uv run python -m agents browser --model sonnet-5.5         # chat on another entry; this one needs ANTHROPIC_API_KEY in .env
uv run pytest agents/browser                                # offline test, no API key, no browser
uv run pytest -m e2e agents/browser                         # live test against quotes.toscrape.com, on the default
```

## Eval

Task `bu2-052` of [BU Bench V2.1](https://github.com/browser-use/benchmark), scored by the benchmark's own judge:
see `evals/run.py` and [docs/eval-plan.md](docs/eval-plan.md).

The eval measures three things for each trial, and a recorded run should give all three:

- **Accuracy**: the judge's score from 0 to 1, and met or violated for each of the ten rubric items.
- **Time**: how long the agent's run took, in seconds. It is the task duration in the report; judge time is not
  part of it.
- **Cost**: `agent_cost_usd` for the agent's model usage and `judge_cost_usd` for the judge call.

A change to the agent or its model is judged on all three, not on the score alone.

A trial costs one OpenAI judge call (about $0.05) plus the agent: nothing on the default (the Codex subscription),
about $0.20 with `--model 6.1-terra` and about $4 with `--model sonnet-5.5`. The report shows both as
`agent_cost_usd` and `judge_cost_usd`. A trial stops with an error after 200 model requests (`REQUEST_LIMIT` in
`evals/run.py`). The judge needs `OPENAI_API_KEY` in `.env`; `--model sonnet-5.5` also needs `ANTHROPIC_API_KEY`.

```bash
git clone https://github.com/browser-use/benchmark agents/browser/evals/.benchmark   # once; gitignored
git -C agents/browser/evals/.benchmark checkout 77b4df339fe8fc293fb48896cfa1c73dd743af42
uv run --env-file .env python -m agents.browser.evals.run 3                          # three trials, one at a time
uv run --env-file .env python -m agents.browser.evals.run --model 6.1-terra          # one trial on another config.yaml entry
```

The same command runs other tasks of the benchmark, several at a time:

```bash
uv run --env-file .env python -m agents.browser.evals.run --tasks 1-10 --concurrency 5 \
  --save agents/browser/evals/.reports/full.jsonl                                    # tasks bu2-001 to bu2-010
uv run --env-file .env python -m agents.browser.evals.run --tasks all --concurrency 5 \
  --save agents/browser/evals/.reports/full.jsonl                                    # all 200; skips the saved ones
```

- `--tasks` takes `all`, a number range such as `1-10`, or a comma list of ids such as `bu2-052,bu2-007`. The
  default is `bu2-052`.
- `--concurrency` is how many tasks run at once (default 1). Each has its own browser and its own judge process.
- `--save FILE` appends one JSON line to FILE as soon as a task is judged: score, result and judge evidence per
  rubric item, agent and judge cost, model requests, agent run time. Tasks already in FILE are skipped, so
  repeating the command resumes an interrupted run. The file holds judge evidence: keep it in `evals/.reports/`.
  Use one file per model, and one trial.
- A task that fails (request limit, model error, the 3600 s timeout, judge error) does not stop the others and is
  not saved, so a repeated command runs it again. The run ends with a summary: failures by kind, mean score with
  and without failures counted as 0, total cost and wall time.

The full 200-task run of `6.1-terra-codex` (mean score 0.38) is in [evals/runs/full-benchmark.md](evals/runs/full-benchmark.md).

Baseline on `sonnet-5.5` (2026-11-26, 3 trials): mean score 0.72 (0.70, 0.86, 0.60). The parameters and the result per rubric item
are in [evals/runs/README.md](evals/runs/README.md). Save a run's full report to `evals/.reports/` (gitignored): it
paraphrases the benchmark's rubric, so only scores and per-item results are committed.

## Traces

Chat and eval runs can be sent to [Logfire](https://pydantic.dev/docs/logfire/), so you can see where a run went
wrong. It is off until this checkout has Logfire credentials; without them nothing is sent and nothing is printed.

Set it up once, from the repo root, with a free Logfire account and a project in it:

```bash
uvx logfire-cli --region us auth                        # sign in through the browser; --region eu for an EU account
uvx logfire-cli --region us init use --name <project>   # writes .logfire/logfire_credentials.json (gitignored)
```

Instead of the CLI, you can create a write token in the project's settings and put it in `.env` as `LOGFIRE_TOKEN`.
Either one turns tracing on; the token wins if both are set. The credentials file is only found when you run from
the repo root.

Each run then shows up in the project's Live view under the service `browser`, as one trace:

- `invoke_agent browser-agent-terra-codex`: the whole run, named after the config entry, with the final output and
  token usage.
- `chat gpt-6.1-terra`: one per model request, with the messages sent and the reply.
- `execute_tool <tool>`: one per tool call, with its arguments and result. A failed call is not marked as an error:
  the error text is the result the model got back.
- `browser <action>`: the browser operation under each tool call, with `browser.outcome` set to `ok` or `error`.
  What the page did during it is attached as events: console messages, page errors, responses (4xx and 5xx marked
  as errors), and failed or blocked requests.

The eval is a Pydantic Evals experiment, so its trace should start with an `evaluate run` span (dataset
`bu_bench_v2`), with each trial's agent run under it. That is from the library source: no eval has been run with
tracing on yet.

Logfire's default scrubbing can redact text that contains words like "session" or "cookie"; the Playwright
capability's README shows how to keep it. The setup is `trace_to_logfire()` in `agent.py`.
