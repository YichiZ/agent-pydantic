"""Browser agent eval on BU Bench tasks (../docs/eval-plan.md).  uv run --env-file .env python -m agents.browser.evals.run"""

import argparse
import asyncio
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import load_dotenv
from genai_prices import Usage, calc_price
from pydantic_ai import Agent, UsageLimits
from pydantic_ai.messages import ModelMessage, TextPart, ToolCallPart, ToolReturnPart
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext

from agents.browser.agent import CONFIG, agent, configured, trace_to_logfire

TASK_ID = 'bu2-052'  # the default task
BENCHMARK = Path(__file__).parent / '.benchmark'  # the user's clone; gitignored
COMMIT = '77b4df339fe8fc293fb48896cfa1c73dd743af42'
TASK_TIMEOUT = 3600  # seconds for one agent run, and for one judge call: TASK_TIMEOUT in the benchmark's run_eval.py
REQUEST_LIMIT = 200  # model requests per trial: a cost guard, the same for every model. Pydantic AI's default is 50.
# Runs inside the clone's own environment, so the rubric never enters this process.
JUDGE_SNIPPET = """
import asyncio, json, sys
from evaluation import load_tasks, create_judge, judge_trace
task = next(t for t in load_tasks() if t['task_id'] == sys.argv[1])
llm, tokens = create_judge(), {'input': 0, 'output': 0}
call = llm.ainvoke
async def counted(*args, **kwargs):  # judge_trace does not return the judge's token usage, so note it here
    response = await call(*args, **kwargs)
    if response.usage:
        tokens.update(input=response.usage.prompt_tokens, output=response.usage.completion_tokens)
    return response
llm.ainvoke = counted
judged = asyncio.run(judge_trace(task, json.load(open(sys.argv[2])), llm))
print(json.dumps({**judged, 'judge_model': llm.model, 'judge_tokens': tokens}))
"""


def task_texts() -> dict[str, str]:
    """Every task's instruction by task id, decrypted in memory. Only the `id` and `task` fields are read."""
    key = base64.urlsafe_b64encode(hashlib.sha256(b'BU_Bench_V2').digest())
    tasks = json.loads(Fernet(key).decrypt(base64.b64decode((BENCHMARK / 'BU_Bench_V2.enc').read_text())))['tasks']
    return {t['id']: t['task'] for t in tasks}


def task_ids(spec: str, known: Sequence[str]) -> list[str]:
    """The task ids `--tasks` names: `all`, a number range such as `1-10`, or a comma list of ids."""
    if spec == 'all':
        return list(known)
    span = re.fullmatch(r'(\d+)-(\d+)', spec)
    ids = [f'bu2-{n:03d}' for n in range(int(span[1]), int(span[2]) + 1)] if span else spec.split(',')
    unknown = [task_id for task_id in ids if task_id not in known]
    if unknown or not ids:
        raise ValueError(f'--tasks {spec}: no such task: {", ".join(unknown) or "empty range"}')
    return ids


def saved_ids(save: str | None) -> set[str]:
    """The task ids already judged in the `--save` file, so that a repeated command skips them."""
    if not save or not Path(save).exists():
        return set()
    lines = Path(save).read_text().splitlines()
    # A line cut short by a kill mid-write is not valid JSON: skip it, and that task runs again.
    return {json.loads(line)['task'] for line in lines if line.endswith('}')}


def trace(messages: Sequence[ModelMessage], answer: str) -> dict:
    """The run as the judge reads it: tool calls, tool results and assistant text in order. No thinking."""
    steps = []
    for part in (part for message in messages for part in message.parts):
        if isinstance(part, ToolCallPart):
            steps.append(f'tool call {part.tool_name}: {part.args_as_json_str()}')
        elif isinstance(part, ToolReturnPart):
            steps.append(f'tool result {part.tool_name}: {part.model_response_str()}')
        elif isinstance(part, TextPart):
            steps.append(f'assistant: {part.content}')
    return {'agent_steps': steps, 'final_result': answer, 'screenshots_b64': []}


async def run(prompt: str, agent: Agent = agent) -> dict:
    result = await agent.run(prompt, usage_limits=UsageLimits(request_limit=REQUEST_LIMIT))
    # The judge ignores keys it does not know, so the agent's cost rides along to the evaluator. A model with no
    # known price has no cost: report 0 rather than lose the run.
    return {**trace(result.all_messages(), result.output), 'agent_cost_usd': float(result.usage.cost or 0),
            'requests': result.usage.requests}


def results(judged: dict) -> dict:
    """The judge's output as Pydantic Evals results: pass/fail per rubric item, the score (0 to 1), and what the
    judge call cost, priced from its token counts."""
    findings = judged['judgement']['findings']
    items = {f['item']: EvaluationReason(value=f['status'] == 'met', reason=f['evidence']) for f in findings}
    tokens = judged['judge_tokens']
    price = calc_price(Usage(input_tokens=tokens['input'], output_tokens=tokens['output']),
                       model_ref=judged['judge_model'], provider_id='openai')
    return {**items, 'score': judged['score'], 'judge_cost_usd': float(price.total_price)}


