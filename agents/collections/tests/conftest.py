"""Fixtures the offline tests share: the database in db/, read fresh."""
import pytest

from agents.collections.data_model import CollectionsDb
from agents.collections.environment import fresh_store
from agents.collections.evals.tasks import DB_PATH, DOCUMENTS_DIR
from agents.collections.store import Store


@pytest.fixture(scope='module')
def db() -> CollectionsDb:
    return CollectionsDb.load(DB_PATH)


@pytest.fixture
def store() -> Store:
    return fresh_store(DB_PATH, DOCUMENTS_DIR)
