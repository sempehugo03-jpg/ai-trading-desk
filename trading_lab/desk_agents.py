"""Contradictory role agents for Research Desk V0.1."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .agent_provider import JsonAgentProvider
from .strategy_dsl import RESEARCH_JSON_SCHEMA, StrategySpec


REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "veto": {"type": "boolean"},
        "reasons": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        "concerns": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
    },
    "required": ["veto", "reasons", "concerns"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class AgentReview:
    role: str
    veto: bool
    reasons: tuple[str, ...]
    concerns: tuple[str, ...]


class ResearcherAgent:
    def __init__(self, provider: JsonAgentProvider):
        self.provider = provider

    def propose(self, *, batch_size: int = 8, memory: Sequence[Mapping[str, object]] = ()) -> tuple[StrategySpec, ...]:
        if not 1 <= batch_size <= 12:
            raise ValueError("batch_size must be 1..12")
        memory_tail = list(memory)[-20:]
        prompt = (
            f"Propose {batch_size} diverse intraday strategy hypotheses. "
            "Use only the supplied declarative schema. No Python/code, no hidden data assumptions, no claim of profitability. "
            "Explore momentum, mean-reversion and breakout across the five-asset universe. "
            "Do not optimize an individual strategy to the 10% monthly north-star; search for robust positive expectancy instead. "
            f"Recent aggregate failure memory (never blind raw data): {memory_tail}"
        )
        raw = self.provider.complete_json(
            role="researcher",
            instructions="You are the Researcher agent. Generate falsifiable, diverse strategy specs only.",
            prompt=prompt,
            schema_name="trading_strategy_batch",
            schema=RESEARCH_JSON_SCHEMA,
        )
        items = raw.get("strategies")
        if not isinstance(items, list):
            raise ValueError("researcher response missing strategies")
        result = []
        seen = set()
        for item in items[:batch_size]:
            if not isinstance(item, dict):
                continue
            try:
                spec = StrategySpec.from_mapping(item)
            except (ValueError, TypeError, KeyError):
                continue
            if spec.fingerprint not in seen:
                seen.add(spec.fingerprint)
                result.append(spec)
        if not result:
            raise ValueError("researcher produced no valid strategy specs")
        return tuple(result)


class ReviewAgent:
    def __init__(self, provider: JsonAgentProvider, role: str):
        if role not in {"red_team", "risk", "regime", "portfolio"}:
            raise ValueError("unsupported review role")
        self.provider = provider
        self.role = role

    def review(self, spec: StrategySpec, metrics: Mapping[str, object], evidence: Mapping[str, object]) -> AgentReview:
        prompt = (
            f"Strategy spec: {spec.as_dict()}\n"
            f"Objective metrics: {dict(metrics)}\n"
            f"Non-secret evidence: {dict(evidence)}\n"
            "Return a veto only for a concrete robustness/risk reason. Never invent measurements. "
            "A veto can reject; absence of veto can never override deterministic quantitative gates."
        )
        raw = self.provider.complete_json(
            role=self.role,
            instructions=f"You are the {self.role} agent. Be adversarial and evidence-bound.",
            prompt=prompt,
            schema_name=f"{self.role}_review",
            schema=REVIEW_SCHEMA,
        )
        return AgentReview(
            self.role,
            bool(raw.get("veto")),
            tuple(str(x) for x in raw.get("reasons", []) if str(x).strip()),
            tuple(str(x) for x in raw.get("concerns", []) if str(x).strip()),
        )
