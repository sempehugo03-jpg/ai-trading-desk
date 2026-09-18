#!/usr/bin/env python3
"""Validate downloaded M1 files and print a compact readiness report."""
from pathlib import Path
from trading_lab.data import data_fingerprint, load_csv_segments
from trading_lab.universe import UNIVERSE

ok = True
for item in UNIVERSE:
    path = Path("data/raw") / item.symbol / "m1.csv"
    if not path.exists():
        print(f"{item.symbol}: MISSING {path}")
        ok = False
        continue
    try:
        segments = load_csv_segments(path)
        bars = tuple(b for segment in segments for b in segment)
        exact = sum(b.has_exact_ask for b in bars)
        print(f"{item.symbol}: PASS rows={len(bars)} segments={len(segments)} gaps={len(segments)-1} exact_ask={exact} from={bars[0].open_time} to={bars[-1].close_time} sha256={data_fingerprint(bars)[:16]}")
    except Exception as exc:
        print(f"{item.symbol}: FAIL {exc}")
        ok = False
raise SystemExit(0 if ok else 1)
