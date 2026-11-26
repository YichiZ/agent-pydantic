"""The eval set as typed, frozen models: tasks from `agents/collections/db/tasks.json` and splits from
`agents/collections/db/split_tasks.json`.

A malformed file raises `TaskFileError` naming the file and what is wrong, before anything runs.
"""

from collections import Counter
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter, ValidationError, model_validator

AGENT_DIR = Path(__file__).resolve().parent.parent  # agents/collections
DB_DIR = AGENT_DIR / 'db'
DB_PATH = DB_DIR / 'db.json'
DOCUMENTS_DIR = DB_DIR / 'documents'
TASKS_PATH = DB_DIR / 'tasks.json'
SPLITS_PATH = DB_DIR / 'split_tasks.json'


class TaskFileError(ValueError):
    """`agents/collections/db/tasks.json` or `agents/collections/db/split_tasks.json` is not what the runner expects."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')


class Step(_Frozen):
    """One initialization action: an agent tool ('assistant') or an environment function ('env')."""

    env_type: Literal['assistant', 'env']
    func_name: str
    arguments: Mapping[str, JsonValue]


class Action(_Frozen):
    """One step of the reference path."""

    action_id: str
    requestor: Literal['assistant']
    name: str
    arguments: Mapping[str, JsonValue]


class Assertion(_Frozen):
    env_type: Literal['assistant']
    func_name: str
    arguments: Mapping[str, JsonValue]
    assert_value: bool

    def label(self) -> str:
        """`assert_balance(invoice_id=INV-1301, expected=0.00)`, for reports."""
        return f'{self.func_name}({", ".join(f"{k}={v}" for k, v in self.arguments.items())})'


class Criteria(_Frozen):
    actions: tuple[Action, ...]
    env_assertions: tuple[Assertion, ...]
    reward_basis: tuple[str, ...]


class InitialState(_Frozen):
    initialization_data: JsonValue = None
    initialization_actions: tuple[Step, ...]
    message_history: JsonValue = None


class UserScenario(_Frozen):
    persona: str
    instructions: str


class Description(_Frozen):
    purpose: str
    relevant_policies: tuple[str, ...]
    notes: str | None


class Annotations(_Frozen):
    customer_id: str
    flow: Literal['collections', 'cash_application', 'disputes', 'cross_flow']
    trigger: Literal['ticket', 'chat']
    disposition: Literal['act', 'ask', 'escalate', 'do_nothing', 'refuse']
    needs_human: bool
    data_condition: str
    adversarial: bool


class Task(_Frozen):
    id: str
    description: Description
    ticket: str | None
    user_scenario: UserScenario | None
    initial_state: InitialState | None
    evaluation_criteria: Criteria
    required_documents: tuple[str, ...]
    annotations: Annotations

    @model_validator(mode='after')
    def _ticket_or_scenario(self) -> Self:
        if (self.ticket is None) == (self.user_scenario is None):
            raise ValueError(f'{self.id} must have exactly one of ticket and user_scenario.')
        return self

    @property
    def setup(self) -> tuple[Step, ...]:
        return self.initial_state.initialization_actions if self.initial_state else ()


_TASKS = TypeAdapter(tuple[Task, ...])
_SPLITS = TypeAdapter(dict[str, tuple[str, ...]])


def load_tasks(path: Path = TASKS_PATH) -> tuple[Task, ...]:
    tasks = _validate(_TASKS, path)
    duplicates = sorted(task_id for task_id, count in Counter(t.id for t in tasks).items() if count > 1)
    if duplicates:
        raise TaskFileError(f'{path}: duplicate task ids {", ".join(duplicates)}.')
    return tasks


def load_splits(path: Path = SPLITS_PATH, task_ids: Collection[str] | None = None) -> Mapping[str, tuple[str, ...]]:
    """Split name -> task ids. Every id must be a task in `task_ids` (default: the tasks in `TASKS_PATH`)."""
    splits = _validate(_SPLITS, path)
    known = set(task_ids) if task_ids is not None else {t.id for t in load_tasks()}
    unknown = sorted({i for ids in splits.values() for i in ids} - known)
    if unknown:
        raise TaskFileError(f'{path}: splits name unknown tasks {", ".join(unknown)}.')
    return splits


def _validate[T](adapter: TypeAdapter[T], path: Path) -> T:
    try:
        return adapter.validate_json(path.read_bytes())
    except ValidationError as error:
        raise TaskFileError(f'{path} is malformed: {error}') from error
    except OSError as error:
        raise TaskFileError(f'{path} cannot be read: {error}') from error
