"""The command line, with the agent, clerk and judge patched to scripted stand-ins."""
from types import SimpleNamespace

import pytest

from agents.collections.evals import run as ar_evals
from agents.collections.evals import runner as ar_runner
from agents.collections.evals.run import BASELINE_PATH, THINKING_BASELINE_PATH
from agents.collections.evals.tasks import TaskFileError
from agents.collections.evals.trace_color import CYAN, RESET
from agents.collections.tests.scripted_agents import noop_agent, one_line_clerk, raising_agent

# What the command printed before --trace existed, for these tasks with a stopped clock; it must not change.
UNTRACED = '''\
task_02  0/2  failed: assert_promise_count(invoice_id=INV-1101, expected=1)  db: promises -prm_8502
task_13  2/2
task_15  0/2  failed: assert_application_count(payment_id=pay_2005, expected=1); \
assert_balance(invoice_id=INV-2001, expected=5000.00); assert_unapplied_cash(payment_id=pay_2005, expected=0.00)  \
db: applications -pay_2005:INV-2001; payments ~pay_2005 (status)

3 tasks, 6 trials; columns are pass^1 and pass^2
overall                            0.3333  0.3333  (3 tasks)
flow  cash_application             0.0000  0.0000  (1 tasks)
flow  collections                  0.5000  0.5000  (2 tasks)
disposition  act                   0.0000  0.0000  (2 tasks)
disposition  do_nothing            1.0000  1.0000  (1 tasks)
never-events                       0.0000  0.0000  (1 tasks)  (pass^k must be 1.0)
human in the loop                  recall n/a on 0 trials (must be 1.0); precision n/a on 0
retrieval (search)                 pass^1 n/a on tasks with required documents
tone                               not judged
efficiency                         $0.000000, 0.000 s, 0.000 tool calls per trial

No baseline yet; run with --save to create baseline.json.
FAIL: a never-event task failed at least one trial
'''


@pytest.fixture(autouse=True)
def scripted(monkeypatch, tmp_path):
    monkeypatch.setattr(ar_evals, 'run_turn', noop_agent)
    monkeypatch.setattr(ar_evals, 'haiku_clerk', one_line_clerk)
    monkeypatch.setattr(ar_evals, 'BASELINE_PATH', tmp_path / 'baseline.json')
    monkeypatch.setattr(ar_evals, 'THINKING_BASELINE_PATH', tmp_path / 'baseline_thinking.json')
    monkeypatch.setattr(ar_evals, 'load_dotenv', lambda: None)  # tests never read a real .env


@pytest.mark.parametrize(('argv', 'message'), [
    (['--trials', '0'], '--trials'),
    (['--trials', 'two'], '--trials'),
    (['--concurrency', '0'], '--concurrency'),
    (['--task', 'task_99'], 'task_99'),
    (['--split', 'nope'], '--split'),
    (['--retrieval', 'bogus'], '--retrieval'),
    (['--split', 'base', '--task', 'task_01'], 'not allowed'),
])
def test_bad_arguments_fail_with_a_clear_error(argv, message, capsys):
    with pytest.raises(SystemExit) as exit_info:
        ar_evals.main(argv)
    assert exit_info.value.code == 2
    assert message in capsys.readouterr().err


def test_without_trace_the_output_is_exactly_what_it_was(monkeypatch, capsys):
    monkeypatch.setattr(ar_runner, 'time', SimpleNamespace(perf_counter=lambda: 0.0))
    assert ar_evals.main(['--task', 'task_13', 'task_15', 'task_02', '--trials', '2']) == 1
    assert capsys.readouterr().out == UNTRACED


def test_colour_without_trace_changes_nothing(monkeypatch, capsys):
    monkeypatch.setattr(ar_runner, 'time', SimpleNamespace(perf_counter=lambda: 0.0))
    assert ar_evals.main(['--task', 'task_13', 'task_15', 'task_02', '--trials', '2', '--color', 'always']) == 1
    assert capsys.readouterr().out == UNTRACED


def test_trace_prints_every_trial_under_its_task_line(capsys):
    assert ar_evals.main(['--task', 'task_13', 'task_17', '--trials', '2', '--trace']) == 0
    lines = capsys.readouterr().out.splitlines()
    tasks = [i for i, line in enumerate(lines) if line.startswith('task_')]
    assert [lines[i] for i in tasks] == ['task_13  2/2', 'task_17  2/2']
    trials = [i for i, line in enumerate(lines) if line.startswith('  trial ')]
    assert [lines[i][:15] for i in trials] == ['  trial 1  PASS', '  trial 2  PASS'] * 2
    grid = lines.index('2 tasks, 4 trials; columns are pass^1 and pass^2')
    assert tasks[0] < trials[0] < trials[1] < tasks[1] < trials[2] < trials[3] < grid
    assert lines[trials[0] + 1:trials[0] + 8] == [
        '    USER', '      Event: aging_check. Account: Kestrel Bakery Supply (cus_kestrel).',
        '    no trace available for this turn', '    ASSISTANT', '      Nothing to do.', '    WROTE', '      nothing']


def test_trace_keeps_a_failed_trials_assertions_and_diff_with_it(capsys):
    assert ar_evals.main(['--task', 'task_15', '--trace']) == 1
    out = capsys.readouterr().out
    trial = out[out.index('  trial 1  FAIL'):out.index('\n\n')]
    assert '    FAILED\n      assert_balance(invoice_id=INV-2001, expected=5000.00)\n' in trial
    assert '      assert_application_count(payment_id=pay_2005, expected=1)\n' in trial
    assert '    DIFF\n      applications -pay_2005:INV-2001\n      payments ~pay_2005 (status)' in trial
    assert out.startswith('task_15  0/1  failed: ')  # the task line is unchanged


