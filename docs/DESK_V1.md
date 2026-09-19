# Desk V1 — Multi-Strategy Portfolio Research

## North star
Research a diversified portfolio capable of approaching ~10% net/month with
>=1 portfolio trade/day on average while controlling drawdown and remaining
compatible with prop-firm loss limits. This is a research target, not a guarantee.

## No artificial strategy ceiling
V1 supports an expandable universe and eight initial strategy families:
momentum, mean reversion, breakout, trend pullback, reversal, volatility
expansion, volatility compression and liquidity sweep.

Supported data adapters:
XAUUSD, XAGUSD, EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, NAS100, US500,
US30, DAX, WTI, BRENT.

Only instruments with a validated local M1 file are exposed to research agents.
Adding data expands the desk automatically.

## Regime research
Every strategy may be unconditional or restricted to TREND, RANGE, HIGH_VOL or
LOW_VOL. This is intended to test whether an edge is conditional rather than
forcing one rule to trade all markets.

## Portfolio and prop-firm layer
`portfolio_v1.py` aggregates independent daily return streams and reports
portfolio return, drawdown, monthly returns and trades/day.

`propfirm.py` contains generic challenge rules plus FTMO 2-Step presets. The
preset reflects the public FTMO objectives checked 2026-09-19: 10% Step 1,
5% Step 2, 5% maximum daily loss, 10% maximum loss and 4 minimum trading days.
Exact floating-P&L/broker mechanics require intraday execution data; the helper
does not pretend otherwise.

## OOS discipline
Research may adapt to IS + validation. OOS failures should not be fed back as
parameter-level optimization instructions. Blind-box and paper-live evidence
remain mandatory before any production conclusion.

## Data expansion
Download only the missing assets first:

```bash
node scripts/fetch_desk_v1_data.cjs --from 2022-01-01 --to 2026-09-01 --new-assets
```

Large M1 downloads are intentionally explicit because they consume storage and
time. V1 is not hard-limited to the initial 13 instruments.
