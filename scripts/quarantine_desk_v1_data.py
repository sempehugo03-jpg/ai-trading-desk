#!/usr/bin/env python3
"""Quarantine malformed OHLC rows for selected Desk V1 assets without inventing prices."""
from __future__ import annotations
import argparse,csv,os
from datetime import datetime
from pathlib import Path
from trading_lab.models import Bar

def valid(row):
    Bar(
        datetime.fromisoformat(row["timestamp_open"]),
        float(row["bid_open"]),float(row["bid_high"]),float(row["bid_low"]),float(row["bid_close"]),
        float(row["spread_price"]),1,
        float(row["ask_open"]),float(row["ask_high"]),float(row["ask_low"]),float(row["ask_close"]),
        float(row.get("volume") or 0),
    )

def clean(symbol):
    src=Path("data/raw")/symbol/"m1.csv"
    if not src.exists():
        print(symbol,": MISSING"); return
    tmp=src.with_suffix(".cleaning.csv")
    quarantine=src.with_name("quarantine-invalid.csv")
    kept=bad=0
    with src.open("r",encoding="utf-8-sig",newline="") as f, tmp.open("w",encoding="utf-8",newline="") as out, quarantine.open("w",encoding="utf-8",newline="") as q:
        r=csv.DictReader(f); fields=r.fieldnames
        if fields is None: raise RuntimeError("missing header")
        w=csv.DictWriter(out,fieldnames=fields); qw=csv.DictWriter(q,fieldnames=fields+["_error"])
        w.writeheader(); qw.writeheader()
        for line,row in enumerate(r,2):
            try:
                valid(row); w.writerow(row); kept+=1
            except Exception as exc:
                x=dict(row); x["_error"]=f"line {line}: {type(exc).__name__}: {exc}"; qw.writerow(x); bad+=1
    os.replace(tmp,src)
    print(f"{symbol}: kept={kept} quarantined={bad}")

p=argparse.ArgumentParser(); p.add_argument("symbols",nargs="+")
a=p.parse_args()
for s in a.symbols: clean(s.upper())
