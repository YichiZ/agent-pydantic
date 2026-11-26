"""The one mutable thing: the current database value, swapped whole by write tools."""

from dataclasses import dataclass
from pathlib import Path

from agents.collections.data_model import CollectionsDb


@dataclass
class Store:
    db: CollectionsDb
    documents_dir: Path

    def swap(self, db: CollectionsDb) -> None:
        """Replace the current database with a new value. The old value is left as it was."""
        self.db = db
