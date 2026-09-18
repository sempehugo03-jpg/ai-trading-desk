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
from typing import Mapping, Sequence


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


def compile_strategy_cached(spec: StrategySpec, source: Sequence):
    """Compile a strategy against one fixed M1 segment in O(n) preprocessing.

    The legacy compiler recomputes resampling and rolling indicators from the
    complete M1 history on every minute. That is intentionally simple but becomes
    quadratic on multi-year datasets. This compiler precomputes only information
    that would have been available at each closed higher-timeframe bar, then the
    returned callback exposes the latest already-closed signal for the current
    M1 decision time. Future bars never contribute to an earlier signal.

    The callback is stateful for speed and is intended for one chronological
    backtest pass over the same segment.
    """
    from bisect import bisect_right
    from collections import deque
    from .data import resample_closed, validate_m1
    from .models import Side, Signal

    m1 = validate_m1(source)
    tf = resample_closed(m1, spec.timeframe_minutes, m1[-1].close_time)
    if not tf:
        return lambda history: None

    n = len(tf)
    closes = [float(b.close) for b in tf]
    highs = [float(b.high) for b in tf]
    lows = [float(b.low) for b in tf]
    close_times = [b.close_time for b in tf]

    close_prefix = [0.0] * (n + 1)
    tr = [0.0] * n
    tr_prefix = [0.0] * (n + 1)
    for i, b in enumerate(tf):
        close_prefix[i + 1] = close_prefix[i] + closes[i]
        if i:
            prev = tf[i - 1]
            tr[i] = max(float(b.high - b.low), abs(float(b.high - prev.close)), abs(float(b.low - prev.close)))
        tr_prefix[i + 1] = tr_prefix[i] + tr[i]

    def sma(i: int, width: int) -> float:
        return (close_prefix[i + 1] - close_prefix[i + 1 - width]) / width

    atr_n = min(20, spec.slow_lookback)
    signals: list[Signal | None] = [None] * n
    need = max(spec.slow_lookback + 2, 10)

    maxq: deque[int] = deque()
    minq: deque[int] = deque()

    for i in range(n):
        # For breakout, maintain exactly the previous `slow_lookback` bars,
        # excluding the current bar, matching bars[-slow-1:-1].
        prev_i = i - 1
        if prev_i >= 0:
            while maxq and highs[maxq[-1]] <= highs[prev_i]:
                maxq.pop()
            maxq.append(prev_i)
            while minq and lows[minq[-1]] >= lows[prev_i]:
                minq.pop()
            minq.append(prev_i)
        lower = i - spec.slow_lookback
        while maxq and maxq[0] < lower:
            maxq.popleft()
        while minq and minq[0] < lower:
            minq.popleft()

        if i + 1 < need or i < atr_n:
            continue
        start_tr = i - atr_n + 1
        atr = (tr_prefix[i + 1] - tr_prefix[start_tr]) / atr_n
        if atr <= 0:
            continue

        current = closes[i]
        side = None
        if spec.family is Family.MOMENTUM:
            fast = sma(i, spec.fast_lookback)
            slow = sma(i, spec.slow_lookback)
            score = (fast - slow) / atr
            if score >= spec.threshold_atr:
                side = Side.LONG
            elif score <= -spec.threshold_atr:
                side = Side.SHORT
        elif spec.family is Family.MEAN_REVERSION:
            slow = sma(i, spec.slow_lookback)
            score = (current - slow) / atr
            if score <= -spec.threshold_atr:
                side = Side.LONG
            elif score >= spec.threshold_atr:
                side = Side.SHORT
        else:
            if not maxq or not minq:
                continue
            hi, lo = highs[maxq[0]], lows[minq[0]]
            pad = spec.threshold_atr * atr
            if current >= hi + pad:
                side = Side.LONG
            elif current <= lo - pad:
                side = Side.SHORT

        if side is None:
            continue
        if spec.side_mode is SideMode.LONG_ONLY and side is Side.SHORT:
            continue
        if spec.side_mode is SideMode.SHORT_ONLY and side is Side.LONG:
            continue

        risk = spec.stop_atr * atr
        if side is Side.LONG:
            stop, target = current - risk, current + risk * spec.target_r
        else:
            stop, target = current + risk, current - risk * spec.target_r
        signals[i] = Signal(side, stop, target, spec.max_holding_bars * spec.timeframe_minutes)

    index = -1
    last_as_of = None

    def strategy(history):
        nonlocal index, last_as_of
        if not history:
            return None
        as_of = history[-1].close_time
        if last_as_of is None or as_of < last_as_of:
            index = bisect_right(close_times, as_of) - 1
        else:
            while index + 1 < n and close_times[index + 1] <= as_of:
                index += 1
        last_as_of = as_of
        return signals[index] if index >= 0 else None

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
