#!/usr/bin/env python3
"""Validate every Desk V1 market file that exists; missing supported assets are reported separately."""
from pathlib import Path
from trading_lab.data import load_csv_segments, data_fingerprint
from trading_lab.desk_v1 import SUPPORTED_INSTRUMENTS

ok=True
for symbol in SUPPORTED_INSTRUMENTS:
    p=Path("data/raw")/symbol/"m1.csv"
    if not p.exists():
        print(f"{symbol}: NOT_DOWNLOADED")
        continue
    try:
        segs=load_csv_segments(p)
        bars=tuple(b for s in segs for b in s)
        exact=sum(b.has_exact_ask for b in bars)
        print(f"{symbol}: PASS rows={len(bars)} segments={len(segs)} exact_ask={exact} from={bars[0].open_time} to={bars[-1].close_time} sha256={data_fingerprint(bars)[:16]}")
    except Exception as exc:
        ok=False
        print(f"{symbol}: FAIL {exc}")
raise SystemExit(0 if ok else 1)
