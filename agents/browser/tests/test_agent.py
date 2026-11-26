import os
import warnings

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from agents.browser.agent import agent, configured, trace_to_logfire


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


# Live: real model, real browser. Run with `uv run --env-file <path to .env> pytest -m e2e agents/browser`.
@pytest.mark.e2e
@pytest.mark.skipif(not os.environ.get('ANTHROPIC_API_KEY'), reason='ANTHROPIC_API_KEY is not set')
def test_reads_the_first_quote_on_quotes_toscrape():
    answer = agent.run_sync('Who wrote the first quote on https://quotes.toscrape.com/ ?').output
    assert 'Einstein' in answer


def test_the_default_config_entry_is_sonnet():
    assert (agent.model, agent.name) == ('anthropic:claude-sonnet-5-5', 'browser-agent-sonnet')


def test_a_config_key_picks_the_model_and_name():
    terra = configured('6.1-terra')
    assert (terra.model, terra.name) == ('openai:gpt-6.1-terra', 'browser-agent-terra')


def test_an_unknown_key_names_the_valid_ones():
    with pytest.raises(ValueError, match=r"'nope'.*sonnet-5\.5, 6\.1-terra"):
        configured('nope')


def test_a_broken_config_entry_is_named(monkeypatch, tmp_path):
    broken = tmp_path / 'config.yaml'
    broken.write_text('default: a\nmodels:\n  a:\n    model: test\n')
    monkeypatch.setattr('agents.browser.agent.CONFIG', broken)
    with pytest.raises(ValueError, match="'a'.*name"):
        configured()
    broken.write_text('models:\n  a:\n    model: test\n    name: a\n')
    with pytest.raises(ValueError, match='default'):
        configured()
