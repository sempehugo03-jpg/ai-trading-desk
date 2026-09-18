#!/usr/bin/env python3
"""Deterministic micro-benchmark for Research Desk V0.2.

Synthetic data only. Verifies trade-result equivalence before reporting timing.
No profitability inference should be drawn from this benchmark.
"""
from time import perf_counter

from trading_lab.demo import synthetic_bars
from trading_lab.engine import backtest
from trading_lab.models import Config
from trading_lab.strategy_dsl import Family, SideMode, StrategySpec, compile_strategy, compile_strategy_cached


def main():
    bars = synthetic_bars(10_000)
    spec = StrategySpec(Family.MOMENTUM, "XAUUSD", 15, 5, 20, .2, 1.5, 2.0, 10, SideMode.BOTH, 0, 24)
    cfg = Config(session_start_utc=0, session_end_utc=24, slippage=0.0,
                 commission_per_unit_side=0.0, max_daily_loss=.05,
                 max_drawdown=.15, max_spread_to_stop=.9)

    t = perf_counter()
    legacy = backtest(bars, compile_strategy(spec), cfg, strategy_id="legacy-benchmark")
    legacy_s = perf_counter() - t

    t = perf_counter()
    fast = backtest(bars, compile_strategy_cached(spec, bars), cfg,
                    strategy_id="fast-benchmark", compact_events=True,
                    copy_history=False)
    fast_s = perf_counter() - t

    if legacy.trades != fast.trades or legacy.final_equity != fast.final_equity:
        raise SystemExit("FAIL: optimized engine changed deterministic trade results")
    print({
        "bars": len(bars),
        "legacy_s": round(legacy_s, 3),
        "optimized_s": round(fast_s, 3),
        "speedup_x": round(legacy_s / fast_s, 1) if fast_s else None,
        "trade_results_identical": True,
        "note": "synthetic technical benchmark only",
    })


if __name__ == "__main__":
    main()
