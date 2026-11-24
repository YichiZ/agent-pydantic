"""The run_event command, offline: scripted agents and clerks, no model, no network, no real stdin."""
import json
import re
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from scripted_agents import escalate_agent, noop_agent

from ar.run_types import AgentTurn
from evals import run_event
from evals.ar_runner import DEFAULT_MAX_TURNS, STOP
from evals.ar_tasks import DB_PATH

EVENT_IDS = [f'event_{n:02}' for n in range(1, 21)]
GARNET = 'Event: aging_check. Account: Garnet Tooling (cus_garnet).'


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    monkeypatch.setattr(run_event, 'load_dotenv', lambda: None)  # tests never read a real .env


class Recorder:
    """An agent that records the account, prompt and policy of each turn, and writes nothing."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def __call__(self, store, customer_id, prompt, **options: Any) -> AgentTurn:
        self.calls.append((customer_id, prompt, options['policy']))
        return AgentTurn(text=f'reply {len(self.calls)}', cost_usd=0.25, tool_calls=1, history=None)

    @property
    def prompts(self) -> list[str]:
        return [prompt for _, prompt, _ in self.calls]


async def no_clerk(scenario, transcript) -> str:
    raise AssertionError('the simulated clerk must not be used')


def typed(*lines: str) -> Callable[[str], str]:
    """An input function that answers with `lines`, one per call, and records the prompts it was given."""
    answers: Iterator[str] = iter(lines)

    def read(prompt: str) -> str:
        read.prompts.append(prompt)
        return next(answers)

    read.prompts = []
    return read


def run(argv: list[str], capsys, **injected: Any) -> tuple[int, list[str]]:
    code = run_event.main(argv, **injected)
    return code, capsys.readouterr().out.splitlines()


def in_order(lines: list[str], wanted: list[str]) -> bool:
    """Each wanted line is in `lines`, after the one before it."""
    rest = iter(lines)
    return all(line in rest for line in wanted)


def footer(event_id: str, calls: str, cost: str) -> re.Pattern[str]:
    return re.compile(rf'{event_id}  {calls}  \${cost}  \d+\.\ds')


def test_list_prints_every_event_and_runs_no_agent(capsys):
    agent = Recorder()
    code, lines = run(['--list'], capsys, agent_fn=agent)
    assert code == 0 and agent.calls == []
    rows = {line.split()[0]: line for line in lines}
    assert list(rows) == EVENT_IDS
    assert re.fullmatch(r'event_06  aging_check +Ridgeway Clinics \(cus_ridgeway\) +rules settle it', rows['event_06'])
    assert rows['event_01'].endswith('rules leave it open') and 'customer_message' in rows['event_20']


def test_an_event_prints_header_notes_setup_trace_and_footer_in_that_order(capsys):
    code, lines = run(['event_11'], capsys, agent_fn=escalate_agent)
    assert code == 0
    starts = ['event_11  aging_check  Juniper Packaging (cus_juniper)', 'context The quality dispute on INV-1702',
              'open q  One message covering both invoices', 'rules   settle it', 'setup   reject_dispute(',
              'event   Event: aging_check. Account: Juniper Packaging (cus_juniper).',
              'no trace available for this turn', 'final   Escalated.', 'wrote   action_log +1 row']
    found = [next(i for i, line in enumerate(lines) if line.startswith(start)) for start in starts]
    assert found == sorted(found) and found[0] == 0
    assert footer('event_11', '1 tool call', '0.0200').fullmatch(lines[-1])
    out = '\n'.join(lines)
    assert 'PASS' not in out and 'FAIL' not in out


def test_the_situation_and_question_are_shown_in_full_wrapped(capsys):
    event = json.loads((run_event.EVENTS_DIR / 'event_13.json').read_text())
    _, lines = run(['event_13'], capsys, agent_fn=noop_agent)
    start, end = lines.index(next(line for line in lines if line.startswith('open q  '))), lines.index('rules   leave it open')
    question = lines[start:end]
    assert len(question) > 1 and all(len(line) <= 100 for line in question)
    assert ' '.join(line[8:] for line in question) == event['open_question']


def test_the_setup_is_replayed_before_the_agent_runs_and_wrote_shows_only_the_agent(capsys):
    seen = []

    async def agent(store, customer_id, prompt, **options):
        seen.append(store.db.dispute('dsp_3004').status)
        return await escalate_agent(store, customer_id, prompt, **options)

    before = DB_PATH.read_bytes()
    _, lines = run(['event_11'], capsys, agent_fn=agent)
    assert seen == ['resolved_invalid']  # the setup's rejection was on the store the agent saw
    wrote = lines.index('wrote   action_log +1 row')
    assert lines[wrote + 1].startswith('event_11  ')  # no disputes or invoices: those were the setup's
    assert DB_PATH.read_bytes() == before  # nothing written to disk


def test_each_setup_step_is_one_line(capsys):
    _, lines = run(['event_16'], capsys, agent_fn=noop_agent)
    setup = lines.index(next(line for line in lines if line.startswith('setup   ')))
    assert lines[setup].startswith('setup   send_message(contact_id="con_819", channel="email", ')
    assert lines[setup + 1] == ('        decide_approval(approval_id="apr_8001", decision="approved", '
                                'decided_by="ar_lead", note="Fine to send.")')
    assert lines[setup + 2].startswith('event   Event: approval_decided.')


def test_a_chat_event_shows_the_turns_in_order_and_stops_when_the_clerk_says_stop(capsys):
    said = ['We paid INV-1001 last week by ACH.', 'The reference is 4471.']
    scenarios = []

    async def clerk(scenario, transcript):
        scenarios.append(scenario.persona)
        return said[len(transcript) // 2] if len(transcript) < 4 else f'Thanks. {STOP}'

    agent = Recorder()
    _, lines = run(['event_18'], capsys, agent_fn=agent, clerk=clerk)
    assert agent.calls == [('cus_brightwell', said[0], 'chat'), ('cus_brightwell', said[1], 'chat')]
    assert len(scenarios) == 3 and scenarios[0].startswith('Priya Raman')
    assert in_order(lines, ['event_18  customer_message  Brightwell Fabrication (cus_brightwell)', f'clerk   {said[0]}',
                            'agent   reply 1', f'clerk   {said[1]}', 'agent   reply 2', 'wrote   nothing'])
    assert footer('event_18', '2 tool calls', '0.5000').fullmatch(lines[-1])


def test_a_chat_event_stops_at_the_turn_limit(capsys):
    async def chatty(scenario, transcript):
        return 'And another thing.'

    agent = Recorder()
    run(['event_19'], capsys, agent_fn=agent, clerk=chatty)
    assert len(agent.calls) == DEFAULT_MAX_TURNS


def test_interactive_feeds_typed_lines_to_the_agent_and_ends_on_an_empty_line(capsys):
    read, agent = typed('What do we owe?', 'Thank you.', '', 'never read'), Recorder()
    code, lines = run(['event_20', '--interactive'], capsys, agent_fn=agent, clerk=no_clerk, read=read)
    assert code == 0 and agent.prompts == ['What do we owe?', 'Thank you.']
    assert read.prompts == ['you> '] * 3
    assert in_order(lines, ['agent> reply 1', 'agent> reply 2', 'clerk   What do we owe?', 'agent   reply 1',
                            'clerk   Thank you.', 'agent   reply 2', 'wrote   nothing'])


@pytest.mark.parametrize('end', ['quit', '  quit  ', EOFError])
def test_interactive_also_ends_on_quit_or_the_end_of_input(end, capsys):
    def read(prompt):
        if end is EOFError:
            raise EOFError
        return end

    agent = Recorder()
    assert run(['event_20', '--interactive'], capsys, agent_fn=agent, clerk=no_clerk, read=read)[0] == 0
    assert agent.calls == []


def test_an_ad_hoc_event_runs_on_any_account(capsys):
    agent = Recorder()
    code, lines = run(['--customer', 'cus_garnet', '--event', GARNET], capsys, agent_fn=agent)
    assert code == 0 and agent.calls == [('cus_garnet', GARNET, 'solo')]
    assert lines[:2] == ['ad hoc  Garnet Tooling (cus_garnet)', f'event   {GARNET}']
    assert footer('ad hoc', '1 tool call', '0.2500').fullmatch(lines[-1])


def test_an_ad_hoc_chat_opens_with_the_event_text_then_reads_typed_lines(capsys):
    read, agent = typed('Is any of it overdue?', 'quit'), Recorder()
    argv = ['--customer', 'cus_corvid', '--chat', '--interactive', '--event', 'What do we owe you?']
    _, lines = run(argv, capsys, agent_fn=agent, clerk=no_clerk, read=read)
    assert agent.calls == [('cus_corvid', 'What do we owe you?', 'chat'), ('cus_corvid', 'Is any of it overdue?', 'chat')]
    assert lines[:2] == ['ad hoc  Corvid Logistics (cus_corvid)', 'you> What do we owe you?']


def test_an_ad_hoc_chat_without_event_text_reads_the_first_line_too(capsys):
    read, agent = typed('Hello.', ''), Recorder()
    run(['--customer', 'cus_corvid', '--chat', '--interactive'], capsys, agent_fn=agent, clerk=no_clerk, read=read)
    assert agent.prompts == ['Hello.']


@pytest.mark.parametrize(('argv', 'message'), [
    ([], 'name events, or use --all, --list or --customer'),
    (['event_99'], 'unknown event event_99'),
    (['--all', 'event_01'], 'use only one of: event ids, --all, --list, --customer'),
    (['--list', '--customer', 'cus_garnet'], 'use only one of'),
    (['--customer', 'cus_nobody', '--event', 'Hello.'], 'unknown customer cus_nobody'),
    (['--customer', 'cus_garnet'], '--customer needs --event, or --chat'),
    (['event_06', '--event', 'Hello.'], '--event and --chat go with --customer'),
    (['--chat', '--interactive'], '--event and --chat go with --customer'),
    (['--customer', 'cus_corvid', '--chat'], '--chat needs --interactive'),
    (['event_06', '--interactive'], '--interactive needs customer_message events, or --customer with --chat; '
                                    'event_06 is aging_check'),
    (['event_20', 'event_14', '--interactive'], 'event_14 is aging_check'),
    (['--all', '--interactive'], 'event_01 is aging_check'),
    (['--customer', 'cus_garnet', '--event', 'Hello.', '--interactive'], '--interactive needs customer_message'),
])
def test_bad_arguments_exit_two_with_a_clear_message_and_run_nothing(argv, message, capsys):
    agent = Recorder()
    with pytest.raises(SystemExit) as exit_info:
        run_event.main(argv, agent_fn=agent)
    assert exit_info.value.code == 2 and agent.calls == []
    assert message in capsys.readouterr().err


def test_a_crash_is_shown_with_the_trace_and_the_next_event_still_runs(capsys):
    async def agent(store, customer_id, prompt, **options):
        if customer_id == 'cus_delmar':
            raise RuntimeError('model unavailable')
        return await noop_agent(store, customer_id, prompt, **options)

    code, lines = run(['event_05', 'event_06'], capsys, agent_fn=agent)
    assert code == 0
    assert in_order(lines, ['event   Event: aging_check. Account: Delmar Foods (cus_delmar).',
                            'error   RuntimeError: model unavailable', 'wrote   nothing'])
    crashed = next(i for i, line in enumerate(lines) if footer('event_05', '0 tool calls', '0.0000').fullmatch(line))
    assert lines[crashed + 1:crashed + 3] == ['', 'event_06  aging_check  Ridgeway Clinics (cus_ridgeway)']
    assert 'final   Nothing to do.' in lines[crashed:]


def test_all_runs_every_event_in_order(capsys):
    agent = Recorder()
    code, lines = run(['--all'], capsys, agent_fn=agent, clerk=lambda scenario, transcript: _stop())
    assert code == 0
    assert [line.split()[0] for line in lines if re.match(r'event_\d\d  [a-z_]+  ', line)] == EVENT_IDS
    assert len(agent.calls) == 17  # three chat events whose clerk stops at once


async def _stop() -> str:
    return STOP


def write_event(directory, event_id: str, **changes: Any) -> None:
    event = json.loads((run_event.EVENTS_DIR / f'{event_id}.json').read_text())
    (directory / f'{event_id}.json').write_text(json.dumps({**event, **changes}))


@pytest.mark.parametrize(('changes', 'message'), [
    ({'type': 'payment_received'}, 'type'),
    ({'user_scenario': {'persona': 'P', 'instructions': 'I'}}, 'exactly one of ticket and user_scenario'),
    ({'ticket': None}, 'exactly one of ticket and user_scenario'),
    ({'id': None}, 'id'),
    ({'customer_id': 'cus_nobody'}, 'unknown customer cus_nobody'),
])
def test_a_malformed_event_file_stops_the_command_naming_the_file(changes, message, monkeypatch, tmp_path, capsys):
    write_event(tmp_path, 'event_06', **changes)
    monkeypatch.setattr(run_event, 'EVENTS_DIR', tmp_path)
    assert run_event.main(['--list'], agent_fn=Recorder()) == 2
    err = capsys.readouterr().err
    assert str(tmp_path / 'event_06.json') in err and message in err


def test_a_file_that_is_not_json_is_malformed(monkeypatch, tmp_path, capsys):
    (tmp_path / 'event_01.json').write_text('{')
    monkeypatch.setattr(run_event, 'EVENTS_DIR', tmp_path)
    assert run_event.main(['--list']) == 2
    assert 'event_01.json is malformed' in capsys.readouterr().err


def test_a_setup_that_is_refused_stops_the_command_before_any_run(monkeypatch, tmp_path, capsys):
    write_event(tmp_path, 'event_06')
    write_event(tmp_path, 'event_11', initial_state={'initialization_actions': [
        {'env_type': 'assistant', 'func_name': 'reject_dispute', 'arguments': {'dispute_id': 'dsp_9999', 'reason': 'x'}}]})
    monkeypatch.setattr(run_event, 'EVENTS_DIR', tmp_path)
    agent = Recorder()
    assert run_event.main(['event_06', 'event_11'], agent_fn=agent) == 2
    assert agent.calls == []
    assert 'event_11: its setup is refused: ' in capsys.readouterr().err


def test_the_command_loads_dotenv_before_it_runs(monkeypatch):
    calls = []
    monkeypatch.setattr(run_event, 'load_dotenv', lambda: calls.append('loaded'))
    assert run_event.main(['--list']) == 0
    assert calls == ['loaded']
