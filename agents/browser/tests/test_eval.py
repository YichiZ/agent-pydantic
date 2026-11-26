from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from agents.browser.evals.run import results, trace


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
