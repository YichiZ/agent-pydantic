"""Run the agent on events from agents/ar/db/events and print what it did. Events are not scored: there is no PASS or FAIL.

    uv run python -m agents ar run event_06 event_02      # these events, in that order; --all for every one
    uv run python -m agents ar run --list                 # ids, types, accounts; runs nothing
    uv run python -m agents ar run --customer cus_garnet --event "Event: aging_check. Account: Garnet Tooling (cus_garnet)."
    uv run python -m agents ar run event_20 --interactive            # you type the customer's lines
    uv run python -m agents ar run --customer cus_corvid --chat --interactive
    uv run python -m agents ar run event_06 --thinking    # the model reasons first; the trace shows it as REASONING
    uv run python -m agents ar run event_06 --color never  # colour is on for a terminal (auto); always | never

Each event runs on a fresh copy of agents/ar/db/db.json after its setup; nothing is written to disk. Exits 2 on bad
arguments, a malformed event file or a refused setup, else 0: an agent that crashes on one event is reported and the
next runs.
"""

import argparse
import asyncio
import json
import os
import sys
import textwrap
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Literal, Self

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from agents.ar.agent import run_turn  # the model is resolved on the first run, so importing needs no API key
from agents.ar.data_model import ArDb
from agents.ar.errors import TOOL_ERRORS
from agents.ar.evals.clerk import haiku_clerk
from agents.ar.evals.runner import STOP, ClerkFn, Customer, Transcript, run_agent, setup_store
from agents.ar.evals.tasks import DB_DIR, DB_PATH, InitialState, Step, UserScenario
from agents.ar.evals.trace import totals, trace_lines
from agents.ar.evals.trace_color import COLOR_MODES, use_color
from agents.ar.run_types import AgentFn
from agents.ar.store import Store

EVENTS_DIR = DB_DIR / 'events'
CHAT = 'customer_message'
AD_HOC = 'ad hoc'
ENDS = ('', 'quit')  # typed in an interactive chat, either ends it
WIDTH = 100  # the intro's text is wrapped at this many characters
LABEL = 8  # the intro's label column: 'context ', 'setup   '
LONG_TEXT = 32  # in a setup step, a string argument longer than this is shown as a short preview
PREVIEW = 16  # characters of that string shown
VALUE_WIDTH = 60  # any other argument value of a setup step is cut to this

type Read = Callable[[str], str]  # `input`, or a stand-in in tests


class EventFileError(ValueError):
    """An event file is not what this command expects, or its setup is refused."""


class Event(BaseModel):
    """One file in agents/ar/db/events."""

    model_config = ConfigDict(frozen=True, extra='forbid')

    id: str
    flow: str
    type: Literal['aging_check', 'approval_decided', 'customer_message']
    customer_id: str
    ticket: str | None
    user_scenario: UserScenario | None
    initial_state: InitialState | None
    situation: str
    open_question: str
    rules_settle_it: bool

    @model_validator(mode='after')
    def _ticket_or_scenario(self) -> Self:
        if (self.ticket is None) == (self.user_scenario is None):
            raise ValueError('must have exactly one of ticket and user_scenario')
        return self

    @property
    def setup(self) -> tuple[Step, ...]:
        return self.initial_state.initialization_actions if self.initial_state else ()


@dataclass(frozen=True)
class Job:
    """One run of the agent: what to print before it starts, its store, and what it is given."""

    name: str  # an event id, or AD_HOC
    intro: tuple[str, ...]
    store: Store
    customer_id: str
    ticket: str | None = None
    customer: Customer | None = None


def main(argv: Sequence[str] | None = None, *, agent_fn: AgentFn = run_turn, clerk: ClerkFn = haiku_clerk,
         read: Read = input) -> int:
    load_dotenv()  # ANTHROPIC_API_KEY from .env, found by walking up from this file; real env vars win
    db = ArDb.load(DB_PATH)
    try:
        events = load_events(EVENTS_DIR, db.customers)
        args = parse_args(argv, events, db.customers)
        jobs = [] if args.list else plan(args, events, db, clerk, read)
    except EventFileError as error:
        print(f'error: {error}', file=sys.stderr)
        return 2
    if args.list:
        print('\n'.join(list_lines(events.values(), db)))
        return 0
    color = use_color(args.color, isatty=sys.stdout.isatty(), environ=os.environ)
    asyncio.run(run_all(jobs, agent_fn, thinking=args.thinking, color=color))
    return 0


