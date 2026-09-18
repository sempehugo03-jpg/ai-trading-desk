"""Append-only SQLite registry of every research experiment, including failures."""
from __future__ import annotations
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping

@dataclass(frozen=True)
class Experiment:
    id: int
    created_at: str
    strategy_id: str
    instrument: str
    split: str
    dataset_sha256: str
    params_json: str
    metrics_json: str
    status: str

class ExperimentRegistry:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS experiments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    instrument TEXT NOT NULL,
                    split TEXT NOT NULL,
                    dataset_sha256 TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('PASS','FAIL','ERROR'))
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_experiments_strategy ON experiments(strategy_id, instrument, split)")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path)
        try:
            yield db
            db.commit()
        finally:
            db.close()

    @staticmethod
    def _canonical(value: Mapping) -> str:
        return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)

    def append(self, *, strategy_id: str, instrument: str, split: str,
               dataset_sha256: str, params: Mapping, metrics: Mapping, status: str) -> int:
        if status not in {"PASS", "FAIL", "ERROR"}:
            raise ValueError("Invalid experiment status")
        if not all(isinstance(v, str) and v.strip() for v in (strategy_id, instrument, split, dataset_sha256)):
            raise ValueError("Experiment identity fields must be nonempty strings")
        created = datetime.now(UTC).isoformat()
        with self._connect() as db:
            cur = db.execute(
                "INSERT INTO experiments(created_at,strategy_id,instrument,split,dataset_sha256,params_json,metrics_json,status) VALUES (?,?,?,?,?,?,?,?)",
                (created, strategy_id, instrument, split, dataset_sha256,
                 self._canonical(params), self._canonical(metrics), status),
            )
            return int(cur.lastrowid)

    def all(self) -> tuple[Experiment, ...]:
        with self._connect() as db:
            rows = db.execute("SELECT id,created_at,strategy_id,instrument,split,dataset_sha256,params_json,metrics_json,status FROM experiments ORDER BY id").fetchall()
        return tuple(Experiment(*row) for row in rows)
