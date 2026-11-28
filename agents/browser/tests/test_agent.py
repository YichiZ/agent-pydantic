import warnings
from pathlib import Path

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from agents.browser.agent import agent, configured, main, trace_to_logfire


def test_agent_runs_offline():
    # No network and no model call: TestModel skips the browser tools.
    with agent.override(model=TestModel(call_tools=[])):
        assert isinstance(agent.run_sync('hello').output, str)


def test_tracing_without_a_token_is_silent(monkeypatch, tmp_path, capsys):
    # A fresh clone or CI: no LOGFIRE_TOKEN and no .logfire/ credentials. Nothing may raise, warn or print.
    monkeypatch.delenv('LOGFIRE_TOKEN', raising=False)
    monkeypatch.chdir(tmp_path)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error')
            trace_to_logfire()
            with agent.override(model=TestModel(call_tools=[])):
                agent.run_sync('hello')
    finally:
        Agent.instrument_all(False)  # instrumentation is global; leave the other tests as they were
    assert capsys.readouterr() == ('', '')


# Live: real model, real browser, on the default entry (the Codex login). Run with `uv run pytest -m e2e agents/browser`.
@pytest.mark.e2e
@pytest.mark.skipif(not Path('~/.codex/auth.json').expanduser().exists(), reason='no Codex CLI login')
def test_reads_the_first_quote_on_quotes_toscrape():
    answer = agent.run_sync('Who wrote the first quote on https://quotes.toscrape.com/ ?').output
    assert 'Einstein' in answer


def test_the_default_config_entry_is_terra_on_codex():
    assert (agent.model, agent.name) == ('openai-codex:gpt-6.1-terra', 'browser-agent-terra-codex')


def test_a_config_key_picks_the_model_and_name():
    terra = configured('6.1-terra')
    assert (terra.model, terra.name) == ('openai:gpt-6.1-terra', 'browser-agent-terra')


def test_chat_runs_on_the_default_or_on_the_model_flag(monkeypatch):
    monkeypatch.setattr('agents.browser.agent.trace_to_logfire', lambda: None)
    chatted = []
    monkeypatch.setattr(Agent, 'to_cli_sync', lambda self, **kwargs: chatted.append(self.name))
    assert main([]) == main(['--model', 'sonnet-5.5']) == 0
    assert chatted == ['browser-agent-terra-codex', 'browser-agent-sonnet']
    with pytest.raises(SystemExit):  # a mistyped key stops before the chat starts
        main(['--model', 'nope'])
