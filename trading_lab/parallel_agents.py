"""Parallel idea generation for Research Desk V0.3.

Parallelism is used where it is cheap and safe: independent LLM hypothesis calls.
The deterministic backtester remains the authority on P&L and gates.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Mapping, Sequence

from .agent_provider import JsonAgentProvider
from .desk_agents import MutationAgent, ResearcherAgent
from .strategy_dsl import StrategySpec


@dataclass(frozen=True)
class MutationSeed:
    spec: StrategySpec
    diagnosis: Mapping[str, object]


@dataclass(frozen=True)
class SpecialistPlan:
    name: str
    focus: str


DEFAULT_SPECIALISTS = (
    SpecialistPlan(
        "gold_microstructure",
        "Focus on XAUUSD. Explore different timeframes, sessions and signal frequencies; avoid only one parameter regime.",
    ),
    SpecialistPlan(
        "index_intraday",
        "Focus on NAS100 and US500 intraday behavior. Explore momentum, breakout and mean-reversion hypotheses.",
    ),
    SpecialistPlan(
        "fx_sessions",
        "Focus on EURUSD and GBPUSD. Explore London/NY session structure and multiple time horizons.",
    ),
    SpecialistPlan(
        "frequency_balance",
        "Seek hypotheses plausibly producing useful but not pathological trade frequency. Avoid both near-zero and hyperactive signals.",
    ),
    SpecialistPlan(
        "contrarian_search",
        "Deliberately search parameter regions dissimilar to recent failures. Prefer hypotheses that could falsify current assumptions.",
    ),
    SpecialistPlan(
        "robustness_first",
        "Prioritize simple parameterizations likely to remain stable under higher costs and different regimes.",
    ),
)


class ParallelIdeaFactory:
    def __init__(
        self, provider: JsonAgentProvider, *,
        workers: int = 6,
        exploration_fraction: float = 0.70,
        specialists: Sequence[SpecialistPlan] = DEFAULT_SPECIALISTS,
    ):
        if workers < 1:
            raise ValueError("workers must be >=1")
        if not 0 <= exploration_fraction <= 1:
            raise ValueError("exploration_fraction must be between 0 and 1")
        self.provider = provider
        self.workers = workers
        self.exploration_fraction = exploration_fraction
        self.specialists = tuple(specialists)
        self.researcher = ResearcherAgent(provider)
        self.mutator = MutationAgent(provider)

    def propose(
        self, *, total: int,
        memory: Sequence[Mapping[str, object]] = (),
        seeds: Sequence[MutationSeed] = (),
    ) -> tuple[StrategySpec, ...]:
        if total < 1:
            return ()

        # Backward-compatible mono-worker mode: one provider call may return
        # the whole requested batch. The CLI explicitly uses >1 workers for
        # real parallel campaigns.
        if self.workers == 1:
            return self.researcher.propose(
                batch_size=min(total, 12),
                memory=memory,
                focus="broad diversified exploration",
                role="researcher",
            )[:total]

        mutation_slots = min(len(seeds), round(total * (1 - self.exploration_fraction)))
        exploration_slots = total - mutation_slots

        jobs = []
        for i in range(exploration_slots):
            plan = self.specialists[i % len(self.specialists)]
            jobs.append((
                i,
                "explore",
                lambda plan=plan: self.researcher.propose(
                    batch_size=1, memory=memory, focus=plan.focus,
                    role=f"researcher_{plan.name}",
                ),
            ))
        base = len(jobs)
        for i in range(mutation_slots):
            seed = seeds[i % len(seeds)]
            jobs.append((
                base + i,
                "mutate",
                lambda seed=seed: self.mutator.mutate(
                    seed.spec, diagnosis=seed.diagnosis, batch_size=1,
                ),
            ))

        ordered: dict[int, tuple[StrategySpec, ...]] = {}
        with ThreadPoolExecutor(max_workers=min(self.workers, len(jobs))) as pool:
            futs = {pool.submit(fn): idx for idx, _kind, fn in jobs}
            for fut in as_completed(futs):
                idx = futs[fut]
                try:
                    ordered[idx] = tuple(fut.result())
                except Exception:
                    # One specialist failure must not discard the other independent work.
                    ordered[idx] = ()

        out = []
        seen = set()
        for idx in sorted(ordered):
            for spec in ordered[idx]:
                if spec.fingerprint in seen:
                    continue
                seen.add(spec.fingerprint)
                out.append(spec)
                if len(out) >= total:
                    return tuple(out)
        return tuple(out)
