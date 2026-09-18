"""Single-instrument, deterministic historical simulator. No broker/API adapter."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Callable, Sequence
from .data import data_fingerprint, validate_m1
from .journal import HashJournal
from .models import Bar, Config, Side, Signal, Trade

Strategy = Callable[[Sequence[Bar]], Signal | None]


@dataclass
class _Position:
    signal: Signal
    decision_time: datetime
    entry_time: datetime
    entry: float
    units: float
    initial_risk: float
    entry_fee: float
    held_bars: int = 0


@dataclass(frozen=True)
class Result:
    trades: tuple[Trade, ...]
    events: tuple[dict, ...]
    equity: tuple[tuple[datetime, float], ...]
    initial_equity: float
    final_cash: float
    final_equity: float
    open_positions: int
    unfilled_at_end: int
    observed_session_days: int
    dataset_sha256: str


def in_session(time: datetime, config: Config) -> bool:
    return time.weekday() < 5 and config.session_start_utc <= time.hour < config.session_end_utc


def backtest(bars: Sequence[Bar], strategy: Strategy, config: Config | None = None,
             *, journal: HashJournal | None = None, strategy_id: str = "unnamed-control",
             compact_events: bool = False, copy_history: bool = True) -> Result:
    """Strategy sees only immutable closed bars. Orders fill no earlier than next open.

    Trusted callbacks only: Python callbacks are not sandboxed against global files,
    full datasets or network access. Generated/untrusted strategy code is NOT run here.
    """
    source = validate_m1(bars)
    cfg = config or Config()
    if not callable(strategy) or not isinstance(strategy_id, str) or not strategy_id.strip():
        raise ValueError("A callable and a nonempty versioned strategy_id are required")
    cash = cfg.initial_equity
    peak = cash
    day_start = cash
    day = None
    halted = False
    stopped_for_day = False
    position: _Position | None = None
    pending: tuple[datetime, Signal] | None = None
    trades: list[Trade] = []
    events: list[dict] = []
    curve = [(source[0].open_time, cash)]
    history: list[Bar] = []
    sessions = set()
    dataset_hash = data_fingerprint(source)

    def emit(kind: str, time: datetime, **fields) -> None:
        # Research runs can omit per-minute NO_TRADE events. This keeps the
        # simulator O(n) in memory while preserving entries/exits/rejections.
        # The default remains the fully verbose audit trail used by existing tests.
        if compact_events and kind in {"NO_TRADE", "ORDER_SUBMITTED", "ORDER_REJECTED"}:
            return
        event = {"kind": kind, "simulated_time": time, **fields}
        if journal is not None:
            journal.append(event)  # record this decision before progressing to the next bar
        events.append(event)

    def mark(bar: Bar) -> float:
        if position is None:
            return cash
        side = position.signal.side
        liquidation = bar.executable_close(side) - side.sign * cfg.slippage
        return cash + side.sign * (liquidation - position.entry) * position.units - cfg.commission_per_unit_side * position.units

    def close(bar: Bar, price: float, reason: str, *, ambiguous: bool = False, at_open: bool = False) -> None:
        nonlocal cash, position
        assert position is not None
        p = position
        exit_fee = cfg.commission_per_unit_side * p.units
        gross = p.signal.side.sign * (price - p.entry) * p.units
        pnl = gross - p.entry_fee - exit_fee
        cash += gross - exit_fee
        observed = bar.open_time if at_open else bar.close_time
        trade = Trade(p.decision_time, p.entry_time, observed, p.signal.side, p.entry,
                      price, p.signal.stop, p.signal.target, p.units, p.initial_risk,
                      pnl, pnl / p.initial_risk, p.entry_fee + exit_fee, reason,
                      bar.open_time, ambiguous)
        trades.append(trade)
        emit("EXIT", observed, **{k: v for k, v in asdict(trade).items() if k != "observed_exit_time"})
        position = None

    emit("RUN_START", source[0].open_time, mode="HISTORICAL_SIMULATION_ONLY",
         strategy_id=strategy_id, config=asdict(cfg), dataset_sha256=dataset_hash)

    for bar in source:
        if day != bar.open_time.date():
            day = bar.open_time.date()
            day_start = cash
            stopped_for_day = False
        if in_session(bar.open_time, cfg):
            sessions.add(day)
        if pending is not None:
            decision, signal = pending
            pending = None  # market-next-open order; never silently carried forward
            entry = bar.executable_open(signal.side) + signal.side.sign * cfg.slippage
            geometry = signal.stop < entry < signal.target if signal.side is Side.LONG else signal.target < entry < signal.stop
            distance = abs(entry - signal.stop)
            risk_budget = cash * cfg.risk_fraction
            reason = None
            if bar.open_time != decision:
                reason = "STALE_ORDER"
            elif not in_session(bar.open_time, cfg):
                reason = "OUTSIDE_SESSION"
            elif halted or stopped_for_day:
                reason = "RISK_HALTED"
            elif not geometry:
                reason = "INVALID_ENTRY_AFTER_GAP"
            elif (bar.executable_open(Side.LONG) - bar.executable_open(Side.SHORT)) > distance * cfg.max_spread_to_stop:
                reason = "SPREAD_TOO_HIGH"
            elif cash <= 0 or risk_budget > cash - day_start * (1 - cfg.max_daily_loss) + 1e-9:
                reason = "DAILY_RISK_BUDGET"
            elif risk_budget > cash - peak * (1 - cfg.max_drawdown) + 1e-9:
                reason = "DRAWDOWN_RISK_BUDGET"
            if reason:
                emit("ORDER_REJECTED", bar.open_time, reason=reason)
            else:
                risk_per_unit = distance + cfg.slippage + 2 * cfg.commission_per_unit_side
                units = risk_budget / risk_per_unit  # synthetic underlying units, NOT broker lots
                entry_fee = units * cfg.commission_per_unit_side
                cash -= entry_fee
                position = _Position(signal, decision, bar.open_time, entry, units, risk_budget, entry_fee)
                emit("ENTRY", bar.open_time, side=signal.side, entry=entry, stop=signal.stop,
                     target=signal.target, units=units, initial_risk_quote=risk_budget)

        if position is not None:
            p = position
            p.held_bars += 1
            long = p.signal.side is Side.LONG
            quote_open = bar.executable_open(p.signal.side)
            quote_low = bar.executable_low(p.signal.side)
            quote_high = bar.executable_high(p.signal.side)
            stop, target = p.signal.stop, p.signal.target
            gap_stop = quote_open <= stop if long else quote_open >= stop
            gap_target = quote_open >= target if long else quote_open <= target
            hit_stop = quote_low <= stop if long else quote_high >= stop
            hit_target = quote_high >= target if long else quote_low <= target
            if gap_stop:
                close(bar, quote_open - p.signal.side.sign * cfg.slippage, "STOP_GAP", at_open=True)
            elif gap_target:
                close(bar, target, "TARGET_GAP", at_open=True)  # limit: never manufacture favorable price improvement
            elif hit_stop:
                close(bar, stop - p.signal.side.sign * cfg.slippage, "STOP", ambiguous=hit_target)
            elif hit_target:
                close(bar, target, "TARGET")  # target is a limit; no worse-than-limit slippage
            elif bar.close_time.date() != bar.open_time.date() or not in_session(bar.close_time, cfg):
                price = bar.executable_close(p.signal.side) - p.signal.side.sign * cfg.slippage
                close(bar, price, "SESSION_END")
            elif p.held_bars >= p.signal.max_holding_bars:
                price = bar.executable_close(p.signal.side) - p.signal.side.sign * cfg.slippage
                close(bar, price, "TIME_STOP")

        equity = mark(bar)
        peak = max(peak, equity)
        daily_breach = equity <= day_start * (1 - cfg.max_daily_loss)
        dd_breach = equity <= peak * (1 - cfg.max_drawdown)
        stopped_for_day = stopped_for_day or daily_breach
        halted = halted or dd_breach
        if (daily_breach or dd_breach) and position is not None:
            side = position.signal.side
            price = bar.executable_close(side) - side.sign * cfg.slippage
            close(bar, price, "RISK_CLOSE")
            equity = cash
        curve.append((bar.close_time, equity))
        history.append(bar)
        if position is not None:
            emit("NO_TRADE", bar.close_time, reason="ONE_POSITION_MAX")
        elif halted or stopped_for_day:
            emit("NO_TRADE", bar.close_time, reason="RISK_HALTED")
        elif not in_session(bar.close_time, cfg):
            emit("NO_TRADE", bar.close_time, reason="OUTSIDE_SESSION")
        else:
            signal = strategy(tuple(history) if copy_history else history)
            if signal is None:
                emit("NO_TRADE", bar.close_time, reason="NO_SIGNAL")
            elif not isinstance(signal, Signal):
                raise TypeError("Strategy must return Signal or None; stopping the simulation")
            else:
                pending = (bar.close_time, signal)
                emit("ORDER_SUBMITTED", bar.close_time, **asdict(signal))

    unfilled = int(pending is not None)
    if pending is not None:
        emit("ORDER_UNFILLED", source[-1].close_time, reason="END_OF_DATA")
    # Do NOT invent an end-of-file fill/close; include still-open mark-to-market P&L.
    emit("RUN_END", source[-1].close_time, cash=cash, equity=curve[-1][1],
         open_positions=int(position is not None), unfilled_at_end=unfilled)
    return Result(tuple(trades), tuple(events), tuple(curve), cfg.initial_equity, cash,
                  curve[-1][1], int(position is not None), unfilled, len(sessions), dataset_hash)
