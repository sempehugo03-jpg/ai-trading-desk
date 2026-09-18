"""Strict M1 CSV ingestion and aggregation of fully closed, complete UTC bars."""
from __future__ import annotations
import csv
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Sequence
from .models import Bar, DataError, utc

COLUMNS = ("timestamp_open", "bid_open", "bid_high", "bid_low", "bid_close", "spread_price")


def validate_m1(bars: Sequence[Bar]) -> tuple[Bar, ...]:
    items = tuple(bars)
    if not items:
        raise DataError("Empty dataset")
    previous = None
    for bar in items:
        if not isinstance(bar, Bar) or bar.minutes != 1:
            raise DataError("Expected validated M1 Bar records")
        if previous is not None and bar.open_time != previous.close_time:
            raise DataError("Duplicate, unordered or missing M1 bars: split/verify sessions; never forward-fill prices")
        previous = bar
    return items


def load_csv(path: str | Path) -> tuple[Bar, ...]:
    result = []
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise DataError("Missing or duplicate CSV headers")
        if not set(COLUMNS).issubset(reader.fieldnames):
            raise DataError(f"Required CSV columns: {','.join(COLUMNS)}")
        for line, row in enumerate(reader, 2):
            try:
                if None in row:
                    raise ValueError("Unexpected extra CSV fields")
                result.append(Bar(datetime.fromisoformat(row["timestamp_open"]),
                                  *(float(row[key]) for key in COLUMNS[1:])))
            except (ValueError, TypeError, KeyError) as exc:
                raise DataError(f"CSV line {line}: {exc}") from exc
    return validate_m1(result)


def write_csv(path: str | Path, bars: Sequence[Bar]) -> None:
    bars = validate_m1(bars)
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        for bar in bars:
            writer.writerow((bar.open_time.isoformat(), bar.open, bar.high, bar.low, bar.close, bar.spread))


def resample_closed(bars: Sequence[Bar], minutes: int, as_of: datetime) -> tuple[Bar, ...]:
    """UTC epoch buckets. No partial first/last buckets. Never returns future bars.

    The aggregated spread is the maximum of source spreads, a descriptive feature,
    NOT a tick-accurate execution spread. Execution continues to use M1 only.
    """
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes not in (5, 15, 60, 240):
        raise ValueError("Supported aggregation: 5, 15, 60 or 240 minutes")
    as_of = utc(as_of)
    # Only inspect records already closed at as_of. Validate their chronology.
    closed = tuple(bar for bar in bars if bar.close_time <= as_of)
    if not closed:
        return ()
    validate_m1(closed)
    buckets: dict[datetime, list[Bar]] = defaultdict(list)
    width = minutes * 60
    for bar in closed:
        start = datetime.fromtimestamp(int(bar.open_time.timestamp()) // width * width, UTC)
        buckets[start].append(bar)
    out = []
    for start, group in sorted(buckets.items()):
        end = start + timedelta(minutes=minutes)
        if len(group) != minutes or group[0].open_time != start or group[-1].close_time != end or end > as_of:
            continue
        out.append(Bar(start, group[0].open, max(b.high for b in group),
                       min(b.low for b in group), group[-1].close,
                       max(b.spread for b in group), minutes))
    return tuple(out)


def data_fingerprint(bars: Sequence[Bar]) -> str:
    # Canonical numeric normalization makes 1 and 1.0 the same input value.
    payload = [[b.open_time.isoformat(), *(float(getattr(b, n)) for n in ("open", "high", "low", "close", "spread")), b.minutes] for b in bars]
    raw = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()
