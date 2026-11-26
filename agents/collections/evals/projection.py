"""The part of the database a run is scored on (plan section 2.2), and a compact diff of two of them.

The projection is `CollectionsDb.dump()` without the action log and without the free text a tool stores in
the agent's own words. Ids, amounts, statuses, invoice ids and dates are kept: the tools make ids
from each table's sequence and dates from `as_of_date`, so they do not vary between correct runs,
except where one run may write several rows of a table in any order (see `NATURAL_KEYS`).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from agents.collections.data_model import CollectionsDb

type Projection = dict[str, dict[str, dict[str, Any]]]

IGNORED_TABLES = frozenset({'action_log'})  # read by assertions and the human-in-the-loop axis, never compared

# (table, field, ...): a field path inside every row of `table` that is left out of the comparison.
FREE_TEXT: tuple[tuple[str, ...], ...] = (
    ('messages', 'body'),  # send_message / execute_approval: the reminder's wording
    ('disputes', 'claim'),  # open_dispute: the customer's claim as the agent put it
    ('disputes', 'resolution'),  # reject_dispute's reason, or propose_credit's "Credit ... applied: <reason>"
    ('credits', 'reason'),  # propose_credit: why, in the agent's words
    ('approvals', 'reason'),  # the policy's sentence
    ('approvals', 'note'),  # decide_approval: the reviewer's note (set by the environment only)
    ('approvals', 'payload', 'body'),  # send_message held under P5: the draft's wording
)


# table -> (natural key, generated id). A payment's lines may be applied in any order, and generated ids
# follow the order of the calls, so applications are compared by payment and invoice, not by id.
NATURAL_KEYS: dict[str, tuple[str, str]] = {'applications': ('idempotency_key', 'application_id')}


@dataclass(frozen=True)
class TableDiff:
    """How the ACTUAL rows of one table differ from TARGET's: ids only in ACTUAL, only in TARGET, or in both."""

    table: str
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()  # 'INV-1301 (status, collections_paused)'


def diff_text(d: TableDiff) -> str:
    """'invoices +INV-1 -INV-2 ~INV-3 (status)': added, removed and changed ids."""
    return ' '.join([d.table, *(f'+{i}' for i in d.added), *(f'-{i}' for i in d.removed), *(f'~{c}' for c in d.changed)])


def project(db: CollectionsDb) -> Projection:
    return {name: _rekey(name, {row_id: _strip_row(name, row) for row_id, row in rows.items()})
            for name, rows in db.dump().items() if name not in IGNORED_TABLES}


def _rekey(table: str, rows: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Key a table by its natural key, dropping the generated id, where the order of writes is free."""
    natural = NATURAL_KEYS.get(table)
    if natural is None:
        return rows
    key_field, id_field = natural
    return {row[key_field]: {k: v for k, v in row.items() if k != id_field} for row in rows.values()}


def diff(target: Projection, actual: Projection) -> tuple[TableDiff, ...]:
    """One `TableDiff` per table that differs, in table order; empty when the projections are equal."""
    found = (_table_diff(name, target.get(name, {}), actual.get(name, {})) for name in sorted({*target, *actual}))
    return tuple(d for d in found if d.added or d.removed or d.changed)


def _strip_row(table: str, row: dict[str, Any]) -> dict[str, Any]:
    for name, *path in FREE_TEXT:
        if name == table:
            row = _without(row, path)
    return row


def _without(value: Mapping[str, Any], path: list[str]) -> dict[str, Any]:
    head, *rest = path
    if not rest:
        return {key: item for key, item in value.items() if key != head}
    inner = value.get(head)
    return {**value, head: _without(inner, rest)} if isinstance(inner, Mapping) else dict(value)


def _table_diff(name: str, target: Mapping[str, dict], actual: Mapping[str, dict]) -> TableDiff:
    changed = tuple(f'{row_id} ({", ".join(_changed_fields(target[row_id], actual[row_id]))})'
                    for row_id in sorted(target.keys() & actual.keys()) if target[row_id] != actual[row_id])
    return TableDiff(table=name, added=tuple(sorted(actual.keys() - target.keys())),
                     removed=tuple(sorted(target.keys() - actual.keys())), changed=changed)


def _changed_fields(target: Mapping[str, Any], actual: Mapping[str, Any]) -> list[str]:
    return sorted(key for key in {*target, *actual} if target.get(key) != actual.get(key))
