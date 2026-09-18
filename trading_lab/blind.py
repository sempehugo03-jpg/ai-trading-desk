"""One-shot blind-box evaluation contracts.

Raw blind data must live outside the research agents' readable workspace in a real
deployment. This module prevents adaptive reuse at the application layer; it is
not a security boundary against an administrator with filesystem access.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Mapping, Sequence


@dataclass(frozen=True)
class BlindOutcome:
    batch_id: str
    box_id: str
    results: Mapping[str, Mapping[str, object]]
    retired: bool = True

    def public_view(self) -> dict:
        # Intentionally no timestamps, paths, individual trades or raw rows.
        return {
            "batch_id": self.batch_id,
            "box_id": self.box_id,
            "retired": self.retired,
            "results": {k: dict(v) for k, v in self.results.items()},
        }


class BlindBoxVault:
    """Metadata-only vault for sealed datasets and non-adaptive candidate batches."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS boxes(
                    box_id TEXT PRIMARY KEY,
                    dataset_sha256 TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL CHECK(status IN ('SEALED','RESERVED','RETIRED')),
                    created_at TEXT NOT NULL
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS batches(
                    batch_id TEXT PRIMARY KEY,
                    box_id TEXT NOT NULL,
                    candidate_ids_json TEXT NOT NULL,
                    frozen_hash TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('FROZEN','COMPLETE')),
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(box_id) REFERENCES boxes(box_id)
                )
            """)

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _candidate_blob(ids: Sequence[str]) -> tuple[str, str]:
        clean = tuple(ids)
        if not clean or len(set(clean)) != len(clean) or any(not x.strip() for x in clean):
            raise ValueError("Blind batch needs unique nonempty candidate IDs")
        raw = json.dumps(clean, separators=(",", ":"))
        return raw, hashlib.sha256(raw.encode()).hexdigest()

    def seal(self, box_id: str, dataset_sha256: str) -> None:
        if not box_id.strip() or len(dataset_sha256) < 16:
            raise ValueError("Invalid blind box identity/fingerprint")
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO boxes VALUES(?,?,?,?)",
                       (box_id, dataset_sha256, "SEALED", self._now()))

    def reserve_batch(self, batch_id: str, box_id: str, candidate_ids: Sequence[str]) -> str:
        raw, frozen_hash = self._candidate_blob(candidate_ids)
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT status FROM boxes WHERE box_id=?", (box_id,)).fetchone()
            if not row or row[0] != "SEALED":
                raise RuntimeError("Blind box is unavailable or already consumed")
            db.execute("INSERT INTO batches VALUES(?,?,?,?,?,?)",
                       (batch_id, box_id, raw, frozen_hash, "FROZEN", self._now()))
            db.execute("UPDATE boxes SET status='RESERVED' WHERE box_id=? AND status='SEALED'", (box_id,))
            if db.total_changes < 2:
                raise RuntimeError("Failed to reserve blind box atomically")
        return frozen_hash

    def frozen_candidates(self, batch_id: str) -> tuple[str, ...]:
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT candidate_ids_json,status FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
        if not row:
            raise KeyError(batch_id)
        if row[1] not in ("FROZEN", "COMPLETE"):
            raise RuntimeError("Invalid batch state")
        return tuple(json.loads(row[0]))

    def complete(self, batch_id: str) -> None:
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT box_id,status FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
            if not row or row[1] != "FROZEN":
                raise RuntimeError("Blind batch cannot be completed twice")
            box_id = row[0]
            db.execute("UPDATE batches SET status='COMPLETE' WHERE batch_id=? AND status='FROZEN'", (batch_id,))
            db.execute("UPDATE boxes SET status='RETIRED' WHERE box_id=? AND status='RESERVED'", (box_id,))
            if db.total_changes < 2:
                raise RuntimeError("Failed to retire blind box")

    def status(self, box_id: str) -> str:
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT status FROM boxes WHERE box_id=?", (box_id,)).fetchone()
        if not row:
            raise KeyError(box_id)
        return str(row[0])


class BlindEvaluator:
    """Evaluator-only facade. The opaque datasets mapping must not be given to agents."""

    def __init__(self, vault: BlindBoxVault, opaque_datasets: Mapping[str, object]):
        self.vault = vault
        self._datasets = dict(opaque_datasets)

    def evaluate_batch(
        self,
        batch_id: str,
        box_id: str,
        runner: Callable[[str, object], Mapping[str, object]],
    ) -> BlindOutcome:
        if self.vault.status(box_id) != "RESERVED":
            raise RuntimeError("Blind box is not reserved")
        if box_id not in self._datasets:
            raise KeyError("Evaluator has no raw payload for box")
        candidate_ids = self.vault.frozen_candidates(batch_id)
        payload = self._datasets[box_id]
        results: dict[str, Mapping[str, object]] = {}
        for candidate_id in candidate_ids:
            raw = dict(runner(candidate_id, payload))
            # Deliberately strip common leakage fields even if a runner returns them.
            for forbidden in ("trades", "timestamps", "start", "end", "path", "rows", "raw"):
                raw.pop(forbidden, None)
            json.dumps(raw, allow_nan=False, default=str)
            results[candidate_id] = raw
        self.vault.complete(batch_id)
        return BlindOutcome(batch_id, box_id, results)
