"""Browser agent eval on BU Bench task 52 (../docs/eval-plan.md).  uv run --env-file .env python -m agents.browser.evals.run"""

import asyncio
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import load_dotenv
from genai_prices import Usage, calc_price
from pydantic_ai.messages import ModelMessage, TextPart, ToolCallPart, ToolReturnPart
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext

from agents.browser.agent import agent

TASK_ID = 'bu2-052'
BENCHMARK = Path(__file__).parent / '.benchmark'  # the user's clone; gitignored
COMMIT = '77b4df339fe8fc293fb48896cfa1c73dd743af42'
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


def task_text() -> str:
    """The task's instruction, decrypted in memory. Only the `task` field is read."""
    key = base64.urlsafe_b64encode(hashlib.sha256(b'BU_Bench_V2').digest())
    tasks = json.loads(Fernet(key).decrypt(base64.b64decode((BENCHMARK / 'BU_Bench_V2.enc').read_text())))['tasks']
    return next(t['task'] for t in tasks if t['id'] == TASK_ID)


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


async def run(prompt: str) -> dict:
    result = await agent.run(prompt)
    # The judge ignores keys it does not know, so the agent's cost rides along to the evaluator. A model with no
    # known price has no cost: report 0 rather than lose the run.
    return {**trace(result.all_messages(), result.output), 'agent_cost_usd': float(result.usage.cost or 0)}


def results(judged: dict) -> dict:
    """The judge's output as Pydantic Evals results: pass/fail per rubric item, the score (0 to 1), and what the
    judge call cost, priced from its token counts."""
    findings = judged['judgement']['findings']
    items = {f['item']: EvaluationReason(value=f['status'] == 'met', reason=f['evidence']) for f in findings}
    tokens = judged['judge_tokens']
    price = calc_price(Usage(input_tokens=tokens['input'], output_tokens=tokens['output']),
                       model_ref=judged['judge_model'], provider_id='openai')
    return {**items, 'score': judged['score'], 'judge_cost_usd': float(price.total_price)}


@dataclass
class BUBenchJudge(Evaluator):
    async def evaluate(self, ctx: EvaluatorContext) -> dict:
        with tempfile.NamedTemporaryFile('w', suffix='.json') as file:
            json.dump(ctx.output, file)
            file.flush()
            command = ['uv', 'run', '--project', str(BENCHMARK), 'python', '-c', JUDGE_SNIPPET, TASK_ID, file.name]
            env = {**os.environ, 'ANONYMIZED_TELEMETRY': 'false'}  # browser-use reports usage unless told not to
            done = await asyncio.to_thread(subprocess.run, command, cwd=BENCHMARK, env=env, capture_output=True,
                                           text=True)
        if done.returncode:  # a judge error fails the trial; it is not scored as zero
            raise RuntimeError(f'The judge exited with {done.returncode}:\n{done.stderr[-2000:]}')
        judged = json.loads(done.stdout.splitlines()[-1])  # the snippet prints its JSON last
        return {**results(judged), 'agent_cost_usd': ctx.output['agent_cost_usd']}


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()  # ANTHROPIC_API_KEY and OPENAI_API_KEY from .env; real env vars win
    args = sys.argv[1:] if argv is None else argv
    trials = int(args[0]) if args else 1
    if not BENCHMARK.exists():
        print(f'Clone the benchmark first:\n  git clone https://github.com/browser-use/benchmark {BENCHMARK}\n'
              f'  git -C {BENCHMARK} checkout {COMMIT}', file=sys.stderr)
        return 2
    dataset = Dataset(name='bu_bench_v2', cases=[Case(name=TASK_ID, inputs=task_text())], evaluators=[BUBenchJudge()])
    # One trial at a time: parallel trials would hammer web.archive.org.
    dataset.evaluate_sync(run, repeat=trials, max_concurrency=1).print(include_reasons=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
