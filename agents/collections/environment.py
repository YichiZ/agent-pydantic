"""Dispatch by name, for the tests and the eval runner.

- `TOOLS`: the 15 agent tools, each with its kind and the capability it lives in (plan, Piece F).
- `call_tool(store, customer_id, name, arguments)`: run one tool as the agent would.
- `call_env_function(store, name, arguments)`: run an environment step such as `decide_approval`.
- `check_assertion(db, func_name, arguments)`: evaluate one `env_assertions` entry.
- `fresh_store(db_path, documents_dir)`: a new store on a freshly loaded database.
"""

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from agents.collections import assertions, tools_disputes, tools_read, tools_write
from agents.collections.data_model import ArDb
from agents.collections.errors import InvalidArgumentError, UnknownToolError
from agents.collections.store import Store

type Kind = Literal['read', 'write']
type CapabilityName = Literal['base', 'collections', 'cash_application', 'disputes']


@dataclass(frozen=True)
class ToolSpec:
    name: str
    function: Callable[..., Any]
    kind: Kind
    capability: CapabilityName


def _specs(kind: Kind, capability: CapabilityName, *functions: Callable[..., Any]) -> list[ToolSpec]:
    return [ToolSpec(f.__name__, f, kind, capability) for f in functions]


TOOLS: Mapping[str, ToolSpec] = MappingProxyType({spec.name: spec for spec in [
    *_specs('read', 'base', tools_read.get_account_state, tools_read.list_open_invoices, tools_read.get_invoice,
            tools_read.get_payment, tools_read.get_remittance, tools_read.amount_due, tools_read.search_knowledge),
    *_specs('write', 'base', tools_write.execute_approval, tools_write.escalate_to_human),
    *_specs('write', 'collections', tools_write.send_message, tools_write.log_promise),
    *_specs('write', 'cash_application', tools_write.apply_payment),
    *_specs('write', 'disputes', tools_disputes.open_dispute, tools_disputes.propose_credit,
            tools_disputes.reject_dispute),
]})

ENV_FUNCTIONS: Mapping[str, Callable[..., Any]] = MappingProxyType({'decide_approval': tools_write.decide_approval})

ASSERTIONS: Mapping[str, Callable[..., bool]] = MappingProxyType({f.__name__: f for f in (
    assertions.assert_outbound_message_count, assertions.assert_last_message_amount,
    assertions.assert_message_invoices, assertions.assert_no_credit_without_approval,
    assertions.assert_unapplied_cash, assertions.assert_application_count, assertions.assert_invoice_paused,
    assertions.assert_balance, assertions.assert_credit_count, assertions.assert_dispute_status,
    assertions.assert_promise_count, assertions.assert_pending_approval_count, assertions.assert_human_requested,
)})


def call_tool(store: Store, customer_id: str, name: str, arguments: Mapping[str, Any] | None = None) -> Any:
    """Run one agent tool. Returns a `WriteResult` for writes and a JSON-ready dict or list for reads.

    Raises `PolicyDenied`, `InvalidArgumentError`, `UnknownToolError` or an `UnknownIdError`
    (all in `agents.collections.errors.TOOL_ERRORS`); none of them changes the store.
    """
    return _invoke(_lookup(TOOLS, name, 'tool').function, name, (store, customer_id), arguments)


def call_env_function(store: Store, name: str, arguments: Mapping[str, Any] | None = None) -> Any:
    return _invoke(_lookup(ENV_FUNCTIONS, name, 'environment function'), name, (store,), arguments)


def check_assertion(db: ArDb, func_name: str, arguments: Mapping[str, Any] | None = None) -> bool:
    return _invoke(_lookup(ASSERTIONS, func_name, 'assertion'), func_name, (db,), arguments)


def fresh_store(db_path: str | Path, documents_dir: str | Path) -> Store:
    directory = Path(documents_dir)
    if not directory.is_dir():
        raise NotADirectoryError(f'Documents directory {directory} does not exist.')
    return Store(db=ArDb.load(db_path), documents_dir=directory)


def _lookup[T](registry: Mapping[str, T], name: str, kind: str) -> T:
    if name not in registry:
        raise UnknownToolError(f'No {kind} named {name!r}. Known: {", ".join(sorted(registry))}.')
    return registry[name]


def _invoke(function: Callable[..., Any], name: str, leading: tuple[Any, ...],
            arguments: Mapping[str, Any] | None) -> Any:
    given = dict(arguments or {})
    signature = inspect.signature(function)
    try:
        signature.bind(*leading, **given)
    except TypeError as error:
        expected = list(signature.parameters)[len(leading):]
        raise InvalidArgumentError(f'{name} takes {expected}; got {sorted(given)}.') from error
    return function(*leading, **given)
