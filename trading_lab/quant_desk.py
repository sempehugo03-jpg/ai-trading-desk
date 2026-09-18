"""Deterministic quantitative gates used by the agent desk.

LLM agents do not calculate P&L. This module does.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from statistics import mean
from typing import Sequence

from .data import load_csv_segments
from .engine import backtest
from .models import Bar, Config
from .strategy_dsl import StrategySpec, compile_strategy_cached
from .stress import cost_multiplier, spread_multiplier


@dataclass(frozen=True)
class GatePolicy:
    min_trades: int = 20
    min_expectancy_r: float = 0.0
    min_profit_factor_r: float = 1.0
    max_drawdown_r: float = 12.0
    min_positive_fold_fraction: float = 0.55

    def __post_init__(self):
        if self.min_trades < 1 or not 0 <= self.min_positive_fold_fraction <= 1:
            raise ValueError("invalid gate policy")


@dataclass(frozen=True)
class QuantOutcome:
    passed: bool
    metrics: dict
    evidence: dict
    reason: str


def _aggregate(results) -> dict:
    trades = [t for r in results for t in r.trades]
    rs = [float(t.r_multiple) for t in trades]
    wins = sum(x for x in rs if x > 0)
    losses = -sum(x for x in rs if x < 0)
    eq = peak = dd = 0.0
    for x in rs:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    days = sum(r.observed_session_days for r in results)
    entries = sum(sum(e.get("kind") == "ENTRY" for e in r.events) for r in results)
    return {
        "closed_trades": len(trades),
        "expectancy_r": mean(rs) if rs else None,
        "profit_factor_r": wins / losses if losses else None,
        "max_drawdown_r": dd,
        "entries_per_observed_session_day": entries / days if days else None,
        "observed_session_days": days,
    }


def gate_failures(metrics: dict, policy: GatePolicy) -> tuple[str, ...]:
    """Return ALL failed gates, not merely the first one."""
    failures = []
    n = int(metrics.get("closed_trades") or 0)
    exp = metrics.get("expectancy_r")
    pf = metrics.get("profit_factor_r")
    dd = metrics.get("max_drawdown_r")
    if n < policy.min_trades:
        failures.append("INSUFFICIENT_TRADES")
    if exp is None or not isfinite(float(exp)) or float(exp) <= policy.min_expectancy_r:
        failures.append("NON_POSITIVE_EXPECTANCY")
    if pf is None or not isfinite(float(pf)) or float(pf) < policy.min_profit_factor_r:
        failures.append("PROFIT_FACTOR_GATE")
    if dd is None or float(dd) > policy.max_drawdown_r:
        failures.append("DRAWDOWN_R_GATE")
    return tuple(failures)


def _passes(metrics: dict, policy: GatePolicy) -> tuple[bool, str, tuple[str, ...]]:
    failures = gate_failures(metrics, policy)
    return (not failures, failures[0] if failures else "QUANT_PASS", failures)


def _segments_in_fraction(
    segments: Sequence[Sequence[Bar]], start: float, end: float
) -> tuple[tuple[Bar, ...], ...]:
    if not (0 <= start < end <= 1):
        raise ValueError("invalid fraction")
    total = sum(len(seg) for seg in segments)
    if total == 0:
        return ()
    lo, hi = int(total * start), int(total * end)
    cursor = 0
    out = []
    for seg in segments:
        seg_start, seg_end = cursor, cursor + len(seg)
        take_lo, take_hi = max(lo, seg_start), min(hi, seg_end)
        if take_lo < take_hi:
            a, b = take_lo - seg_start, take_hi - seg_start
            part = tuple(seg[a:b])
            if len(part) >= 2:
                out.append(part)
        cursor = seg_end
        if cursor >= hi:
            break
    return tuple(out)


_MARKET_CACHE_KEY = None
_MARKET_CACHE_VALUE = None


def clear_market_cache() -> None:
    global _MARKET_CACHE_KEY, _MARKET_CACHE_VALUE
    _MARKET_CACHE_KEY = None
    _MARKET_CACHE_VALUE = None


def load_market(data_root: str | Path, symbol: str):
    global _MARKET_CACHE_KEY, _MARKET_CACHE_VALUE
    path = (Path(data_root) / symbol / "m1.csv").resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    if key != _MARKET_CACHE_KEY:
        _MARKET_CACHE_VALUE = load_csv_segments(path)
        _MARKET_CACHE_KEY = key
    return _MARKET_CACHE_VALUE


def _research_backtest(segment, spec: StrategySpec, cfg: Config):
    strategy = compile_strategy_cached(spec, segment)
    return backtest(
        segment, strategy, cfg, strategy_id=spec.fingerprint[:16],
        compact_events=True, copy_history=False,
    )


def evaluate_split(
    spec: StrategySpec, *, data_root: str | Path = "data/raw",
    split: str = "IS", config: Config | None = None,
    policy: GatePolicy | None = None,
) -> QuantOutcome:
    segments = load_market(data_root, spec.instrument)
    fractions = {"IS": (0.0, .60), "VALIDATION": (.60, .80), "OOS": (.80, 1.0)}
    if split not in fractions:
        raise ValueError("split must be IS, VALIDATION or OOS")
    stage_segments = _segments_in_fraction(segments, *fractions[split])
    cfg = config or Config(
        session_start_utc=spec.session_start_utc,
        session_end_utc=spec.session_end_utc,
    )
    results = [_research_backtest(seg, spec, cfg) for seg in stage_segments]
    metrics = _aggregate(results)
    p = policy or GatePolicy()
    ok, reason, failures = _passes(metrics, p)
    return QuantOutcome(
        ok, metrics,
        {
            "split": split,
            "segments": len(stage_segments),
            "strategy_hash": spec.fingerprint,
            "failed_gates": failures,
        },
        reason,
    )


def evaluate_walk_forward(
    spec: StrategySpec, *, data_root: str | Path = "data/raw",
    folds: int = 5, config: Config | None = None,
    policy: GatePolicy | None = None,
) -> QuantOutcome:
    if folds < 3:
        raise ValueError("folds must be >=3")
    segments = load_market(data_root, spec.instrument)
    cfg = config or Config(
        session_start_utc=spec.session_start_utc,
        session_end_utc=spec.session_end_utc,
    )
    fold_metrics = []
    for i in range(1, folds + 1):
        start = i / (folds + 1)
        end = (i + 1) / (folds + 1)
        segs = _segments_in_fraction(segments, start, end)
        results = [_research_backtest(seg, spec, cfg) for seg in segs]
        fold_metrics.append(_aggregate(results))
    valid = [
        m for m in fold_metrics
        if (m.get("closed_trades") or 0) > 0 and m.get("expectancy_r") is not None
    ]
    positive = sum(float(m["expectancy_r"]) > 0 for m in valid)
    fraction = positive / len(valid) if valid else 0.0
    metrics = {
        "closed_trades": sum(int(m.get("closed_trades") or 0) for m in fold_metrics),
        "positive_fold_fraction": fraction,
        "folds_with_trades": len(valid),
        "mean_fold_expectancy_r": mean(float(m["expectancy_r"]) for m in valid) if valid else None,
        "worst_fold_expectancy_r": min(
            (float(m["expectancy_r"]) for m in valid), default=None
        ),
    }
    p = policy or GatePolicy()
    ok = (
        len(valid) >= max(2, folds // 2)
        and fraction >= p.min_positive_fold_fraction
        and (metrics["mean_fold_expectancy_r"] or -1) > 0
    )
    return QuantOutcome(
        ok, metrics, {"fold_metrics": fold_metrics},
        "WALK_FORWARD_PASS" if ok else "WALK_FORWARD_UNSTABLE",
    )


def evaluate_stress(
    spec: StrategySpec, *, data_root: str | Path = "data/raw",
    config: Config | None = None,
) -> QuantOutcome:
    segments = _segments_in_fraction(load_market(data_root, spec.instrument), .80, 1.0)
    base = config or Config(
        session_start_utc=spec.session_start_utc,
        session_end_utc=spec.session_end_utc,
    )
    scenarios = []
    for name, spread_factor, cost_factor in (
        ("BASE", 1.0, 1.0), ("X1_5", 1.5, 1.5), ("X2", 2.0, 2.0)
    ):
        cfg = cost_multiplier(base, cost_factor) if cost_factor > 1 else base
        segs = [
            spread_multiplier(seg, spread_factor)
            if spread_factor > 1 else tuple(seg)
            for seg in segments
        ]
        results = [_research_backtest(seg, spec, cfg) for seg in segs]
        scenarios.append({"name": name, **_aggregate(results)})
    stressed = scenarios[-1]
    failures = []
    if int(stressed.get("closed_trades") or 0) < 10:
        failures.append("STRESS_INSUFFICIENT_TRADES")
    if stressed.get("expectancy_r") is None or float(stressed["expectancy_r"]) <= 0:
        failures.append("STRESS_NON_POSITIVE_EXPECTANCY")
    ok = not failures
    return QuantOutcome(
        ok, {"scenarios": scenarios},
        {"stress_max": "2x spread/cost", "failed_gates": tuple(failures)},
        "STRESS_PASS" if ok else failures[0],
    )
