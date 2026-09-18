"""Crash-safe continuous research orchestration for AI Trading Desk V0.3.

This module schedules work; it does not claim any strategy is profitable and does
not execute live orders. Stage handlers are pluggable and must return objective
metrics/evidence.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping, Sequence


class Stage(str, Enum):
    RESEARCH = "RESEARCH"
    VALIDATION = "VALIDATION"
    OOS = "OOS"
    WALK_FORWARD = "WALK_FORWARD"
    STRESS = "STRESS"
    BLIND = "BLIND"
    SHADOW = "SHADOW"
    PROMOTED = "PROMOTED"
    REJECTED = "REJECTED"


class AgentRole(str, Enum):
    RESEARCHER = "RESEARCHER"
    QUANT = "QUANT"
    RED_TEAM = "RED_TEAM"
    REGIME = "REGIME"
    PORTFOLIO = "PORTFOLIO"
    RISK = "RISK"
    BLIND_EVALUATOR = "BLIND_EVALUATOR"
    SHADOW = "SHADOW"


ROLE_PLAN: dict[Stage, tuple[AgentRole, ...]] = {
    Stage.RESEARCH: (AgentRole.RESEARCHER,),
    Stage.VALIDATION: (AgentRole.QUANT, AgentRole.RED_TEAM),
    Stage.OOS: (AgentRole.QUANT, AgentRole.RED_TEAM),
    Stage.WALK_FORWARD: (AgentRole.QUANT, AgentRole.REGIME),
    Stage.STRESS: (AgentRole.RED_TEAM, AgentRole.RISK),
    Stage.BLIND: (AgentRole.BLIND_EVALUATOR, AgentRole.RISK),
    Stage.SHADOW: (AgentRole.SHADOW, AgentRole.PORTFOLIO, AgentRole.RISK),
}

NEXT_STAGE: dict[Stage, Stage] = {
    Stage.RESEARCH: Stage.VALIDATION,
    Stage.VALIDATION: Stage.OOS,
    Stage.OOS: Stage.WALK_FORWARD,
    Stage.WALK_FORWARD: Stage.STRESS,
    Stage.STRESS: Stage.BLIND,
    Stage.BLIND: Stage.SHADOW,
    Stage.SHADOW: Stage.PROMOTED,
}


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    strategy_family: str
    version: int
    stage: Stage
    spec_json: str
    created_at: str
    updated_at: str

    @property
    def spec(self) -> dict:
        return json.loads(self.spec_json)


@dataclass(frozen=True)
class StageOutcome:
    passed: bool
    metrics: Mapping[str, object]
    evidence: Mapping[str, object]
    reason: str = ""

    def __post_init__(self) -> None:
        json.dumps(dict(self.metrics), allow_nan=False, default=str)
        json.dumps(dict(self.evidence), allow_nan=False, default=str)
        if not isinstance(self.reason, str):
            raise TypeError("reason must be text")


class ResearchStore:
    """SQLite state machine and append-only audit event log."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS candidates (
                    candidate_id TEXT PRIMARY KEY,
                    strategy_family TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    stage TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    at TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    passed INTEGER,
                    metrics_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    reason TEXT NOT NULL
                )
            """)

    def _connect(self):
        return sqlite3.connect(self.path)

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _canonical(value: Mapping) -> str:
        return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)

    def add_candidate(self, candidate_id: str, strategy_family: str, version: int, spec: Mapping) -> None:
        if not candidate_id.strip() or not strategy_family.strip() or version < 1:
            raise ValueError("Invalid candidate identity")
        now = self._now()
        with self._connect() as db:
            db.execute(
                "INSERT INTO candidates VALUES (?,?,?,?,?,?,?)",
                (candidate_id, strategy_family, version, Stage.RESEARCH.value,
                 self._canonical(spec), now, now),
            )
            db.execute(
                "INSERT INTO events(at,candidate_id,stage,passed,metrics_json,evidence_json,reason) VALUES(?,?,?,?,?,?,?)",
                (now, candidate_id, Stage.RESEARCH.value, None, "{}", "{}", "CANDIDATE_CREATED"),
            )

    def get(self, candidate_id: str) -> Candidate:
        with self._connect() as db:
            row = db.execute(
                "SELECT candidate_id,strategy_family,version,stage,spec_json,created_at,updated_at FROM candidates WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()
        if not row:
            raise KeyError(candidate_id)
        return Candidate(row[0], row[1], row[2], Stage(row[3]), row[4], row[5], row[6])

    def pending(self) -> tuple[Candidate, ...]:
        terminal = (Stage.PROMOTED.value, Stage.REJECTED.value)
        with self._connect() as db:
            rows = db.execute(
                "SELECT candidate_id,strategy_family,version,stage,spec_json,created_at,updated_at FROM candidates WHERE stage NOT IN (?,?) ORDER BY created_at,candidate_id",
                terminal,
            ).fetchall()
        return tuple(Candidate(r[0], r[1], r[2], Stage(r[3]), r[4], r[5], r[6]) for r in rows)

    def record(self, candidate_id: str, current_stage: Stage, outcome: StageOutcome) -> Stage:
        candidate = self.get(candidate_id)
        if candidate.stage is not current_stage:
            raise RuntimeError(f"Stage changed concurrently: expected {current_stage}, got {candidate.stage}")
        next_stage = NEXT_STAGE[current_stage] if outcome.passed else Stage.REJECTED
        now = self._now()
        with self._connect() as db:
            db.execute(
                "INSERT INTO events(at,candidate_id,stage,passed,metrics_json,evidence_json,reason) VALUES(?,?,?,?,?,?,?)",
                (now, candidate_id, current_stage.value, int(outcome.passed),
                 self._canonical(outcome.metrics), self._canonical(outcome.evidence), outcome.reason),
            )
            db.execute(
                "UPDATE candidates SET stage=?,updated_at=? WHERE candidate_id=? AND stage=?",
                (next_stage.value, now, candidate_id, current_stage.value),
            )
            if db.total_changes < 2:
                raise RuntimeError("Failed to atomically advance candidate")
        return next_stage

    def events(self, candidate_id: str) -> tuple[dict, ...]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT id,at,stage,passed,metrics_json,evidence_json,reason FROM events WHERE candidate_id=? ORDER BY id",
                (candidate_id,),
            ).fetchall()
        return tuple({
            "id": r[0], "at": r[1], "stage": r[2], "passed": None if r[3] is None else bool(r[3]),
            "metrics": json.loads(r[4]), "evidence": json.loads(r[5]), "reason": r[6],
        } for r in rows)


StageHandler = Callable[[Candidate, tuple[AgentRole, ...]], StageOutcome]


class ContinuousResearchLoop:
    """Persistent staged scheduler. It may run forever, but every stage is fail-closed.

    A handler exception rejects nothing and promotes nothing: the candidate remains
    in the same stage so an operator can inspect/retry the infrastructure safely.
    """

    def __init__(self, store: ResearchStore, handlers: Mapping[Stage, StageHandler]):
        self.store = store
        self.handlers = dict(handlers)

    def step(self) -> bool:
        items = self.store.pending()
        if not items:
            return False
        candidate = items[0]
        handler = self.handlers.get(candidate.stage)
        if handler is None:
            raise RuntimeError(f"No handler configured for {candidate.stage.value}")
        outcome = handler(candidate, ROLE_PLAN[candidate.stage])
        if not isinstance(outcome, StageOutcome):
            raise TypeError("Stage handler must return StageOutcome")
        self.store.record(candidate.candidate_id, candidate.stage, outcome)
        return True

    def run_cycles(self, max_cycles: int) -> int:
        if max_cycles < 0:
            raise ValueError("max_cycles must be nonnegative")
        n = 0
        while n < max_cycles and self.step():
            n += 1
        return n

    def run_forever(self, poll_seconds: float = 5.0, stop: Callable[[], bool] | None = None) -> None:
        if poll_seconds < 0:
            raise ValueError("poll_seconds must be nonnegative")
        stop = stop or (lambda: False)
        while not stop():
            worked = self.step()
            if not worked:
                time.sleep(poll_seconds)
