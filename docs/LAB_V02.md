# LAB V0.2 — Definition of Done

V0.2 upgrades the deterministic V0.1 simulator into a real-data research laboratory.

## Required capabilities

1. Five-instrument universe: XAUUSD, NAS100, US500, EURUSD, GBPUSD.
2. M1 BID + ASK historical data in UTC.
3. Exact executable-side simulation when ASK OHLC exists.
4. Chronological IS / Validation / OOS partitions; no random shuffle.
5. Rolling walk-forward windows.
6. Spread and execution-cost stress scenarios.
7. Append-only registry of every experiment, including failures.
8. Raw datasets excluded from Git and fingerprinted before use.

## North Star

The project still researches approximately **10% net/month** and at least **one portfolio opportunity per trading day on average**. These are research targets, not constraints that may override robustness, drawdown, OOS integrity or risk controls.

## Gate to Research Desk V0.1

Research agents are not allowed to search for strategies until:

- the real-data smoke download passes for all five instruments;
- the parser verifies exact BID/ASK structure;
- the full Python test suite passes;
- the initial chronological split is frozen and recorded;
- stress and registry modules pass deterministic tests.
