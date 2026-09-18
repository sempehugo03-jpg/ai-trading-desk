"""Deterministic quantitative gates used by the agent desk.

LLM agents do not calculate P&L. This module does.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from math import isfinite
from pathlib import Path
from statistics import mean
from typing import Iterable, Sequence

from .data import load_csv_segments
from .engine import backtest
from .models import Bar, Config
from .strategy_dsl import StrategySpec, compile_strategy
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
    eq = 0.0
    peak = 0.0
    dd = 0.0
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


def _passes(metrics: dict, policy: GatePolicy) -> tuple[bool, str]:
    n = int(metrics.get("closed_trades") or 0)
    exp = metrics.get("expectancy_r")
    pf = metrics.get("profit_factor_r")
    dd = metrics.get("max_drawdown_r")
    if n < policy.min_trades:
        return False, "INSUFFICIENT_TRADES"
    if exp is None or not isfinite(float(exp)) or float(exp) <= policy.min_expectancy_r:
        return False, "NON_POSITIVE_EXPECTANCY"
    if pf is None or not isfinite(float(pf)) or float(pf) < policy.min_profit_factor_r:
        return False, "PROFIT_FACTOR_GATE"
    if dd is None or float(dd) > policy.max_drawdown_r:
        return False, "DRAWDOWN_R_GATE"
    return True, "QUANT_PASS"


def _segments_in_fraction(segments: Sequence[Sequence[Bar]], start: float, end: float) -> tuple[tuple[Bar, ...], ...]:
    """Select a chronological count-fraction without joining market gaps.

    This avoids a huge timestamp set for multi-year M1 datasets and preserves each
    provider-contiguous segment as an independent backtest unit.
    """
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


def load_market(data_root: str | Path, symbol: str):
    path = Path(data_root) / symbol / "m1.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    return load_csv_segments(path)


def evaluate_split(spec: StrategySpec, *, data_root: str | Path = "data/raw", split: str = "IS", config: Config | None = None, policy: GatePolicy | None = None) -> QuantOutcome:
    segments = load_market(data_root, spec.instrument)
    fractions = {"IS": (0.0, .60), "VALIDATION": (.60, .80), "OOS": (.80, 1.0)}
    if split not in fractions:
        raise ValueError("split must be IS, VALIDATION or OOS")
    stage_segments = _segments_in_fraction(segments, *fractions[split])
    strategy = compile_strategy(spec)
    cfg = config or Config(session_start_utc=spec.session_start_utc, session_end_utc=spec.session_end_utc)
    results = [backtest(seg, strategy, cfg, strategy_id=spec.fingerprint[:16]) for seg in stage_segments]
    metrics = _aggregate(results)
    ok, reason = _passes(metrics, policy or GatePolicy())
    return QuantOutcome(ok, metrics, {"split": split, "segments": len(stage_segments), "strategy_hash": spec.fingerprint}, reason)


def evaluate_walk_forward(spec: StrategySpec, *, data_root: str | Path = "data/raw", folds: int = 5, config: Config | None = None, policy: GatePolicy | None = None) -> QuantOutcome:
    if folds < 3:
        raise ValueError("folds must be >=3")
    segments = load_market(data_root, spec.instrument)
    cfg = config or Config(session_start_utc=spec.session_start_utc, session_end_utc=spec.session_end_utc)
    strategy = compile_strategy(spec)
    fold_metrics = []
    # Fixed strategy: consecutive future blocks test temporal stability without refitting on the block.
    for i in range(1, folds + 1):
        start = i / (folds + 1)
        end = (i + 1) / (folds + 1)
        segs = _segments_in_fraction(segments, start, end)
        results = [backtest(seg, strategy, cfg, strategy_id=spec.fingerprint[:16]) for seg in segs]
        fold_metrics.append(_aggregate(results))
    valid = [m for m in fold_metrics if (m.get("closed_trades") or 0) > 0 and m.get("expectancy_r") is not None]
    positive = sum(float(m["expectancy_r"]) > 0 for m in valid)
    fraction = positive / len(valid) if valid else 0.0
    combined_rs_proxy = {
        "closed_trades": sum(int(m.get("closed_trades") or 0) for m in fold_metrics),
        "positive_fold_fraction": fraction,
        "folds_with_trades": len(valid),
        "mean_fold_expectancy_r": mean(float(m["expectancy_r"]) for m in valid) if valid else None,
        "worst_fold_expectancy_r": min((float(m["expectancy_r"]) for m in valid), default=None),
    }
    p = policy or GatePolicy()
    ok = len(valid) >= max(2, folds // 2) and fraction >= p.min_positive_fold_fraction and (combined_rs_proxy["mean_fold_expectancy_r"] or -1) > 0
    return QuantOutcome(ok, combined_rs_proxy, {"fold_metrics": fold_metrics}, "WALK_FORWARD_PASS" if ok else "WALK_FORWARD_UNSTABLE")


def evaluate_stress(spec: StrategySpec, *, data_root: str | Path = "data/raw", config: Config | None = None) -> QuantOutcome:
    segments = _segments_in_fraction(load_market(data_root, spec.instrument), .80, 1.0)
    base = config or Config(session_start_utc=spec.session_start_utc, session_end_utc=spec.session_end_utc)
    strategy = compile_strategy(spec)
    scenarios = []
    for name, spread_factor, cost_factor in (("BASE",1.0,1.0),("X1_5",1.5,1.5),("X2",2.0,2.0)):
        cfg = cost_multiplier(base, cost_factor) if cost_factor > 1 else base
        segs = [spread_multiplier(seg, spread_factor) if spread_factor > 1 else tuple(seg) for seg in segments]
        results = [backtest(seg, strategy, cfg, strategy_id=spec.fingerprint[:16]) for seg in segs]
        metrics = _aggregate(results)
        scenarios.append({"name": name, **metrics})
    stressed = scenarios[-1]
    ok = int(stressed.get("closed_trades") or 0) >= 10 and (stressed.get("expectancy_r") is not None and float(stressed["expectancy_r"]) > 0)
    return QuantOutcome(ok, {"scenarios": scenarios}, {"stress_max": "2x spread/cost"}, "STRESS_PASS" if ok else "STRESS_FAIL")