def summary(judged: Sequence[dict], failures: Sequence[str], wall_seconds: float) -> str:
    """The run in a few lines. `judged` holds one dict of numbers per judged task; `failures` one kind per failed one."""
    total, scores = len(judged) + len(failures), sum(j['score'] for j in judged)
    kinds = ', '.join(f'{kind} x{n}' for kind, n in Counter(failures).items()) or 'none'
    return '\n'.join([
        f'tasks run: {total}, judged: {len(judged)}, failed: {len(failures)} ({kinds})',
        f'mean score over judged tasks: {scores / len(judged):.3f}' if judged else 'no task was judged',
        f'mean score counting failures as 0: {scores / total:.3f}' if total else 'nothing to run',
        f'agent cost: ${sum(j["agent_cost_usd"] for j in judged):.2f} (judged tasks only: a failed run reports none)',
        f'judge cost: ${sum(j["judge_cost_usd"] for j in judged):.2f}',
        f'wall time: {wall_seconds:.0f} s',
    ])  # fmt: skip


@dataclass
class BUBenchJudge(Evaluator):
    save: str | None = None  # a JSON Lines file: one line per judged task. It holds judge evidence: local only.

    async def evaluate(self, ctx: EvaluatorContext) -> dict:
        with tempfile.NamedTemporaryFile('w', suffix='.json') as file:
            json.dump(ctx.output, file)
            file.flush()
            command = ['uv', 'run', '--project', str(BENCHMARK), 'python', '-c', JUDGE_SNIPPET, ctx.metadata, file.name]
            env = {**os.environ, 'ANONYMIZED_TELEMETRY': 'false'}  # browser-use reports usage unless told not to
            done = await asyncio.to_thread(subprocess.run, command, cwd=BENCHMARK, env=env, capture_output=True,
                                           text=True, timeout=TASK_TIMEOUT)
        if done.returncode:  # a judge error fails the trial; it is not scored as zero
            raise RuntimeError(f'The judge exited with {done.returncode}:\n{done.stderr[-2000:]}')
        judged = json.loads(done.stdout.splitlines()[-1])  # the snippet prints its JSON last
        got = results(judged)
        numbers = {'score': got['score'], 'agent_cost_usd': ctx.output['agent_cost_usd'],
                   'judge_cost_usd': got['judge_cost_usd'], 'requests': ctx.output['requests']}
        if self.save:  # appended as soon as the task is judged, so a crash later loses nothing finished
            items = {name: {'met': item.value, 'evidence': item.reason} for name, item in got.items()
                     if isinstance(item, EvaluationReason)}
            with open(self.save, 'a') as file:
                file.write(json.dumps({'task': ctx.metadata, **numbers, 'agent_seconds': ctx.duration,
                                       'items': items}) + '\n')
        return {**got, **numbers}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='python -m agents.browser.evals.run')
    parser.add_argument('trials', nargs='?', type=int, default=1)
    parser.add_argument('--model', choices=list(CONFIG['models']), default=CONFIG['default'],
                        help='an entry of agents/browser/config.yaml (default: %(default)s)')
    parser.add_argument('--tasks', default=TASK_ID,
                        help='`all`, a number range such as 1-10, or a comma list of task ids (default: %(default)s)')
    parser.add_argument('--concurrency', type=int, default=1, help='tasks run at once (default: %(default)s)')
    parser.add_argument('--save', help='append one JSON line per judged task to this file; tasks already in it are '
                                       'skipped, so repeating the command resumes a run. Keep it out of git.')
    args = parser.parse_args(argv)  # a mistyped key stops here, before anything is spent
    if args.save and args.trials > 1:
        parser.error('--save skips a task once it has one line, so it cannot resume repeated trials: use one trial')
    chosen = configured(args.model)
    load_dotenv()  # ANTHROPIC_API_KEY, OPENAI_API_KEY and LOGFIRE_TOKEN from .env; real env vars win
    trace_to_logfire()
    if not BENCHMARK.exists():
        print(f'Clone the benchmark first:\n  git clone https://github.com/browser-use/benchmark {BENCHMARK}\n'
              f'  git -C {BENCHMARK} checkout {COMMIT}', file=sys.stderr)
        return 2
    texts = task_texts()
    try:
        ids = task_ids(args.tasks, list(texts))
    except ValueError as error:
        parser.error(str(error))
    skipped = saved_ids(args.save)
    cases = [Case(name=task_id, inputs=texts[task_id], metadata=task_id) for task_id in ids if task_id not in skipped]
    dataset = Dataset(name='bu_bench_v2', cases=cases, evaluators=[BUBenchJudge(save=args.save)])
    print(f'model {args.model}: {chosen.model}, agent {chosen.name}')  # every saved report says what produced it
    print(f'tasks {args.tasks}: {len(cases)} to run, {len(ids) - len(cases)} already saved')
    started = time.perf_counter()
    # A task that raises or times out, or whose judge fails, is reported as a failure; the others go on.
    report = dataset.evaluate_sync(partial(run, agent=chosen), task_name='run', repeat=args.trials,
                                   max_concurrency=args.concurrency, task_timeout=TASK_TIMEOUT)
    wall_seconds = time.perf_counter() - started
    report.print(include_reasons=True)
    judged = [{name: score.value for name, score in case.scores.items()} for case in report.cases
              if not case.evaluator_failures]
    failures = [failure.error_message.split(':')[0] for failure in report.failures]
    failures += ['judge ' + failure.error_message.split(':')[0] for case in report.cases
                 for failure in case.evaluator_failures]
    print(summary(judged, failures, wall_seconds))
    return 0


if __name__ == '__main__':
    sys.exit(main())
