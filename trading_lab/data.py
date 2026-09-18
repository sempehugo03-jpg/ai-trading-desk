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

BASE_COLUMNS = ("timestamp_open", "bid_open", "bid_high", "bid_low", "bid_close", "spread_price")
ASK_COLUMNS = ("ask_open", "ask_high", "ask_low", "ask_close")
OPTIONAL_COLUMNS = (*ASK_COLUMNS, "volume")
COLUMNS = BASE_COLUMNS  # backwards-compatible export name


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
        if not set(BASE_COLUMNS).issubset(reader.fieldnames):
            raise DataError(f"Required CSV columns: {','.join(BASE_COLUMNS)}")
        ask_present = [name in reader.fieldnames for name in ASK_COLUMNS]
        if any(ask_present) and not all(ask_present):
            raise DataError("ASK columns must be supplied as a complete set")
        for line, row in enumerate(reader, 2):
            try:
                if None in row:
                    raise ValueError("Unexpected extra CSV fields")
                base = [float(row[key]) for key in BASE_COLUMNS[1:]]
                kwargs = {}
                if all(ask_present):
                    kwargs.update({key: float(row[key]) for key in ASK_COLUMNS})
                if "volume" in reader.fieldnames and row.get("volume", "") != "":
                    kwargs["volume"] = float(row["volume"])
                result.append(Bar(datetime.fromisoformat(row["timestamp_open"]), *base, **kwargs))
            except (ValueError, TypeError, KeyError) as exc:
                raise DataError(f"CSV line {line}: {exc}") from exc
    return validate_m1(result)


def write_csv(path: str | Path, bars: Sequence[Bar]) -> None:
    bars = validate_m1(bars)
    exact_ask = all(bar.has_exact_ask for bar in bars)
    has_volume = all(bar.volume is not None for bar in bars)
    fields = [*BASE_COLUMNS]
    if exact_ask:
        fields.extend(ASK_COLUMNS)
    if has_volume:
        fields.append("volume")
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(fields)
        for bar in bars:
            row = [bar.open_time.isoformat(), bar.open, bar.high, bar.low, bar.close, bar.spread]
            if exact_ask:
                row.extend((bar.ask_open, bar.ask_high, bar.ask_low, bar.ask_close))
            if has_volume:
                row.append(bar.volume)
            writer.writerow(row)



def split_contiguous(bars: Sequence[Bar]) -> tuple[tuple[Bar, ...], ...]:
    """Split ordered M1 bars at any timestamp gap without inventing prices."""
    items = tuple(bars)
    if not items:
        return ()
    segments: list[list[Bar]] = [[items[0]]]
    for bar in items[1:]:
        previous = segments[-1][-1]
        if bar.open_time <= previous.open_time:
            raise DataError("Duplicate or unordered M1 bars")
        if bar.open_time == previous.close_time:
            segments[-1].append(bar)
        else:
            segments.append([bar])
    return tuple(tuple(segment) for segment in segments)


def load_csv_segments(path: str | Path) -> tuple[tuple[Bar, ...], ...]:
    """Load real data that may contain genuine market-closure gaps.

    Every returned segment is individually strict/continuous. No gap is
    forward-filled and the core backtester should run one segment at a time.
    """
    result = []
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise DataError("Missing or duplicate CSV headers")
        if not set(BASE_COLUMNS).issubset(reader.fieldnames):
            raise DataError(f"Required CSV columns: {','.join(BASE_COLUMNS)}")
        ask_present = [name in reader.fieldnames for name in ASK_COLUMNS]
        if any(ask_present) and not all(ask_present):
            raise DataError("ASK columns must be supplied as a complete set")
        for line, row in enumerate(reader, 2):
            try:
                if None in row:
                    raise ValueError("Unexpected extra CSV fields")
                base = [float(row[key]) for key in BASE_COLUMNS[1:]]
                kwargs = {}
                if all(ask_present):
                    kwargs.update({key: float(row[key]) for key in ASK_COLUMNS})
                if "volume" in reader.fieldnames and row.get("volume", "") != "":
                    kwargs["volume"] = float(row["volume"])
                result.append(Bar(datetime.fromisoformat(row["timestamp_open"]), *base, **kwargs))
            except (ValueError, TypeError, KeyError) as exc:
                raise DataError(f"CSV line {line}: {exc}") from exc
    segments = split_contiguous(result)
    if not segments:
        raise DataError("Empty dataset")
    for segment in segments:
        validate_m1(segment)
    return segments

def resample_closed(bars: Sequence[Bar], minutes: int, as_of: datetime) -> tuple[Bar, ...]:
    """UTC epoch buckets. No partial first/last buckets. Never returns future bars.

    Exact ASK OHLC is independently aggregated when present. The output spread is
    ask_open - bid_open, matching executable opening quotes.
    """
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes not in (5, 15, 60, 240):
        raise ValueError("Supported aggregation: 5, 15, 60 or 240 minutes")
    as_of = utc(as_of)
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
        exact_ask = all(b.has_exact_ask for b in group)
        kwargs = {}
        if exact_ask:
            kwargs.update(
                ask_open=group[0].ask_open,
                ask_high=max(b.ask_high for b in group if b.ask_high is not None),
                ask_low=min(b.ask_low for b in group if b.ask_low is not None),
                ask_close=group[-1].ask_close,
            )
            spread = float(kwargs["ask_open"]) - group[0].open
        else:
            spread = max(b.spread for b in group)
        volumes = [b.volume for b in group]
        if all(v is not None for v in volumes):
            kwargs["volume"] = sum(float(v) for v in volumes if v is not None)
        out.append(Bar(start, group[0].open, max(b.high for b in group),
                       min(b.low for b in group), group[-1].close,
                       spread, minutes, **kwargs))
    return tuple(out)


def data_fingerprint(bars: Sequence[Bar]) -> str:
    payload = []
    for b in bars:
        def num(value):
            return None if value is None else float(value)
        payload.append([
            b.open_time.isoformat(), num(b.open), num(b.high), num(b.low), num(b.close), num(b.spread), b.minutes,
            num(b.ask_open), num(b.ask_high), num(b.ask_low), num(b.ask_close), num(b.volume),
        ])
    raw = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()
