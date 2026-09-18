# LAB V0.2 — Real market data

## Provider selected for the first research dataset

V0.2 uses **Dukascopy historical quotes** through the pinned open-source downloader `dukascopy-node@1.50.0`.
The provider supports separate BID and ASK candles. We download both sides and merge them by UTC timestamp.

Universe mapping:

- XAUUSD -> `xauusd`
- NAS100 -> `usatechidxusd`
- US500 -> `usa500idxusd`
- EURUSD -> `eurusd`
- GBPUSD -> `gbpusd`

Raw data is **never committed to Git** (`data/` is ignored). Every research run records a dataset fingerprint.

## Execution convention

- Long market entry: ASK open + adverse slippage.
- Long exit: BID.
- Short market entry: BID open - adverse slippage.
- Short exit: ASK.
- When exact ASK OHLC is present, short stop/target detection uses the actual ASK candle, not `bid + fixed spread`.
- If exact ASK is absent, V0.1's fixed-spread approximation remains available for synthetic tests only.

## Smoke test

```bash
npm install
npm run data:smoke
python scripts/check_real_data.py
```

This downloads one historical week for all five instruments. It is a connectivity/data-format test, not research evidence.

## Research dataset

Do not start with multi-year downloads until the smoke test passes. Once validated, download a bounded historical window, preserve it unchanged, fingerprint it, and freeze the chronological IS/Validation/OOS split before strategy search begins.
