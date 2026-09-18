"""Reproducible synthetic plumbing test. No market feed, credentials, or paid API."""
from __future__ import annotations
import argparse
import hashlib
import json
import random
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from .data import load_csv, resample_closed, write_csv
from .engine import backtest
from .journal import HashJournal, canonical, digest
from .metrics import summarize
from .models import Bar, Config, Side, Signal


def synthetic_bars(count: int = 720) -> tuple[Bar, ...]:
    rng = random.Random(73)
    start = datetime(2025, 1, 6, 8, tzinfo=UTC)
    price = 2500.0
    bars = []
    for i in range(count):
        opening = price
        price = max(1.0, opening + rng.uniform(-0.7, 0.7))
        high = max(opening, price) + rng.uniform(0, 0.35)
        low = min(opening, price) - rng.uniform(0, 0.35)
        bars.append(Bar(start + timedelta(minutes=i), opening, high, low, price, 0.08))
    return tuple(bars)


def control_strategy(history: tuple[Bar, ...]) -> Signal | None:
    """Intentionally non-optimized periodic control. NOT a discovered strategy."""
    if len(history) % 12:
        return None
    side = Side.LONG if (len(history) // 12) % 2 else Side.SHORT
    close = history[-1].close
    return Signal(side, close - side.sign * 1.5, close + side.sign * 2.25, 18)


def run_demo(output: str | Path, csv_path: str | Path | None = None) -> dict:
    out = Path(output)
    # Never overwrite an earlier experiment or its journal.
    if out.exists():
        raise FileExistsError(f"Choose a NEW experiment directory: {out}")
    bars = load_csv(csv_path) if csv_path else synthetic_bars()
    out.mkdir(parents=True)
    if csv_path is None:
        write_csv(out / "synthetic_m1.csv", bars)
    journal = HashJournal(out / "journal.jsonl")
    cfg = Config()
    replay = backtest(bars, control_strategy, cfg, journal=journal, strategy_id="periodic-control-v0.1")
    repeated = backtest(bars, control_strategy, cfg, strategy_id="periodic-control-v0.1")
    if replay != repeated:
        raise RuntimeError("Determinism check FAILED")
    checkpoint = journal.verify()
    code_hash = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        code_hash.update(path.name.encode() + b"\0" + path.read_bytes())
    result_hash = digest(asdict(replay))
    report = {
        "lab_version": "0.1.0",
        "mode": "HISTORICAL_SIMULATION_ONLY",
        "data_kind": "USER_CSV_NOT_PROVIDER_VERIFIED" if csv_path else "SYNTHETIC_NOT_MARKET_DATA",
        "instrument": "SINGLE_INSTRUMENT_BID_CSV" if csv_path else "XAUUSD_LIKE_SYNTHETIC",
        "account_currency": "QUOTE_CURRENCY_UNITS_NOT_EUR",
        "source_bar_count": len(bars),
        "aggregate_bar_counts": {f"M{m}": len(resample_closed(bars, m, bars[-1].close_time)) for m in (5, 15, 60, 240)},
        "identical_replays": True,
        "dataset_sha256": replay.dataset_sha256,
        "source_code_sha256": code_hash.hexdigest(),
        "result_sha256": result_hash,
        "journal_records": checkpoint[0],
        "journal_head": checkpoint[1],
        "statistics": summarize(replay),
    }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (out / "trades.json").write_text(canonical([asdict(t) for t in replay.trades]) + "\n", encoding="utf-8")
    (out / "equity.json").write_text(canonical(replay.equity) + "\n", encoding="utf-8")
    # Keep this checkpoint elsewhere for independent truncation detection.
    (out / "journal-checkpoint.txt").write_text(checkpoint[1] + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="LAB V0.1: offline simulation only; no real execution")
    parser.add_argument("--out", default="runs/demo-v01", help="New output folder (existing paths are refused)")
    parser.add_argument("--csv", help="Explicit bid OHLC M1 CSV with timezone and spread_price columns")
    args = parser.parse_args()
    try:
        report = run_demo(args.out, args.csv)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"LAB stopped: {exc}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
