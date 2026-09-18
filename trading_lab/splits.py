"""Chronological holdout and walk-forward utilities. Never randomize time series."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence
from .models import Bar, DataError, utc

@dataclass(frozen=True)
class TimeSplit:
    name: str
    start: datetime
    end: datetime
    bars: tuple[Bar, ...]


def chronological_holdout(bars: Sequence[Bar], *, train: float = 0.60,
                          validation: float = 0.20) -> tuple[TimeSplit, TimeSplit, TimeSplit]:
    items = tuple(bars)
    if len(items) < 10:
        raise DataError("At least 10 bars required for a chronological split")
    if not (0 < train < 1 and 0 < validation < 1 and train + validation < 1):
        raise ValueError("Require positive train/validation fractions summing to less than 1")
    # Boundaries use counts but are reported with explicit UTC timestamps.
    i = max(1, min(len(items)-2, int(len(items) * train)))
    j = max(i+1, min(len(items)-1, int(len(items) * (train + validation))))
    groups = (("IS", items[:i]), ("VALIDATION", items[i:j]), ("OOS", items[j:]))
    return tuple(TimeSplit(name, part[0].open_time, part[-1].close_time, tuple(part)) for name, part in groups)  # type: ignore[return-value]


def slice_time(bars: Sequence[Bar], start: datetime, end: datetime) -> tuple[Bar, ...]:
    start, end = utc(start), utc(end)
    if start >= end:
        raise ValueError("start must be before end")
    return tuple(b for b in bars if start <= b.open_time and b.close_time <= end)


def walk_forward_windows(bars: Sequence[Bar], *, train_days: int = 180,
                         test_days: int = 30, step_days: int = 30):
    items = tuple(bars)
    if not items:
        raise DataError("Empty dataset")
    if min(train_days, test_days, step_days) < 1:
        raise ValueError("Window sizes must be positive")
    cursor = items[0].open_time
    last = items[-1].close_time
    while cursor + timedelta(days=train_days + test_days) <= last:
        train_end = cursor + timedelta(days=train_days)
        test_end = train_end + timedelta(days=test_days)
        train = slice_time(items, cursor, train_end)
        test = slice_time(items, train_end, test_end)
        if train and test:
            yield (TimeSplit("WF_TRAIN", cursor, train_end, train),
                   TimeSplit("WF_TEST", train_end, test_end, test))
        cursor += timedelta(days=step_days)
