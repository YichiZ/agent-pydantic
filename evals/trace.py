"""The --trace view of one trial: the conversation the agent had, in order, as labelled blocks for a terminal.
`evals.run_event` prints the same view for an event.

Pure functions from a `TrialResult` and its `TrialTrace` to `Line`s, drawn by `evals.trace_color.render`. A turn's
history is read as pydantic-ai messages from the request that carries the turn's prompt: each response's reasoning,
text and tool calls in part order, then the next request's tool results. In pydantic-ai 2.71 a refused call comes
back as a tool return with outcome 'retried' whose text is the refusal; a policy refusal reads "Denied by <rule>:
<reason>" (`ar.errors.PolicyDenied`). A write held for a person is a normal return whose `WriteResult` status is
'held_for_approval'. A response with no tool call is answered by a `RetryFeedbackPart` asking for one. The
final-output call and its return are left out when it succeeded: the turn's reply shows it. A history that is not a
list of pydantic-ai messages (a scripted agent's) gets one line saying no trace is available for that turn.
Nothing is cut: arguments and results are shown whole.
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from pydantic_ai.messages import (
    ModelRequest,
    ModelRequestPart,
    ModelResponse,
    ModelResponsePart,
    RetryFeedbackPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_core import to_jsonable_python

from ar.agent import OUTPUT_TOOL
from ar.tool_support import WriteResult
from evals.ar_projection import TableDiff, diff_text
from evals.scoreboard import TraceTurn, TrialResult, TrialTrace
from evals.trace_color import Kind, Line, render

HEADER = 2  # the trial's header line is indented this far
TRIAL = 4  # and its trace this far, under the header
BODY = 2  # a block's text sits this far in from its label
ACTION_LOG = 'action_log'
DENIAL = re.compile(r'Denied by (\S+): (.*)', re.DOTALL)  # the message of ar.errors.PolicyDenied
NO_TRACE = 'no trace available for this turn'
NO_RESULT = 'no result: the run stopped first'

type Lines = tuple[Line, ...]
type Answers = Mapping[str, ToolReturnPart]  # tool call id -> its return


def trial_lines(number: int, result: TrialResult, *, color: bool = False) -> list[str]:
    """The trial's header, then indented under it: its trace and, if it failed, the failed assertions and the diff
    against the target."""
    return render(_trial(number, result), color)


def trace_lines(trace: TrialTrace, error: str | None = None, *, color: bool = False) -> list[str]:
    """Each turn in order (the user's message, what the agent did, its reply), then the error the run stopped on,
    then what the agent wrote."""
    return render(_trace(trace, error), color)


def totals(tool_calls: int, cost_usd: float, seconds: float) -> str:
    """`3 tool calls  $0.0812  6.2s`"""
    return f'{_count(tool_calls, "tool call")}  ${cost_usd:.4f}  {seconds:.1f}s'


def _trial(number: int, result: TrialResult) -> Lines:
    verdict = 'PASS' if result.passed else 'FAIL'
    head = f'trial {number}  {verdict}  {totals(result.tool_calls, result.cost_usd, result.seconds)}'
    body = (*_trace(result.trace, result.error), *_optional('FAILED', result.failed_assertions),
            *_optional('DIFF', [diff_text(d) for d in result.diff]))
    return (Line(Kind.PLAIN, head, HEADER), *(replace(line, indent=line.indent + TRIAL) for line in body))


def _trace(trace: TrialTrace, error: str | None) -> Lines:
    turns = tuple(line for turn in trace.turns for line in _turn(turn))
    return (*turns, *_optional('ERROR', [error] if error else []), *_wrote(trace.wrote))


def _turn(turn: TraceTurn) -> Lines:
    reply = () if turn.reply is None else _block(Kind.ASSISTANT, 'ASSISTANT', [turn.reply])
    return (*_block(Kind.USER, 'USER', [turn.prompt]), *_steps(turn.history), *reply)


def _steps(history: Any) -> Lines:
    """What the agent did in the turn that ends `history`, message by message; then each call the run stopped
    before answering."""
    if not isinstance(history, list) or not all(isinstance(m, ModelRequest | ModelResponse) for m in history):
        return (Line(Kind.PLAIN, NO_TRACE),)
    own = history[_turn_start(history):]
    answers = {part.tool_call_id: part for message in own if isinstance(message, ModelRequest)
               for part in message.parts if isinstance(part, ToolReturnPart)}
    unanswered = [part for message in own if isinstance(message, ModelResponse)
                  for part in message.parts if isinstance(part, ToolCallPart) and part.tool_call_id not in answers]
    return (*(line for message in own for part in message.parts for line in _part(part, answers)),
            *(line for call in unanswered for line in _block(Kind.TOOL_RESULT, _result_label(call), [NO_RESULT])))


def _turn_start(history: Sequence[ModelRequest | ModelResponse]) -> int:
    """Where the last turn starts: the last request carrying a user prompt. A chat's history holds earlier turns."""
    return max((i for i, message in enumerate(history) if isinstance(message, ModelRequest)
                and any(isinstance(part, UserPromptPart) for part in message.parts)), default=0)


def _part(part: ModelRequestPart | ModelResponsePart, answers: Answers) -> Lines:
    """One part of a message as a block; nothing for a part the trace leaves out (the user's prompt, shown from the
    turn; empty thinking or text; instructions; the final-output call and its return when it succeeded)."""
    match part:
        case ThinkingPart() if part.has_content():
            return _block(Kind.REASONING, 'REASONING', [part.content])
        case TextPart() if part.has_content():
            return _block(Kind.ASSISTANT, 'ASSISTANT', [part.content])
        case ToolCallPart() if not _closing(answers.get(part.tool_call_id)):
            return _block(Kind.TOOL_CALL, f'TOOL CALL {part.tool_name}', [_json(part.args_as_dict())])
        case ToolReturnPart() if not _closing(part):
            return (*_block(Kind.TOOL_RESULT, _result_label(part)), *_result(part))
        case RetryFeedbackPart():
            return _block(Kind.PLAIN, 'RETRY', [_text(part.content)])
    return ()


def _closing(answer: ToolReturnPart | None) -> bool:
    """The final-output call answered as accepted: the turn's reply shows it."""
    return answer is not None and answer.tool_name == OUTPUT_TOOL and answer.outcome == 'success'


def _result_label(part: ToolCallPart | ToolReturnPart) -> str:
    return f'TOOL RESULT {part.tool_name}'


def _result(part: ToolReturnPart) -> Lines:
    """A refusal; or the whole result, after the rule and approval when the write was held for a person."""
    if part.outcome != 'success':
        return _refusal(part)
    content = part.content
    if isinstance(content, WriteResult) and content.status == 'held_for_approval':
        rule = f' {content.rule}' if content.rule else ''
        held = _body(Kind.HELD, f'HELD{rule}: approval {content.approval_id}')
        return (*held, *_body(Kind.TOOL_RESULT, _text(content)))
    return _body(Kind.TOOL_RESULT, _text(content))


def _refusal(part: ToolReturnPart) -> Lines:
    """DENIED by a policy rule, RETRY for any other refusal, or the outcome (FAILED, ...) with its text."""
    text = _text(part.content)
    if part.outcome == 'retried' and (denial := DENIAL.match(text)):
        return _body(Kind.DENIED, f'DENIED {denial[1]}: {denial[2]}')
    return _body(Kind.TOOL_RESULT, f'{"RETRY" if part.outcome == "retried" else part.outcome.upper()}: {text}')


def _wrote(wrote: Sequence[TableDiff]) -> Lines:
    """One table per line: ids added (+), changed (~, with the fields) or removed (-); the action log last, as a
    count."""
    texts = [f'{d.table} +{_count(len(d.added), "row")}' if d.table == ACTION_LOG else diff_text(d)
             for d in sorted(wrote, key=lambda d: d.table == ACTION_LOG)]
    return _block(Kind.PLAIN, 'WROTE', texts or ['nothing'])


def _optional(label: str, texts: Sequence[str]) -> Lines:
    return _block(Kind.PLAIN, label, texts) if texts else ()


def _block(kind: Kind, label: str, texts: Sequence[str] = ()) -> Lines:
    """The label, then each text in full, line by line, under it."""
    return (Line(kind, label, label=True), *(line for text in texts for line in _body(kind, text)))


def _body(kind: Kind, text: str) -> Lines:
    # Blank lines around the text are dropped (a model's thinking often ends with some); those inside are kept.
    return tuple(Line(kind, row, BODY) for row in text.strip('\n').splitlines() or [''])


def _text(value: Any) -> str:
    """A string as it is, line breaks kept; anything else as indented JSON."""
    return value if isinstance(value, str) else _json(value)


def _json(value: Any) -> str:
    return json.dumps(to_jsonable_python(value, fallback=str), indent=2, ensure_ascii=False)


def _count(n: int, noun: str) -> str:
    return f'{n} {noun}{"" if n == 1 else "s"}'
