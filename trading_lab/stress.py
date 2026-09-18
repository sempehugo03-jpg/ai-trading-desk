"""Execution-cost stress scenarios for robustness testing."""
from __future__ import annotations
from dataclasses import replace
from typing import Sequence
from .models import Bar, Config


def spread_multiplier(bars: Sequence[Bar], factor: float) -> tuple[Bar, ...]:
    if factor < 1:
        raise ValueError("Stress factor must be >= 1")
    out = []
    for b in bars:
        spread = b.spread * factor
        kwargs = {}
        if b.has_exact_ask:
            assert None not in (b.ask_open, b.ask_high, b.ask_low, b.ask_close)
            kwargs = {
                "ask_open": b.open + (b.ask_open - b.open) * factor,
                "ask_high": b.high + (b.ask_high - b.high) * factor,
                "ask_low": b.low + (b.ask_low - b.low) * factor,
                "ask_close": b.close + (b.ask_close - b.close) * factor,
            }
            spread = kwargs["ask_open"] - b.open
        out.append(replace(b, spread=spread, **kwargs))
    return tuple(out)


def cost_multiplier(config: Config, factor: float) -> Config:
    if factor < 1:
        raise ValueError("Stress factor must be >= 1")
    return replace(config,
                   slippage=config.slippage * factor,
                   commission_per_unit_side=config.commission_per_unit_side * factor)


def default_scenarios(config: Config):
    return {
        "BASE": config,
        "COST_X1_5": cost_multiplier(config, 1.5),
        "COST_X2": cost_multiplier(config, 2.0),
        "COST_X3": cost_multiplier(config, 3.0),
    }
