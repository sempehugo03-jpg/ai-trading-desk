# Research Desk V0.2 — high-performance deterministic research

V0.2 fixes the multi-year research bottleneck without changing the trading rules.

## What changed

- Higher-timeframe bars and rolling indicators are precomputed once per segment.
- The simulator no longer copies the entire M1 history on every minute during trusted DSL research.
- Research runs use compact events, preserving entries/exits and metrics while omitting millions of repetitive audit events.
- The most recently used market is cached in-process, bounded to one symbol to avoid excessive Codespace RAM use.
- Finite campaigns can set `--max-candidates`; a batch of five can now mean exactly five total candidates.
- The CLI prints progress after each completed stage, including stage counts and API token usage.
- SQLite research connections are explicitly closed.

## Anti-look-ahead invariant

The optimized compiler precomputes a signal for each *closed* strategy-timeframe bar using only that bar and earlier bars. During M1 replay, a signal becomes visible only when its corresponding timeframe bar has closed. Future bars cannot change an earlier signal.

The legacy compiler remains available and equivalence tests compare both implementations signal-by-signal and trade-by-trade.

## Resume Campaign 001

Campaign state and market data are not overwritten by this upgrade.

```bash
python scripts/run_agent_desk.py \
  --db runs/campaign-001.sqlite3 \
  --cycles 100 \
  --batch-size 5 \
  --max-candidates 5 \
  --confirm-api-costs
```

The existing five candidates will be resumed. The hard candidate cap prevents the finite campaign from silently generating more candidates.

## Verification

```bash
python -m unittest discover -s tests -q
python scripts/benchmark_research_engine.py
```

The benchmark is technical and synthetic. It is not evidence of trading profitability.
