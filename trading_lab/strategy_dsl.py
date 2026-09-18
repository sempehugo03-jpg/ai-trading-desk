"""Safe, declarative strategy DSL for Research Desk V0.1.

LLM agents may propose JSON specs only. They never emit executable Python.
Specs are validated against hard bounds and compiled by trusted local code.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import Enum
from math import isfinite
from statistics import mean
from typing import Mapping


class Family(str, Enum):
    MOMENTUM = "MOMENTUM"
    MEAN_REVERSION = "MEAN_REVERSION"
    BREAKOUT = "BREAKOUT"


class SideMode(str, Enum):
    BOTH = "BOTH"
    LONG_ONLY = "LONG_ONLY"
    SHORT_ONLY = "SHORT_ONLY"


UNIVERSE = ("XAUUSD", "NAS100", "US500", "EURUSD", "GBPUSD")
TIMEFRAMES = (5, 15, 60)


@dataclass(frozen=True)
class StrategySpec:
    family: Family
    instrument: str
    timeframe_minutes: int
    fast_lookback: int
    slow_lookback: int
    threshold_atr: float
    stop_atr: float
    target_r: float
    max_holding_bars: int
    side_mode: SideMode = SideMode.BOTH
    session_start_utc: int = 7
    session_end_utc: int = 20

    def __post_init__(self) -> None:
        if not isinstance(self.family, Family):
            raise ValueError("family must be a supported Family")
        if self.instrument not in UNIVERSE:
            raise ValueError("instrument outside research universe")
        if self.timeframe_minutes not in TIMEFRAMES:
            raise ValueError("unsupported timeframe")
        if not 2 <= self.fast_lookback <= 100:
            raise ValueError("fast_lookback outside safe bounds")
        if not 5 <= self.slow_lookback <= 300 or self.slow_lookback <= self.fast_lookback:
            raise ValueError("slow_lookback must be > fast_lookback and <= 300")
        for name, value, lo, hi in (
            ("threshold_atr", self.threshold_atr, 0.0, 5.0),
            ("stop_atr", self.stop_atr, 0.25, 8.0),
            ("target_r", self.target_r, 0.25, 10.0),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or not lo <= float(value) <= hi:
                raise ValueError(f"{name} outside safe bounds")
        if not 1 <= self.max_holding_bars <= 240:
            raise ValueError("max_holding_bars outside safe bounds")
        if not isinstance(self.side_mode, SideMode):
            raise ValueError("side_mode must be supported")
        if not (0 <= self.session_start_utc < self.session_end_utc <= 24):
            raise ValueError("invalid UTC session")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "StrategySpec":
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"unknown strategy fields: {sorted(unknown)}")
        payload = dict(value)
        payload["family"] = Family(str(payload["family"]))
        payload["side_mode"] = SideMode(str(payload.get("side_mode", SideMode.BOTH.value)))
        for key in ("timeframe_minutes", "fast_lookback", "slow_lookback", "max_holding_bars", "session_start_utc", "session_end_utc"):
            if key in payload:
                payload[key] = int(payload[key])
        for key in ("threshold_atr", "stop_atr", "target_r"):
            if key in payload:
                payload[key] = float(payload[key])
        return cls(**payload)  # type: ignore[arg-type]

    def as_dict(self) -> dict:
        raw = asdict(self)
        raw["family"] = self.family.value
        raw["side_mode"] = self.side_mode.value
        return raw

    @property
    def fingerprint(self) -> str:
        raw = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(raw.encode()).hexdigest()


def _sma(values, n: int) -> float:
    return mean(values[-n:])


def _atr(bars, n: int) -> float:
    if len(bars) < n + 1:
        return 0.0
    trs = []
    for prev, cur in zip(bars[-n-1:-1], bars[-n:]):
        trs.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    return mean(trs) if trs else 0.0


def compile_strategy(spec: StrategySpec):
    """Compile a validated spec into a trusted Strategy callback.

    Uses only closed bars provided by the simulator. No filesystem/network access.
    """
    from .data import resample_closed
    from .models import Side, Signal

    def strategy(history):
        if not history:
            return None
        as_of = history[-1].close_time
        bars = resample_closed(history, spec.timeframe_minutes, as_of)
        need = max(spec.slow_lookback + 2, 10)
        if len(bars) < need:
            return None
        closes = [b.close for b in bars]
        atr = _atr(bars, min(20, spec.slow_lookback))
        if atr <= 0:
            return None
        current = closes[-1]
        side = None
        if spec.family is Family.MOMENTUM:
            fast = _sma(closes, spec.fast_lookback)
            slow = _sma(closes, spec.slow_lookback)
            score = (fast - slow) / atr
            if score >= spec.threshold_atr:
                side = Side.LONG
            elif score <= -spec.threshold_atr:
                side = Side.SHORT
        elif spec.family is Family.MEAN_REVERSION:
            slow = _sma(closes, spec.slow_lookback)
            score = (current - slow) / atr
            if score <= -spec.threshold_atr:
                side = Side.LONG
            elif score >= spec.threshold_atr:
                side = Side.SHORT
        else:  # BREAKOUT
            prior = bars[-spec.slow_lookback-1:-1]
            hi = max(b.high for b in prior)
            lo = min(b.low for b in prior)
            pad = spec.threshold_atr * atr
            if current >= hi + pad:
                side = Side.LONG
            elif current <= lo - pad:
                side = Side.SHORT
        if side is None:
            return None
        if spec.side_mode is SideMode.LONG_ONLY and side is Side.SHORT:
            return None
        if spec.side_mode is SideMode.SHORT_ONLY and side is Side.LONG:
            return None
        risk = spec.stop_atr * atr
        if side is Side.LONG:
            stop = current - risk
            target = current + risk * spec.target_r
        else:
            stop = current + risk
            target = current - risk * spec.target_r
        return Signal(side, stop, target, spec.max_holding_bars * spec.timeframe_minutes)

    return strategy


RESEARCH_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "strategies": {
            "type": "array",
            "minItems": 1,
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "family": {"type": "string", "enum": [x.value for x in Family]},
                    "instrument": {"type": "string", "enum": list(UNIVERSE)},
                    "timeframe_minutes": {"type": "integer", "enum": list(TIMEFRAMES)},
                    "fast_lookback": {"type": "integer", "minimum": 2, "maximum": 100},
                    "slow_lookback": {"type": "integer", "minimum": 5, "maximum": 300},
                    "threshold_atr": {"type": "number", "minimum": 0, "maximum": 5},
                    "stop_atr": {"type": "number", "minimum": 0.25, "maximum": 8},
                    "target_r": {"type": "number", "minimum": 0.25, "maximum": 10},
                    "max_holding_bars": {"type": "integer", "minimum": 1, "maximum": 240},
                    "side_mode": {"type": "string", "enum": [x.value for x in SideMode]},
                    "session_start_utc": {"type": "integer", "minimum": 0, "maximum": 23},
                    "session_end_utc": {"type": "integer", "minimum": 1, "maximum": 24},
                },
                "required": ["family", "instrument", "timeframe_minutes", "fast_lookback", "slow_lookback", "threshold_atr", "stop_atr", "target_r", "max_holding_bars", "side_mode", "session_start_utc", "session_end_utc"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["strategies"],
    "additionalProperties": False,
}
