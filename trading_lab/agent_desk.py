"""Research Desk V0.3 orchestration.

Independent hypothesis agents run concurrently; deterministic quantitative gates
remain sequential and authoritative to avoid RAM blow-ups on a small Codespace.
"""
from __future__ import annotations

import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .agent_provider import JsonAgentProvider
from .desk_agents import ReviewAgent
from .parallel_agents import MutationSeed, ParallelIdeaFactory
from .quant_desk import GatePolicy, evaluate_split, evaluate_stress, evaluate_walk_forward
from .research import Candidate, ResearchStore, Stage, StageOutcome
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
    total_candidate_cap: int | None = None
    parallel_researchers: int = 1
    exploration_fraction: float = 0.70
    memory_db_paths: tuple[str, ...] = ()


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

    def _parallel_reviews(self, pairs, spec, metrics, evidence):
        jobs = [(name, agent) for name, agent in pairs if agent is not None]
        if not self.config.use_llm_reviews or not jobs:
            return {}
        out = {}
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = {
                pool.submit(agent.review, spec, metrics, evidence): name
                for name, agent in jobs
            }
            for fut, name in [(f, futures[f]) for f in futures]:
                try:
                    out[name] = fut.result()
                except Exception as exc:
                    # Review infrastructure failure cannot silently approve.
                    raise RuntimeError(f"{name} review failed: {exc}") from exc
        return out

    @staticmethod
    def _review_evidence(reviews):
        return {
            name: {
                "veto": review.veto,
                "reasons": review.reasons,
                "concerns": review.concerns,
            }
            for name, review in reviews.items()
        }

    def research(self, c: Candidate, roles) -> StageOutcome:
        spec = self._spec(c)
        out = evaluate_split(
            spec, data_root=self.config.data_root, split="IS",
            policy=GatePolicy(min_trades=30),
        )
        return StageOutcome(out.passed, out.metrics, out.evidence, out.reason)

    def validation(self, c: Candidate, roles) -> StageOutcome:
        spec = self._spec(c)
        out = evaluate_split(
            spec, data_root=self.config.data_root, split="VALIDATION",
            policy=GatePolicy(min_trades=20),
        )
        if not out.passed:
            return StageOutcome(False, out.metrics, out.evidence, out.reason)
        reviews = self._parallel_reviews(
            (("red_team", self.red_team), ("regime", self.regime)),
            spec, out.metrics, out.evidence,
        )
        vetoes = [name for name, r in reviews.items() if r.veto]
        evidence = dict(out.evidence)
        evidence["independent_reviews"] = self._review_evidence(reviews)
        return StageOutcome(
            not vetoes, out.metrics, evidence,
            "MULTI_REVIEW_VETO:" + ",".join(vetoes) if vetoes else out.reason,
        )

    def oos(self, c: Candidate, roles) -> StageOutcome:
        spec = self._spec(c)
        out = evaluate_split(
            spec, data_root=self.config.data_root, split="OOS",
            policy=GatePolicy(
                min_trades=20, min_expectancy_r=.01,
                min_profit_factor_r=1.02,
            ),
        )
        if not out.passed:
            return StageOutcome(False, out.metrics, out.evidence, out.reason)
        reviews = self._parallel_reviews(
            (("red_team", self.red_team), ("regime", self.regime)),
            spec, out.metrics, out.evidence,
        )
        vetoes = [name for name, r in reviews.items() if r.veto]
        evidence = dict(out.evidence)
        evidence["independent_reviews"] = self._review_evidence(reviews)
        return StageOutcome(
            not vetoes, out.metrics, evidence,
            "MULTI_REVIEW_VETO:" + ",".join(vetoes) if vetoes else out.reason,
        )

    def walk_forward(self, c: Candidate, roles) -> StageOutcome:
        spec = self._spec(c)
        out = evaluate_walk_forward(spec, data_root=self.config.data_root)
        if not out.passed:
            return StageOutcome(False, out.metrics, out.evidence, out.reason)
        reviews = self._parallel_reviews(
            (("regime", self.regime), ("red_team", self.red_team)),
            spec, out.metrics, {"summary_only": True},
        )
        vetoes = [name for name, r in reviews.items() if r.veto]
        evidence = dict(out.evidence)
        evidence["independent_reviews"] = self._review_evidence(reviews)
        return StageOutcome(
            not vetoes, out.metrics, evidence,
            "MULTI_REVIEW_VETO:" + ",".join(vetoes) if vetoes else out.reason,
        )

    def stress(self, c: Candidate, roles) -> StageOutcome:
        spec = self._spec(c)
        out = evaluate_stress(spec, data_root=self.config.data_root)
        if not out.passed:
            return StageOutcome(False, out.metrics, out.evidence, out.reason)
        reviews = self._parallel_reviews(
            (("risk", self.risk), ("red_team", self.red_team)),
            spec, out.metrics, out.evidence,
        )
        vetoes = [name for name, r in reviews.items() if r.veto]
        evidence = dict(out.evidence)
        evidence["independent_reviews"] = self._review_evidence(reviews)
        return StageOutcome(
            not vetoes, out.metrics, evidence,
            "MULTI_REVIEW_VETO:" + ",".join(vetoes) if vetoes else out.reason,
        )

    def blind(self, c: Candidate, roles) -> StageOutcome:
        raise StageBlocked("Waiting for a sealed one-shot blind batch")

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
    def __init__(
        self, store: ResearchStore,
        provider: JsonAgentProvider,
        config: DeskConfig | None = None,
    ):
        self.store = store
        self.provider = provider
        self.config = config or DeskConfig()
        self.idea_factory = ParallelIdeaFactory(
            provider,
            workers=self.config.parallel_researchers,
            exploration_fraction=self.config.exploration_fraction,
        )
        self.handlers = DeskHandlers(provider, self.config).mapping()

    def _active_count(self) -> int:
        return len(self.store.pending())

    def _total_count(self) -> int:
        with closing(sqlite3.connect(self.store.path)) as db:
            return int(db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0])

    def _memory_paths(self) -> tuple[Path, ...]:
        paths = [Path(self.store.path)]
        for p in self.config.memory_db_paths:
            pp = Path(p)
            if pp.exists() and pp not in paths:
                paths.append(pp)
        return tuple(paths)

    @staticmethod
    def _compact_metrics(raw: str) -> dict:
        try:
            m = json.loads(raw)
        except Exception:
            return {}
        keys = (
            "closed_trades", "expectancy_r", "profit_factor_r",
            "max_drawdown_r", "entries_per_observed_session_day",
        )
        return {k: m.get(k) for k in keys if k in m}

    def _experience_memory(self, limit: int = 30):
        rows = []
        for path in self._memory_paths():
            with closing(sqlite3.connect(path)) as db:
                rows.extend(db.execute("""
                    SELECT c.candidate_id,c.spec_json,e.stage,e.reason,e.metrics_json,e.evidence_json,e.id
                    FROM events e
                    JOIN candidates c ON c.candidate_id=e.candidate_id
                    WHERE e.passed=0 AND e.stage!='BLIND'
                    ORDER BY e.id DESC
                    LIMIT ?
                """, (limit,)).fetchall())
        out = []
        for cid, spec_json, stage, reason, metrics_json, evidence_json, event_id in rows[:limit]:
            try:
                spec = json.loads(spec_json)
            except Exception:
                continue
            out.append({
                "candidate_id": cid,
                "stage": stage,
                "reason": reason,
                "metrics": self._compact_metrics(metrics_json),
                "spec": spec,
            })
        return tuple(out)

    def _mutation_seeds(self, memory) -> tuple[MutationSeed, ...]:
        scored = []
        for item in memory:
            try:
                spec = StrategySpec.from_mapping(item["spec"])
            except Exception:
                continue
            metrics = item.get("metrics") or {}
            exp = metrics.get("expectancy_r")
            trades = int(metrics.get("closed_trades") or 0)
            freq = metrics.get("entries_per_observed_session_day")
            # Prefer informative near misses; strongly negative edges are poor mutation seeds.
            if exp is None:
                score = -999.0
            else:
                expf = float(exp)
                score = expf * 20
                if expf > -0.15:
                    score += 3
                if trades >= 20:
                    score += 1
                if freq is not None and 0.05 <= float(freq) <= 5:
                    score += 1
            diagnosis = {
                "reason": item.get("reason"),
                "stage": item.get("stage"),
                "metrics": metrics,
            }
            scored.append((score, MutationSeed(spec, diagnosis)))
        scored.sort(key=lambda x: x[0], reverse=True)
        return tuple(seed for score, seed in scored[:8] if score > -10)

    def generate(self) -> int:
        if self._active_count() >= self.config.active_candidate_cap:
            return 0
        batch_size = self.config.proposal_batch_size
        if self.config.total_candidate_cap is not None:
            remaining = self.config.total_candidate_cap - self._total_count()
            if remaining <= 0:
                return 0
            batch_size = min(batch_size, remaining)
        memory = self._experience_memory()
        seeds = self._mutation_seeds(memory)
        specs = self.idea_factory.propose(
            total=batch_size, memory=memory, seeds=seeds,
        )
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