def test_trace_shows_a_crash(monkeypatch, capsys):
    monkeypatch.setattr(ar_evals, 'run_turn', raising_agent)
    assert ar_evals.main(['--task', 'task_13', '--trace']) == 0
    assert '    ERROR\n      RuntimeError: model unavailable\n' in capsys.readouterr().out


@pytest.mark.parametrize(('argv', 'no_color', 'coloured'), [
    (['--color', 'always'], '1', True),
    (['--color', 'never'], None, False),
    (['--color', 'auto'], None, False),  # captured output is not a terminal
    ([], '1', False),
])
def test_trace_is_coloured_only_when_asked_or_on_a_terminal(monkeypatch, capsys, argv, no_color, coloured):
    if no_color is not None:
        monkeypatch.setenv('NO_COLOR', no_color)
    assert ar_evals.main(['--task', 'task_13', '--trace', *argv]) == 0
    out = capsys.readouterr().out
    assert ('\x1b[' in out) is coloured
    assert (f'    {CYAN}USER{RESET}' in out.splitlines()) is coloured


def test_thinking_reaches_the_agent_and_has_its_own_baseline(monkeypatch, capsys):
    seen = []

    async def agent(store, customer_id, prompt, **options):
        seen.append(options['thinking'])
        return await noop_agent(store, customer_id, prompt, **options)

    monkeypatch.setattr(ar_evals, 'run_turn', agent)
    assert THINKING_BASELINE_PATH == BASELINE_PATH.with_name('baseline_thinking.json')  # the real paths
    assert ar_evals.main(['--task', 'task_13', '--thinking']) == 0
    assert 'No baseline yet; run with --save to create baseline_thinking.json.' in capsys.readouterr().out
    assert ar_evals.main(['--task', 'task_13', '--thinking', '--save']) == 0
    assert f'Saved baseline to {ar_evals.THINKING_BASELINE_PATH}.' in capsys.readouterr().out
    assert ar_evals.THINKING_BASELINE_PATH.is_file() and not ar_evals.BASELINE_PATH.exists()
    assert ar_evals.main(['--task', 'task_13', '--thinking']) == 0
    assert 'overall.pass_1' in capsys.readouterr().out
    assert ar_evals.main(['--task', 'task_13']) == 0
    assert 'No baseline yet; run with --save to create baseline.json.' in capsys.readouterr().out
    assert seen == [True, True, True, False]


def test_missed_human_in_the_loop_exits_one(capsys):
    assert ar_evals.main(['--task', 'task_18']) == 1  # needs a person; not a never-event
    assert 'recall' in capsys.readouterr().out


def test_a_split_runs_its_tasks(capsys):
    ar_evals.main(['--split', 'cross_flow'])
    out = capsys.readouterr().out
    assert [line.split()[0] for line in out.splitlines() if line.startswith('task_')] == [
        'task_06', 'task_11', 'task_12']


def test_save_then_compare_with_the_baseline(capsys):
    assert ar_evals.main(['--task', 'task_13', '--save']) == 0
    assert ar_evals.BASELINE_PATH.is_file()
    assert 'Saved baseline' in capsys.readouterr().out
    ar_evals.main(['--task', 'task_13'])
    assert 'overall.pass_1' in capsys.readouterr().out


def test_a_crashed_agent_is_reported_on_its_task_line(monkeypatch, capsys):
    monkeypatch.setattr(ar_evals, 'run_turn', raising_agent)
    assert ar_evals.main(['--task', 'task_13']) == 0  # failed, but neither a never-event nor a human task
    out = capsys.readouterr().out
    assert 'task_13  0/1' in out and 'RuntimeError: model unavailable' in out


def test_judge_runs_only_when_asked(monkeypatch, capsys):
    calls = []

    async def judge(text, facts):
        calls.append(text)
        return 0.5

    async def sender(store, customer_id, prompt, **options):
        from agents.collections.environment import call_tool
        from agents.collections.run_types import AgentTurn
        call_tool(store, customer_id, 'send_message', {
            'contact_id': 'con_801', 'channel': 'email', 'invoice_ids': ['INV-1001'],
            'body': 'INV-1001 for $12,400.00 was due on November 6, 2026.'})
        return AgentTurn(text='Sent.', cost_usd=0.0, tool_calls=1, history=None)

    monkeypatch.setattr(ar_evals, 'run_turn', sender)
    monkeypatch.setattr(ar_evals, 'sonnet_judge', judge)
    assert ar_evals.main(['--task', 'task_01']) == 0
    assert calls == [] and 'not judged' in capsys.readouterr().out
    assert ar_evals.main(['--task', 'task_01', '--judge']) == 0
    assert len(calls) == 1 and '0.5000 mean over 1' in capsys.readouterr().out


def test_an_unreadable_baseline_is_reported_not_raised(capsys):
    ar_evals.BASELINE_PATH.write_text('{"k": "four"}')
    assert ar_evals.main(['--task', 'task_13']) == 0
    assert 'is not a saved grid' in capsys.readouterr().out


def test_a_malformed_task_file_stops_before_any_run(monkeypatch, capsys):
    def broken():
        raise TaskFileError('agents/collections/db/tasks.json is malformed: annotations missing')

    monkeypatch.setattr(ar_evals, 'load_tasks', broken)
    assert ar_evals.main([]) == 2
    assert 'annotations missing' in capsys.readouterr().err


def test_the_command_loads_dotenv_before_it_runs(monkeypatch):
    calls = []
    monkeypatch.setattr(ar_evals, 'load_dotenv', lambda: calls.append('loaded'))
    assert ar_evals.main(['--task', 'task_13']) == 0
    assert calls == ['loaded']
