# AI Trading Desk — LAB V0.2 delivery report

## Scope

LAB V0.2 upgrades the validated V0.1 simulator for real historical research. It does **not** trade live and it does **not** claim profitability.

## Added

- Five-asset universe: XAUUSD, NAS100, US500, EURUSD, GBPUSD.
- Pinned Dukascopy historical-data adapter (`dukascopy-node@1.50.0`).
- Separate BID and ASK M1 acquisition and timestamp merge.
- Exact ASK OHLC support in the execution engine.
- Real-market-gap segmentation without forward filling.
- Chronological IS / Validation / OOS split utilities.
- Rolling walk-forward windows.
- Spread and execution-cost stress helpers.
- Append-only SQLite experiment registry.
- Real-data validation script.
- V0.2 data-source and gate documentation.

## Verification performed locally

- Python unit/integration tests: **92 run, 92 passed, 0 failures, 0 errors, 0 skipped**.
- Node downloader syntax check: passed (`node --check`).
- Two complete synthetic replays: byte-identical for report, trades, equity, journal and synthetic source CSV.
- Synthetic bars per replay: 720.
- Journal records per replay: 784.

## Not yet verified in this delivery

The execution environment used to build this archive has no outbound npm/data access, so the Dukascopy smoke download itself has **not** been executed here. It must be run in Codespaces before Research Desk V0.1 is allowed to begin.

## Required smoke gate in Codespaces

```bash
npm install
npm run data:smoke
python scripts/check_real_data.py
```

All five instruments must report PASS. Raw market data stays under `data/` and is excluded from Git.

## Performance target

The North Star remains approximately 10% net/month and >=1 portfolio opportunity per trading day on average. This is a research target only. LAB V0.2 does not demonstrate that target.
