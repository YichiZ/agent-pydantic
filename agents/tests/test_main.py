"""`python -m agents` and `python -m agents ar`: listing, dispatch and errors, with no model calls."""
import sys

import pytest

from agents.__main__ import main
from agents.ar import cli as ar_cli
from agents.ar.evals import run, run_event


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    for module in (run, run_event):
        monkeypatch.setattr(module, 'load_dotenv', lambda: None)  # tests never read a real .env


@pytest.mark.parametrize('argv', [[], ['-h'], ['--help']])
def test_no_agent_or_help_lists_the_agents_without_importing_their_cli(argv, monkeypatch, capsys):
    monkeypatch.delitem(sys.modules, 'agents.ar.cli', raising=False)
    assert main(argv) == 0
    assert '  ar' in capsys.readouterr().out.splitlines()
    assert 'agents.ar.cli' not in sys.modules


def test_an_unknown_agent_exits_two_and_names_the_available_ones(capsys):
    assert main(['nope']) == 2
    assert "unknown agent 'nope'; available: ar" in capsys.readouterr().err


@pytest.mark.parametrize('argv', [[], ['-h']])
def test_ar_with_no_command_or_help_lists_its_commands(argv, capsys):
    assert ar_cli.main(argv) == 0
    out = capsys.readouterr().out
    assert '  run ' in out and '  eval ' in out


def test_an_unknown_ar_command_exits_two(capsys):
    assert main(['ar', 'bogus']) == 2
    assert "unknown command 'bogus'; choose from run, eval" in capsys.readouterr().err


def test_ar_run_list_reaches_run_event(capsys):
    assert main(['ar', 'run', '--list']) == 0
    assert capsys.readouterr().out.startswith('event_01  ')


def test_ar_eval_help_reaches_the_eval_parser(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(['ar', 'eval', '-h'])
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith('usage: python -m agents ar eval') and '--trials' in out
