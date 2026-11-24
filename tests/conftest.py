"""Fixtures the offline tests share: the database in db/, read fresh."""
import pytest

from ar.data_model import ArDb
from ar.environment import fresh_store
from ar.store import Store
from evals.ar_tasks import DB_PATH, DOCUMENTS_DIR


@pytest.fixture(scope='module')
def db() -> ArDb:
    return ArDb.load(DB_PATH)


@pytest.fixture
def store() -> Store:
    return fresh_store(DB_PATH, DOCUMENTS_DIR)
