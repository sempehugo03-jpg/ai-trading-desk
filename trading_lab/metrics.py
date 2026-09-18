"""Descriptive metrics only. No extrapolated monthly return or profitability claim."""
from collections import Counter
from statistics import mean
from .engine import Result


def summarize(result: Result) -> dict:
    trades = result.trades
    wins = sum(max(t.pnl_quote, 0) for t in trades)
    losses = -sum(min(t.pnl_quote, 0) for t in trades)
    peak, max_dd = result.initial_equity, 0.0
    for _, equity in result.equity:
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
    r_equity, r_peak, r_dd = 0.0, 0.0, 0.0
    for trade in trades:
        r_equity += trade.r_multiple
        r_peak = max(r_peak, r_equity)
        r_dd = max(r_dd, r_peak - r_equity)
    return {
        "closed_trades": len(trades),
        "open_positions": result.open_positions,
        "unfilled_at_end": result.unfilled_at_end,
        "observed_session_days": result.observed_session_days,
        "entries_per_observed_session_day": sum(e["kind"] == "ENTRY" for e in result.events) / result.observed_session_days if result.observed_session_days else None,
        "expectancy_r": mean(t.r_multiple for t in trades) if trades else None,
        "win_rate_closed_trades": sum(t.pnl_quote > 0 for t in trades) / len(trades) if trades else None,
        "profit_factor_quote": wins / losses if losses else None,
        "profit_factor_status": "DEFINED" if losses else "UNDEFINED_NO_GROSS_LOSS",
        "max_drawdown_closed_trades_r": r_dd,
        "max_drawdown_m1_close_pct": 100 * max_dd,
        "total_return_mark_to_market_pct": 100 * (result.final_equity / result.initial_equity - 1),
        "net_pnl_closed_quote": sum(t.pnl_quote for t in trades),
        "commission_closed_quote": sum(t.commission_quote for t in trades),
        "initial_equity_quote": result.initial_equity,
        "final_cash_quote": result.final_cash,
        "final_equity_quote": result.final_equity,
        "event_counts": dict(sorted(Counter(e["kind"] for e in result.events).items())),
        "monthly_target_demonstrated": False,
        "robustness_demonstrated": False,
        "warning": "Technical simulation metrics; not an estimate of future profitability. M1-close drawdown is not intrabar maximum drawdown.",
    }
