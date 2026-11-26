import asyncio

import pytest

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

from agents.browser.agent import agent
from agents.browser.evals.run import main, results, run, trace


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
    assert set(ran) == {'agent_steps', 'final_result', 'screenshots_b64', 'agent_cost_usd'}
    assert ran['agent_cost_usd'] == 0.0


def test_model_flag_rejects_an_unknown_key_before_anything_runs(capsys):
    with pytest.raises(SystemExit) as stopped:
        main(['--model', 'nope'])
    assert stopped.value.code == 2
    assert '6.1-terra' in capsys.readouterr().err
