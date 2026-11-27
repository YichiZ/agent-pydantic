import asyncio
import json
import subprocess

import pytest
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.test import TestModel
from pydantic_evals import Case, Dataset

from agents.browser.agent import agent
from agents.browser.evals.run import BUBenchJudge, results, run, saved_ids, summary, task_ids, trace


def test_trace_keeps_tool_calls_results_and_text_in_order():
    # Offline: a hand-built history. Thinking and the user prompt stay out of the steps.
    messages = [
        ModelRequest(parts=[UserPromptPart('What does the page say?')]),
        ModelResponse(
            parts=[
                ThinkingPart('I should open the page.'),
                TextPart('Opening the page.'),
                ToolCallPart('navigate', {'url': 'https://example.com'}),
            ]
        ),
        ModelRequest(parts=[ToolReturnPart('navigate', 'Example Domain')]),
        ModelResponse(parts=[TextPart('It says Example Domain.')]),
    ]
    assert trace(messages, 'It says Example Domain.') == {
        'agent_steps': [
            'assistant: Opening the page.',
            'tool call navigate: {"url":"https://example.com"}',
            'tool result navigate: Example Domain',
            'assistant: It says Example Domain.',
        ],
        'final_result': 'It says Example Domain.',
        'screenshots_b64': [],
    }


def test_results_gives_each_item_the_score_and_the_judge_cost():
    judged = {
        'score': 0.6,
        'judgement': {'findings': [{'item': 'A1', 'status': 'met', 'evidence': 'seen'},
                                   {'item': 'A2', 'status': 'not_assessable', 'evidence': 'clipped'}]},
        'judge_model': 'gpt-5.6-luna',
        'judge_tokens': {'input': 60_000, 'output': 20_000},
    }
    got = results(judged)
    assert (got['A1'].value, got['A2'].value, got['score']) == (True, False, 0.6)
    assert got['judge_cost_usd'] > 0


def test_run_returns_the_trace_and_a_cost_offline():
    # TestModel has no price, so the cost is 0; the run must still come back whole.
    with agent.override(model=TestModel(call_tools=[])):
        ran = asyncio.run(run('hello'))
    assert set(ran) == {'agent_steps', 'final_result', 'screenshots_b64', 'agent_cost_usd', 'requests'}
    assert ran['agent_cost_usd'] == 0.0


def test_run_stops_at_the_request_limit(monkeypatch):
    monkeypatch.setattr('agents.browser.evals.run.REQUEST_LIMIT', 0)
    with agent.override(model=TestModel(call_tools=[])), pytest.raises(UsageLimitExceeded, match='request_limit of 0'):
        asyncio.run(run('hello'))


def test_task_ids_takes_all_a_range_or_a_list():
    known = [f'bu2-{n:03d}' for n in range(1, 201)]
    assert task_ids('all', known) == known
    assert task_ids('9-11', known) == ['bu2-009', 'bu2-010', 'bu2-011']
    assert task_ids('bu2-052,bu2-007', known) == ['bu2-052', 'bu2-007']
    for bad in ['199-201', '5-4', 'bu2-999', '']:
        with pytest.raises(ValueError, match='no such task'):
            task_ids(bad, known)


def test_summary_counts_failures_as_zero():
    judged = [{'score': 1.0, 'agent_cost_usd': 0.2, 'judge_cost_usd': 0.05},
              {'score': 0.5, 'agent_cost_usd': 0.1, 'judge_cost_usd': 0.05}]
    text = summary(judged, ['UsageLimitExceeded', 'TimeoutError', 'UsageLimitExceeded'], 61.2)
    assert 'tasks run: 5, judged: 2, failed: 3 (UsageLimitExceeded x2, TimeoutError x1)' in text
    assert 'over judged tasks: 0.750' in text and 'failures as 0: 0.300' in text
    assert 'agent cost: $0.30' in text and 'judge cost: $0.10' in text and 'wall time: 61 s' in text
    assert 'no task was judged' in summary([], [], 0)


def test_a_judged_task_is_saved_a_failed_one_is_not_and_neither_stops_the_rest(tmp_path, monkeypatch):
    # Offline: the judge subprocess is faked, and the task for bu2-002 raises.
    judged = {'score': 0.4, 'judgement': {'findings': [{'item': 'A1', 'status': 'met', 'evidence': 'seen'}]},
              'judge_model': 'gpt-5.6-luna', 'judge_tokens': {'input': 1000, 'output': 100}}
    judged_ids = []

    def fake_judge(command, **kwargs):
        judged_ids.append(command[-2])
        return subprocess.CompletedProcess(command, 0, stdout='noise\n' + json.dumps(judged), stderr='')

    monkeypatch.setattr(subprocess, 'run', fake_judge)

    async def task(prompt: str) -> dict:
        if prompt == 'two':
            raise RuntimeError('boom')
        return {'agent_steps': [], 'final_result': prompt, 'screenshots_b64': [], 'agent_cost_usd': 0.1, 'requests': 3}

    save = tmp_path / 'run.jsonl'
    assert saved_ids(str(save)) == saved_ids(None) == set()
    cases = [Case(name=i, inputs=text, metadata=i) for i, text in [('bu2-001', 'one'), ('bu2-002', 'two'),
                                                                   ('bu2-003', 'three')]]
    report = Dataset(name='t', cases=cases, evaluators=[BUBenchJudge(save=str(save))]).evaluate_sync(
        task, max_concurrency=2, progress=False)

    assert [failure.error_message for failure in report.failures] == ['RuntimeError: boom']
    assert sorted(judged_ids) == ['bu2-001', 'bu2-003']  # the judge is told the case's task, not a constant
    assert saved_ids(str(save)) == {'bu2-001', 'bu2-003'}
    row = json.loads(save.read_text().splitlines()[0])
    save.write_text(save.read_text() + '{"task": "bu2-00')  # a line cut short by a kill
    assert saved_ids(str(save)) == {'bu2-001', 'bu2-003'}
    assert set(row) == {'task', 'score', 'agent_cost_usd', 'judge_cost_usd', 'requests', 'agent_seconds', 'items'}
    assert (row['score'], row['requests'], row['items']) == (0.4, 3, {'A1': {'met': True, 'evidence': 'seen'}})
