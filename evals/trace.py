"""The --trace view of one trial: what the agent did, step by step, as plain lines for a terminal.

Pure functions from a `TrialResult` and its `TrialTrace` to lines. A turn's history is read as pydantic-ai
messages: each tool call the model made, paired by call id with its return. In pydantic-ai 2.71 a refused call
comes back as a tool return with outcome 'retried' whose text is the refusal; a policy refusal reads
"Denied by <rule>: <reason>" (`ar.errors.PolicyDenied`). A write held for a person is a normal return whose
`WriteResult` status is 'held_for_approval'. A history that is not a list of pydantic-ai messages (a scripted
agent's) gets one line saying no trace is available for that turn.
"""

import json
import re
import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import accumulate
from typing import Any

from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart, UserPromptPart

from ar.agent import OUTPUT_TOOL
from ar.tool_support import WriteResult
from evals.ar_projection import TableDiff, diff_text
from evals.scoreboard import TraceTurn, TrialResult, TrialTrace

WIDTH = 100  # text is wrapped, and result digests cut, at this many characters
LABEL = 8  # the label column: 'event   ', 'wrote   '
RESULT = '     -> '  # a call's outcome, under the call
LONG_TEXT = 32  # a string argument longer than this is shown in full on its own lines, after a short preview
PREVIEW = 16  # characters of that string shown in the call itself
VALUE_WIDTH = 60  # any other argument value is cut to this
LOAD_TOOL = 'load_capability'
ACTION_LOG = 'action_log'
DENIAL = re.compile(r'Denied by (\S+): (.*)', re.DOTALL)  # the message of ar.errors.PolicyDenied


@dataclass(frozen=True)
class _Call:
    part: ToolCallPart
    result: ToolReturnPart | None  # None if the run stopped before the call returned


def trial_lines(number: int, result: TrialResult) -> list[str]:
    """The trial's header, then indented under it: its trace and, if it failed, the failed assertions and the diff
    against the target."""
    verdict = 'PASS' if result.passed else 'FAIL'
    head = (f'  trial {number}  {verdict}  {_count(result.tool_calls, "tool call")}  ${result.cost_usd:.4f}  '
            f'{result.seconds:.1f}s')
    body = [*trace_lines(result.trace, result.error), *_labelled('failed', result.failed_assertions),
            *_labelled('diff', [diff_text(d) for d in result.diff])]
    return [head, *(f'    {line}' if line else '' for line in body)]


def trace_lines(trace: TrialTrace, error: str | None = None) -> list[str]:
    """Each turn in order (its prompt, its numbered tool calls with their outcomes, the agent's reply), then the
    error the run stopped on, then what the agent wrote."""
    calls = [_calls(turn.history) for turn in trace.turns]
    firsts = accumulate((len(found or ()) for found in calls), initial=1)  # calls are numbered across turns
    turns = [line for turn, found, first in zip(trace.turns, calls, firsts)
             for line in _turn_lines(turn, found, first, trace.chat)]
    return [*turns, *_labelled('error', [error] if error else []), *_wrote_lines(trace.wrote)]


def _turn_lines(turn: TraceTurn, calls: tuple[_Call, ...] | None, first: int, chat: bool) -> list[str]:
    asked, answered = ('clerk', 'agent') if chat else ('event', 'final')
    steps = (['no trace available for this turn'] if calls is None
             else [line for number, call in enumerate(calls, first) for line in _call_lines(number, call)])
    reply = [] if turn.reply is None else _labelled(answered, [turn.reply])
    return [*_labelled(asked, [turn.prompt]), *steps, *reply]


def _calls(history: Any) -> tuple[_Call, ...] | None:
    """The tool calls of the turn that ends `history`, in order, each with its return; None if `history` is not a
    list of pydantic-ai messages. The final-output call is left out: the reply shows it."""
    if not isinstance(history, list) or not all(isinstance(m, ModelRequest | ModelResponse) for m in history):
        return None
    own = history[_turn_start(history):]
    returns = {part.tool_call_id: part for message in own if isinstance(message, ModelRequest)
               for part in message.parts if isinstance(part, ToolReturnPart)}
    return tuple(_Call(part, returns.get(part.tool_call_id)) for message in own if isinstance(message, ModelResponse)
                 for part in message.parts if isinstance(part, ToolCallPart) and part.tool_name != OUTPUT_TOOL)


