"""Contradictory agents for Research Desk V0.3."""
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

    def propose(
        self, *, batch_size: int = 8,
        memory: Sequence[Mapping[str, object]] = (),
        focus: str = "",
        role: str = "researcher",
    ) -> tuple[StrategySpec, ...]:
        if not 1 <= batch_size <= 12:
            raise ValueError("batch_size must be 1..12")
        memory_tail = list(memory)[-30:]
        prompt = (
            f"Propose {batch_size} diverse intraday strategy hypotheses. "
            "Use only the supplied declarative schema. No Python/code and no profitability claims. "
            "The portfolio north-star is about 10% net/month with >=1 portfolio trade/day, but do NOT "
            "force an individual strategy to hit that target. Search for robust positive expectancy after costs. "
            "Treat failed experiments as scientific evidence, not as instructions to overfit them. "
            f"Specialist focus: {focus or 'broad diversified exploration'}\n"
            f"Non-blind research memory: {memory_tail}"
        )
        raw = self.provider.complete_json(
            role=role,
            instructions=(
                "You are an independent strategy research specialist. Generate falsifiable strategy specs only. "
                "Prefer materially different hypotheses over cosmetic parameter changes."
            ),
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


class MutationAgent:
    """Produces controlled local experiments around a prior candidate.

    The model may suggest a full spec, but this class only accepts mutations that
    keep family+instrument fixed and alter at most two remaining fields.
    """

    _IDENTITY = {"family", "instrument"}

    def __init__(self, provider: JsonAgentProvider):
        self.provider = provider
        self.researcher = ResearcherAgent(provider)

    @staticmethod
    def distance(parent: StrategySpec, child: StrategySpec) -> int:
        a, b = parent.as_dict(), child.as_dict()
        return sum(a[k] != b[k] for k in a if k not in MutationAgent._IDENTITY)

    def mutate(
        self, parent: StrategySpec, *,
        diagnosis: Mapping[str, object],
        batch_size: int = 1,
    ) -> tuple[StrategySpec, ...]:
        focus = (
            "CONTROLLED MUTATION. Parent spec: "
            f"{parent.as_dict()}. Diagnosis: {dict(diagnosis)}. "
            "Keep family and instrument identical. Change only ONE or TWO other fields. "
            "Use the diagnosis to design an informative experiment, not to chase a backtest score."
        )
        proposed = self.researcher.propose(
            batch_size=max(1, min(12, batch_size * 2)),
            memory=(),
            focus=focus,
            role="mutator",
        )
        valid = []
        for child in proposed:
            if child.family is not parent.family or child.instrument != parent.instrument:
                continue
            d = self.distance(parent, child)
            if 1 <= d <= 2:
                valid.append(child)
            if len(valid) >= batch_size:
                break
        return tuple(valid)


class ReviewAgent:
    def __init__(self, provider: JsonAgentProvider, role: str):
        if role not in {"red_team", "risk", "regime", "portfolio"}:
            raise ValueError("unsupported review role")
        self.provider = provider
        self.role = role

    def review(
        self, spec: StrategySpec,
        metrics: Mapping[str, object],
        evidence: Mapping[str, object],
    ) -> AgentReview:
        prompt = (
            f"Strategy spec: {spec.as_dict()}\n"
            f"Objective metrics: {dict(metrics)}\n"
            f"Non-secret evidence: {dict(evidence)}\n"
            "Return a veto only for a concrete robustness/risk reason. Never invent measurements. "
            "A veto can reject; absence of veto can never override deterministic quantitative gates."
        )
        raw = self.provider.complete_json(
            role=self.role,
            instructions=f"You are the {self.role} agent. Be adversarial, independent and evidence-bound.",
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
