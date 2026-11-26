"""Fixtures the offline tests share: the database in db/, read fresh."""
import pytest

from agents.ar.data_model import ArDb
from agents.ar.environment import fresh_store
from agents.ar.evals.tasks import DB_PATH, DOCUMENTS_DIR
from agents.ar.store import Store


@pytest.fixture(scope='module')
def db() -> ArDb:
    return ArDb.load(DB_PATH)


@pytest.fixture
def store() -> Store:
    return fresh_store(DB_PATH, DOCUMENTS_DIR)