def load_events(directory: Path, customers: Collection[str]) -> dict[str, Event]:
    """Every event_*.json in `directory`, by id, in file order. Raises `EventFileError` naming the first bad file."""
    return {event.id: event for event in (_load(path, customers) for path in sorted(directory.glob('event_*.json')))}


def _load(path: Path, customers: Collection[str]) -> Event:
    try:
        event = Event.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as error:
        raise EventFileError(f'{path} is malformed: {error}') from error
    if event.customer_id not in customers:
        raise EventFileError(f'{path}: unknown customer {event.customer_id}')
    return event


def parse_args(argv: Sequence[str] | None, events: Mapping[str, Event], customers: Collection[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog='python -m agents ar run', description=__doc__.splitlines()[0])
    parser.add_argument('ids', nargs='*', metavar='EVENT', help='event ids, such as event_06')
    parser.add_argument('--all', action='store_true', help='every event, in order')
    parser.add_argument('--list', action='store_true', help='list the events and run nothing')
    parser.add_argument('--customer', metavar='ID', help='an ad hoc event on this account')
    parser.add_argument('--event', metavar='TEXT', help='with --customer: the event text, or the first line of a chat')
    parser.add_argument('--chat', action='store_true', help='with --customer: a conversation; needs --interactive')
    parser.add_argument('--interactive', action='store_true', help="type the customer's lines yourself")
    parser.add_argument('--thinking', action='store_true',
                        help='the model reasons before it answers; the trace shows it as REASONING')
    parser.add_argument('--color', choices=COLOR_MODES, default='auto',
                        help='colour the trace: auto (on a terminal unless NO_COLOR is set), always or never')
    args = parser.parse_args(argv)
    if problem := _problem(args, events, customers):
        parser.error(problem)
    return args


def _problem(args: argparse.Namespace, events: Mapping[str, Event], customers: Collection[str]) -> str | None:
    """The first thing wrong with the arguments, or None."""
    modes = sum([bool(args.ids), args.all, args.list, args.customer is not None])
    unknown = [i for i in args.ids if i not in events]
    chosen = list(events.values()) if args.all else [events[i] for i in args.ids if i in events]
    typed_wrong = next((e for e in chosen if e.type != CHAT), None)
    checks = (
        ((args.event is not None or args.chat) and args.customer is None, '--event and --chat go with --customer'),
        (modes == 0, 'name events, or use --all, --list or --customer'),
        (modes > 1, 'use only one of: event ids, --all, --list, --customer'),
        (bool(unknown), f'unknown event {", ".join(unknown)}; --list shows them'),
        (args.customer is not None and args.customer not in customers, f'unknown customer {args.customer}'),
        (args.customer is not None and args.event is None and not args.chat, '--customer needs --event, or --chat'),
        (args.chat and not args.interactive, '--chat needs --interactive: an ad hoc chat has no simulated customer'),
        (args.interactive and not args.chat and (not chosen or typed_wrong is not None),
         '--interactive needs customer_message events, or --customer with --chat'
         + (f'; {typed_wrong.id} is {typed_wrong.type}' if typed_wrong else '')),
    )
    return next((message for failed, message in checks if failed), None)


def plan(args: argparse.Namespace, events: Mapping[str, Event], db: ArDb, clerk: ClerkFn, read: Read) -> list[Job]:
    """A job per event asked for, each on its own store with its setup replayed, before any agent runs."""
    if args.customer is not None:
        return [Job(AD_HOC, (f'{AD_HOC}  {account(db, args.customer)}',), setup_store(args.customer, ()), args.customer,
                    ticket=None if args.chat else args.event, customer=typed(read, args.event) if args.chat else None)]
    chosen = events.values() if args.all else [events[i] for i in args.ids]
    return [event_job(event, db, None if event.user_scenario is None
                      else typed(read) if args.interactive else partial(clerk, event.user_scenario))
            for event in chosen]


def event_job(event: Event, db: ArDb, customer: Customer | None) -> Job:
    """The event on a fresh store with its setup replayed; the intro is its header, notes and setup steps."""
    try:
        store = setup_store(event.customer_id, event.setup)
    except TOOL_ERRORS as error:
        raise EventFileError(f'{event.id}: its setup is refused: {error}') from error
    intro = (f'{event.id}  {event.type}  {account(db, event.customer_id)}',
             *labelled('context', [event.situation]), *labelled('open q', [event.open_question]),
             *labelled('rules', [verdict(event)]),
             *(f'{"" if i else "setup":<{LABEL}}{call_text(step.func_name, step.arguments)}'
               for i, step in enumerate(event.setup)))  # one line each, not wrapped
    return Job(event.id, intro, store, event.customer_id, ticket=event.ticket, customer=customer)


def typed(read: Read, first: str | None = None) -> Customer:
    """The customer's lines, typed: `first` if given, then each line read after the agent's last reply is shown. An
    empty line, `quit` or the end of input ends the conversation."""

    async def say(transcript: Transcript) -> str:
        if not transcript and first:
            print(f'you> {first}', flush=True)
            return first
        if transcript:
            print(f'agent> {transcript[-1][1]}', flush=True)
        try:
            line = read('you> ').strip()
        except EOFError:
            return STOP
        return STOP if line in ENDS else line

    return say


async def run_all(jobs: Sequence[Job], agent_fn: AgentFn, *, thinking: bool = False, color: bool = False) -> None:
    """Each job in turn: its intro before the agent starts, then the trace (coloured with `color`) and a footer.
    `thinking` goes to every turn. A crash ends only its job."""
    for number, job in enumerate(jobs):
        print('\n'.join([*([''] if number else []), *job.intro]), flush=True)
        ran = await run_agent(job.store, job.customer_id, agent_fn, ticket=job.ticket, customer=job.customer,
                              thinking=thinking)
        print('\n'.join([*trace_lines(ran.trace, ran.error, color=color),
                         f'{job.name}  {totals(ran.tool_calls, ran.cost_usd, ran.seconds)}']), flush=True)


def labelled(label: str, items: Sequence[str]) -> list[str]:
    """Each item in full, wrapped; the label on the first line only, everything else aligned under the text."""
    return [line for i, item in enumerate(items) for line in _wrapped(f'{"" if i else label:<{LABEL}}', item)]


def _wrapped(prefix: str, text: str) -> list[str]:
    rows = [row for line in text.splitlines() or [''] for row in textwrap.wrap(line, WIDTH - len(prefix)) or ['']]
    return [f'{" " * len(prefix) if i else prefix}{row}' for i, row in enumerate(rows)]


def call_text(name: str, args: Mapping[str, Any]) -> str:
    """A setup step on one line, `decide_approval(approval_id="apr_8001")`: a long text as a short preview, any
    other long value cut. Only the intro is shortened; the trace shows every call in full."""
    return f'{name}({", ".join(f"{key}={_inline(value)}" for key, value in args.items())})'


def _inline(value: Any) -> str:
    if isinstance(value, str) and len(value) > LONG_TEXT:
        return f'"{" ".join(value.split())[:PREVIEW]}..."'
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= VALUE_WIDTH else f'{text[:VALUE_WIDTH - 3]}...'


def list_lines(events: Iterable[Event], db: ArDb) -> list[str]:
    rows = [(e.id, e.type, account(db, e.customer_id), f'rules {verdict(e)}') for e in events]
    width = max((len(row[2]) for row in rows), default=0)
    return [f'{event_id}  {kind:<16}  {name:<{width}}  {rules}' for event_id, kind, name, rules in rows]


def account(db: ArDb, customer_id: str) -> str:
    return f'{db.customer(customer_id).name} ({customer_id})'


def verdict(event: Event) -> str:
    return 'settle it' if event.rules_settle_it else 'leave it open'


if __name__ == '__main__':
    sys.exit(main())
