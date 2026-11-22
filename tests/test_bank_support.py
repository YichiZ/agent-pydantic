"""Offline agent tests: scripted models, fixture database, no API key or network."""

import asyncio
import json
from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from bank_db import UnknownCustomerError
from bank_support import SupportDependencies, SupportOutput, support_agent

FINAL_OUTPUT = {'support_advice': 'ok', 'block_card': False, 'risk': 1}


def scripted(*calls: tuple[str, dict[str, Any]]) -> FunctionModel:
    """A model that makes the given tool calls in order, then returns FINAL_OUTPUT."""

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        answered = sum(isinstance(p, ToolReturnPart) for m in messages for p in m.parts)
        if answered < len(calls):
            return ModelResponse(parts=[ToolCallPart(*calls[answered])])
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, FINAL_OUTPUT)])

    return FunctionModel(model)


def run(model: FunctionModel, customer_id: str = 'u1'):
    with support_agent.override(model=model):
        return asyncio.run(support_agent.run('hi', deps=SupportDependencies(customer_id=customer_id)))


def tool_return(result, tool_name: str) -> ToolReturnPart:
    (part,) = [
        p for m in result.all_messages() for p in m.parts if isinstance(p, ToolReturnPart) and p.tool_name == tool_name
    ]
    return part


def returned(result, tool_name: str) -> Any:
    part = tool_return(result, tool_name)
    assert part.outcome == 'success', part.content
    return json.loads(part.model_response_str())


def test_list_accounts_returns_only_this_customers_accounts() -> None:
    result = run(scripted(('list_accounts', {})))
    assert isinstance(result.output, SupportOutput)
    accounts = returned(result, 'list_accounts')
    assert {a['account_id']: a['balance'] for a in accounts} == {'chk_u1': '100.10', 'sav_u1': '0'}


def test_recent_transactions_newest_first() -> None:
    result = run(scripted(('recent_transactions', {'account_id': 'chk_u1', 'limit': 2})))
    assert [t['transaction_id'] for t in returned(result, 'recent_transactions')] == ['t2', 't1']


@pytest.mark.parametrize('args', [{'account_id': 'chk_u2'}, {'account_id': 'chk_u1', 'limit': 0}])
def test_recent_transactions_rejects_bad_requests_with_a_retry(args: dict[str, Any]) -> None:
    result = run(scripted(('recent_transactions', args)))
    assert tool_return(result, 'recent_transactions').outcome == 'retried'


def test_credit_cards_need_the_capability_loaded_first() -> None:
    seen_before_load: list[set[str]] = []

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        done = {p.tool_name for p in (p for m in messages for p in m.parts) if isinstance(p, ToolReturnPart)}
        if 'load_capability' not in done:
            seen_before_load.append({t.name for t in info.function_tools})
            return ModelResponse(parts=[ToolCallPart('load_capability', {'id': 'credit-cards'})])
        if 'credit_card_accounts' not in done:
            return ModelResponse(parts=[ToolCallPart('credit_card_accounts', {})])
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, FINAL_OUTPUT)])

    result = run(FunctionModel(model))
    assert 'credit_card_accounts' not in seen_before_load[0]
    assert returned(result, 'credit_card_accounts')[0]['current_balance'] == '1038.52'


def test_unknown_customer_fails_clearly() -> None:
    with pytest.raises(UnknownCustomerError, match='nobody'):
        run(scripted(), customer_id='nobody')
