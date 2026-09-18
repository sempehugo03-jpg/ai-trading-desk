"""Explicit, immutable contracts. Prices are quote currency per underlying unit."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from math import isfinite


class DataError(ValueError):
    """Input is unsafe or its timing convention is not explicit."""


def finite(value: float, name: str, *, positive: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not isfinite(value):
        raise ValueError(f"{name}: finite number required")
    if positive and value <= 0:
        raise ValueError(f"{name}: must be positive")


def utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise DataError("Explicit timezone required; local/naive timestamps are forbidden")
    return value.astimezone(UTC)


class Side(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"

    @property
    def sign(self) -> int:
        return 1 if self is Side.LONG else -1


@dataclass(frozen=True)
class Bar:
    """One closed price bar.

    `open/high/low/close` are BID prices. `spread` is the executable spread at
    the bar open. When exact ASK OHLC is available it is stored explicitly;
    otherwise ASK is conservatively approximated as BID + `spread`.
    """
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    spread: float
    minutes: int = 1
    ask_open: float | None = None
    ask_high: float | None = None
    ask_low: float | None = None
    ask_close: float | None = None
    volume: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "open_time", utc(self.open_time))
        if self.open_time.second or self.open_time.microsecond:
            raise DataError("Bar timestamp must be aligned to a full minute")
        if isinstance(self.minutes, bool) or not isinstance(self.minutes, int) or self.minutes < 1:
            raise DataError("Bar duration must be positive whole minutes")
        for name in ("open", "high", "low", "close"):
            finite(getattr(self, name), name, positive=True)
        finite(self.spread, "spread")
        if self.spread < 0:
            raise DataError("Spread cannot be negative")
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise DataError("Invalid bid OHLC relationships")

        asks = (self.ask_open, self.ask_high, self.ask_low, self.ask_close)
        if any(value is not None for value in asks):
            if not all(value is not None for value in asks):
                raise DataError("ASK OHLC must be supplied as a complete set")
            for name in ("ask_open", "ask_high", "ask_low", "ask_close"):
                finite(getattr(self, name), name, positive=True)
            assert self.ask_open is not None and self.ask_high is not None
            assert self.ask_low is not None and self.ask_close is not None
            if not self.ask_low <= min(self.ask_open, self.ask_close) <= max(self.ask_open, self.ask_close) <= self.ask_high:
                raise DataError("Invalid ask OHLC relationships")
            for ask_value, bid_value, label in (
                (self.ask_open, self.open, "open"), (self.ask_high, self.high, "high"),
                (self.ask_low, self.low, "low"), (self.ask_close, self.close, "close"),
            ):
                if ask_value < bid_value:
                    raise DataError(f"ASK cannot be below BID at {label}")
            # Exact real-data bars define spread from the opening executable quotes.
            if abs((self.ask_open - self.open) - self.spread) > max(1e-12, abs(self.spread) * 1e-7):
                raise DataError("spread must equal ask_open - bid_open when exact ASK is supplied")

        if self.volume is not None:
            finite(self.volume, "volume")
            if self.volume < 0:
                raise DataError("Volume cannot be negative")

    @property
    def close_time(self) -> datetime:
        return self.open_time + timedelta(minutes=self.minutes)

    @property
    def has_exact_ask(self) -> bool:
        return self.ask_open is not None

    def executable_open(self, side: Side) -> float:
        if side is Side.LONG:
            return self.ask_open if self.ask_open is not None else self.open + self.spread
        return self.open

    def executable_high(self, side: Side) -> float:
        if side is Side.SHORT:
            return self.ask_high if self.ask_high is not None else self.high + self.spread
        return self.high

    def executable_low(self, side: Side) -> float:
        if side is Side.SHORT:
            return self.ask_low if self.ask_low is not None else self.low + self.spread
        return self.low

    def executable_close(self, side: Side) -> float:
        if side is Side.SHORT:
            return self.ask_close if self.ask_close is not None else self.close + self.spread
        return self.close


@dataclass(frozen=True)
class Signal:
    side: Side
    stop: float
    target: float
    max_holding_bars: int = 30

    def __post_init__(self) -> None:
        if not isinstance(self.side, Side):
            raise ValueError("side must be a Side enum")
        finite(self.stop, "stop", positive=True)
        finite(self.target, "target", positive=True)
        if self.stop == self.target:
            raise ValueError("Stop and target cannot coincide")
        if not isinstance(self.max_holding_bars, int) or isinstance(self.max_holding_bars, bool) or self.max_holding_bars < 1:
            raise ValueError("max_holding_bars must be a positive integer")


@dataclass(frozen=True)
class Config:
    # Testing defaults ONLY. No real account, leverage, lot size or FX conversion.
    initial_equity: float = 10_000.0
    risk_fraction: float = 0.0025
    max_daily_loss: float = 0.01
    max_drawdown: float = 0.05
    max_spread_to_stop: float = 0.25
    slippage: float = 0.02
    commission_per_unit_side: float = 0.005
    session_start_utc: int = 7
    session_end_utc: int = 20

    def __post_init__(self) -> None:
        finite(self.initial_equity, "initial_equity", positive=True)
        for name in ("risk_fraction", "max_daily_loss", "max_drawdown", "max_spread_to_stop"):
            value = getattr(self, name)
            finite(value, name, positive=True)
            if value >= 1:
                raise ValueError(f"{name} must be less than 1")
        if self.risk_fraction > self.max_daily_loss or self.max_daily_loss > self.max_drawdown:
            raise ValueError("Require risk_fraction <= max_daily_loss <= max_drawdown")
        for name in ("slippage", "commission_per_unit_side"):
            finite(getattr(self, name), name)
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")
        for name in ("session_start_utc", "session_end_utc"):
            if isinstance(getattr(self, name), bool) or not isinstance(getattr(self, name), int):
                raise ValueError("Session hours must be integers")
        if not 0 <= self.session_start_utc < self.session_end_utc <= 24:
            raise ValueError("Invalid UTC session")


@dataclass(frozen=True)
class Trade:
    decision_time: datetime
    entry_time: datetime
    observed_exit_time: datetime
    side: Side
    entry: float
    exit: float
    stop: float
    target: float
    units: float
    initial_risk_quote: float
    pnl_quote: float
    r_multiple: float
    commission_quote: float
    reason: str
    # M1 OHLC cannot locate an intrabar fill's exact timestamp.
    exit_bar_open: datetime
    ambiguous: bool = False