def _turn_start(history: Sequence[ModelRequest | ModelResponse]) -> int:
    """Where the last turn starts: the last request carrying a user prompt. A chat's history holds earlier turns."""
    return max((i for i, message in enumerate(history) if isinstance(message, ModelRequest)
                and any(isinstance(part, UserPromptPart) for part in message.parts)), default=0)


def _call_lines(number: int, call: _Call) -> list[str]:
    """`3  amount_due(invoice_ids=["INV-1"])`, then each long text argument in full, then the outcome."""
    name, args = call.part.tool_name, call.part.args_as_dict()
    shown = str(args.get('id')) if name == LOAD_TOOL else ', '.join(f'{k}={_inline(v)}' for k, v in args.items())
    texts = [line for key, value in args.items() if _is_long_text(value)
             for line in _block(f'     {key}: ', value)]
    outcome = _outcome(call)
    return [f'{number:<3}{name}({shown})', *texts, *([] if outcome is None else _block(RESULT, outcome))]


def _outcome(call: _Call) -> str | None:
    """DENIED by a rule, RETRY, HELD for a person, a write's status, or a one-line digest of what a read returned.
    None for a capability that loaded."""
    result = call.result
    if result is None:
        return 'no result: the run stopped first'
    if result.outcome != 'success':
        return _refusal(result)
    if call.part.tool_name == LOAD_TOOL:
        return None
    if isinstance(result.content, WriteResult):
        return _write(result.content)
    return _clip(_digest(result.content), WIDTH - len(RESULT))


def _refusal(result: ToolReturnPart) -> str:
    text = result.content if isinstance(result.content, str) else json.dumps(result.content, default=str)
    if result.outcome == 'retried' and (denial := DENIAL.match(text)):
        return f'DENIED {denial[1]}: {denial[2]}'
    return f'{"RETRY" if result.outcome == "retried" else result.outcome.upper()}: {text}'


def _write(written: WriteResult) -> str:
    if written.status == 'held_for_approval':
        return f'HELD{f" {written.rule}" if written.rule else ""}: approval {written.approval_id}'
    return f'{written.status}: {written.target_id}'


def _digest(value: Any) -> str:
    """A mapping as its fields, each with a short form of its value; anything else as that short form."""
    if isinstance(value, Mapping):
        return '; '.join(f'{key} {_brief(item)}' for key, item in value.items())
    return _brief(value)


def _brief(value: Any) -> str:
    """A list as its items, a row by its first field (its id), or 'none'; a mapping as {...}; else the value."""
    if isinstance(value, list | tuple):
        return ', '.join(str(next(iter(v.values()), '')) if isinstance(v, Mapping) else str(v) for v in value) or 'none'
    return '{...}' if isinstance(value, Mapping) else str(value)


def _wrote_lines(wrote: Sequence[TableDiff]) -> list[str]:
    """One table per line: ids added (+), changed (~, with the fields) or removed (-); the action log last, as a
    count."""
    texts = [f'{d.table} +{_count(len(d.added), "row")}' if d.table == ACTION_LOG else diff_text(d)
             for d in sorted(wrote, key=lambda d: d.table == ACTION_LOG)]
    return _labelled('wrote', texts or ['nothing'])


def _labelled(label: str, items: Sequence[str]) -> list[str]:
    """Each item in full, wrapped; the label on the first line only, everything else aligned under the text."""
    return [line for i, item in enumerate(items) for line in _block(f'{"" if i else label:<{LABEL}}', item)]


def _block(prefix: str, text: str) -> list[str]:
    """`text` in full, wrapped, its first line after `prefix` and the rest aligned under it; line breaks are kept."""
    rows = [row for line in text.splitlines() or [''] for row in textwrap.wrap(line, WIDTH - len(prefix)) or ['']]
    return [f'{" " * len(prefix) if i else prefix}{row}'.rstrip() for i, row in enumerate(rows)]


def _inline(value: Any) -> str:
    if _is_long_text(value):
        return f'"{" ".join(value.split())[:PREVIEW]}..."'  # one line: the full text follows the call
    return _clip(json.dumps(value, ensure_ascii=False, default=str), VALUE_WIDTH)


def _is_long_text(value: Any) -> bool:
    return isinstance(value, str) and len(value) > LONG_TEXT


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else f'{text[:width - 3]}...'


def _count(n: int, noun: str) -> str:
    return f'{n} {noun}{"" if n == 1 else "s"}'
