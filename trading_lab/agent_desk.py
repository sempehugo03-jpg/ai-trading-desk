"""Research Desk V0.1 orchestration.

Continuous research is allowed; promotion remains gated. Blind and shadow stages
never auto-pass when their external evidence is unavailable.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .agent_provider import JsonAgentProvider
from .desk_agents import ResearcherAgent, ReviewAgent
from .quant_desk import GatePolicy, evaluate_split, evaluate_stress, evaluate_walk_forward
from .research import AgentRole, Candidate, ResearchStore, Stage, StageOutcome
from .strategy_dsl import StrategySpec


class StageBlocked(RuntimeError):
    pass


@dataclass(frozen=True)
class DeskConfig:
    data_root: str = "data/raw"
    active_candidate_cap: int = 100
    proposal_batch_size: int = 8
    idle_sleep_seconds: float = 5.0
    use_llm_reviews: bool = True


class DeskHandlers:
    def __init__(self, provider: JsonAgentProvider | None, config: DeskConfig):
        self.provider = provider
        self.config = config
        self.red_team = ReviewAgent(provider, "red_team") if provider else None
        self.risk = ReviewAgent(provider, "risk") if provider else None
        self.regime = ReviewAgent(provider, "regime") if provider else None

    @staticmethod
    def _spec(candidate: Candidate) -> StrategySpec:
        return StrategySpec.from_mapping(candidate.spec)

    def _review(self, agent, spec, metrics, evidence):
        if agent is None or not self.config.use_llm_reviews:
            return None
        return agent.review(spec, metrics, evidence)

    def research(self, c: Candidate, roles) -> StageOutcome:
        spec = self._spec(c)
        out = evaluate_split(spec, data_root=self.config.data_root, split="IS", policy=GatePolicy(min_trades=30))
        return StageOutcome(out.passed, out.metrics, out.evidence, out.reason)

    def validation(self, c: Candidate, roles) -> StageOutcome:
        spec = self._spec(c)
        out = evaluate_split(spec, data_root=self.config.data_root, split="VALIDATION", policy=GatePolicy(min_trades=20))
        review = self._review(self.red_team, spec, out.metrics, out.evidence) if out.passed else None
        veto = bool(review and review.veto)
        evidence = dict(out.evidence)
        if review: evidence["red_team"] = {"veto": review.veto, "reasons": review.reasons, "concerns": review.concerns}
        return StageOutcome(out.passed and not veto, out.metrics, evidence, "RED_TEAM_VETO" if veto else out.reason)

    def oos(self, c: Candidate, roles) -> StageOutcome:
        spec = self._spec(c)
        out = evaluate_split(spec, data_root=self.config.data_root, split="OOS", policy=GatePolicy(min_trades=20, min_expectancy_r=.01, min_profit_factor_r=1.02))
        review = self._review(self.red_team, spec, out.metrics, out.evidence) if out.passed else None
        veto = bool(review and review.veto)
        evidence = dict(out.evidence)
        if review: evidence["red_team"] = {"veto": review.veto, "reasons": review.reasons}
        return StageOutcome(out.passed and not veto, out.metrics, evidence, "RED_TEAM_VETO" if veto else out.reason)

    def walk_forward(self, c: Candidate, roles) -> StageOutcome:
        spec = self._spec(c)
        out = evaluate_walk_forward(spec, data_root=self.config.data_root)
        review = self._review(self.regime, spec, out.metrics, {"summary_only": True}) if out.passed else None
        veto = bool(review and review.veto)
        evidence = dict(out.evidence)
        if review: evidence["regime"] = {"veto": review.veto, "reasons": review.reasons}
        return StageOutcome(out.passed and not veto, out.metrics, evidence, "REGIME_VETO" if veto else out.reason)

    def stress(self, c: Candidate, roles) -> StageOutcome:
        spec = self._spec(c)
        out = evaluate_stress(spec, data_root=self.config.data_root)
        review = self._review(self.risk, spec, out.metrics, out.evidence) if out.passed else None
        veto = bool(review and review.veto)
        evidence = dict(out.evidence)
        if review: evidence["risk"] = {"veto": review.veto, "reasons": review.reasons}
        return StageOutcome(out.passed and not veto, out.metrics, evidence, "RISK_VETO" if veto else out.reason)

    def blind(self, c: Candidate, roles) -> StageOutcome:
        raise StageBlocked("Waiting for a sealed one-shot blind batch; research agents cannot inspect blind data")

    def shadow(self, c: Candidate, roles) -> StageOutcome:
        raise StageBlocked("Waiting for future paper-live evidence")

    def mapping(self):
        return {
            Stage.RESEARCH: self.research,
            Stage.VALIDATION: self.validation,
            Stage.OOS: self.oos,
            Stage.WALK_FORWARD: self.walk_forward,
            Stage.STRESS: self.stress,
            Stage.BLIND: self.blind,
            Stage.SHADOW: self.shadow,
        }


class AgentResearchDesk:
    def __init__(self, store: ResearchStore, provider: JsonAgentProvider, config: DeskConfig | None = None):
        self.store = store
        self.provider = provider
        self.config = config or DeskConfig()
        self.researcher = ResearcherAgent(provider)
        self.handlers = DeskHandlers(provider, self.config).mapping()

    def _active_count(self) -> int:
        return len(self.store.pending())

    def _memory(self):
        # Only aggregate non-blind failure reasons are fed back to Researcher.
        with sqlite3.connect(self.store.path) as db:
            rows = db.execute("SELECT stage,reason,COUNT(*) FROM events WHERE passed=0 AND stage!='BLIND' GROUP BY stage,reason ORDER BY COUNT(*) DESC LIMIT 20").fetchall()
        return tuple({"stage": r[0], "reason": r[1], "count": r[2]} for r in rows)

    def generate(self) -> int:
        if self._active_count() >= self.config.active_candidate_cap:
            return 0
        specs = self.researcher.propose(batch_size=self.config.proposal_batch_size, memory=self._memory())
        created = 0
        for spec in specs:
            cid = f"{spec.family.value.lower()}-{spec.instrument.lower()}-{spec.fingerprint[:12]}"
            try:
                self.store.add_candidate(cid, spec.family.value, 1, spec.as_dict())
                created += 1
            except sqlite3.IntegrityError:
                pass
        return created

    def step(self) -> bool:
        # Fair scheduling: a BLIND/SHADOW blocked candidate cannot freeze all research.
        candidates = self.store.pending()
        for c in candidates:
            handler = self.handlers.get(c.stage)
            if handler is None:
                continue
            try:
                outcome = handler(c, ())
            except StageBlocked:
                continue
            self.store.record(c.candidate_id, c.stage, outcome)
            return True
        return self.generate() > 0

    def run_cycles(self, n: int) -> int:
        ran = 0
        for _ in range(n):
            if not self.step():
                break
            ran += 1
        return ran

    def run_forever(self, stop=lambda: False):
        while not stop():
            if not self.step():
                time.sleep(self.config.idle_sleep_seconds)
