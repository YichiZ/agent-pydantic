"""The command line, with the agent, clerk and judge patched to scripted stand-ins."""
import pytest
from scripted_agents import noop_agent, one_line_clerk, raising_agent

from evals import ar_evals
from evals.ar_tasks import TaskFileError


@pytest.fixture(autouse=True)
def scripted(monkeypatch, tmp_path):
    monkeypatch.setattr(ar_evals, 'load_agent', lambda: noop_agent)
    monkeypatch.setattr(ar_evals, 'haiku_clerk', one_line_clerk)
    monkeypatch.setattr(ar_evals, 'BASELINE_PATH', tmp_path / 'ar_baseline.json')


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


def test_a_clean_run_exits_zero_and_prints_tasks_then_grid(capsys):
    assert ar_evals.main(['--task', 'task_13', 'task_17', '--trials', '2']) == 0
    out = capsys.readouterr().out
    assert 'task_13  2/2' in out and 'task_17  2/2' in out
    assert out.index('task_17') < out.index('overall') < out.index('No baseline yet')


def test_a_failed_never_event_exits_one(capsys):
    assert ar_evals.main(['--task', 'task_16', 'task_15']) == 1
    out = capsys.readouterr().out
    assert 'task_15  0/1' in out and 'assert_application_count(payment_id=pay_2005, expected=1)' in out
    assert 'never-event task failed' in out


def test_missed_human_in_the_loop_exits_one(capsys):
    assert ar_evals.main(['--task', 'task_18']) == 1  # needs a person; not a never-event
    assert 'recall' in capsys.readouterr().out


def test_a_split_runs_its_tasks(capsys):
    ar_evals.main(['--split', 'cross_skill'])
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
    monkeypatch.setattr(ar_evals, 'load_agent', lambda: raising_agent)
    assert ar_evals.main(['--task', 'task_13']) == 0  # failed, but neither a never-event nor a human task
    out = capsys.readouterr().out
    assert 'task_13  0/1' in out and 'RuntimeError: model unavailable' in out


def test_judge_runs_only_when_asked(monkeypatch, capsys):
    calls = []

    async def judge(text, facts):
        calls.append(text)
        return 0.5

    async def sender(store, customer_id, prompt, **options):
        from ar.environment import call_tool
        from ar.run_types import AgentTurn
        call_tool(store, customer_id, 'send_message', {
            'contact_id': 'con_801', 'channel': 'email', 'invoice_ids': ['INV-1001'],
            'body': 'INV-1001 for $12,400.00 was due on November 6, 2026.'})
        return AgentTurn(text='Sent.', cost_usd=0.0, tool_calls=1, history=None)

    monkeypatch.setattr(ar_evals, 'load_agent', lambda: sender)
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
        raise TaskFileError('db/tasks.json is malformed: annotations missing')

    monkeypatch.setattr(ar_evals, 'load_tasks', broken)
    assert ar_evals.main([]) == 2
    assert 'annotations missing' in capsys.readouterr().err
