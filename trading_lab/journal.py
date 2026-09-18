"""Single-writer hash-chained JSONL audit log, NOT an immutable/WORM store."""
from __future__ import annotations
import hashlib
import json
import os
from datetime import datetime
from enum import Enum
from pathlib import Path
from .models import utc


def _encode(value):
    if isinstance(value, datetime):
        return utc(value).isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Unsupported journal value: {type(value).__name__}")


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False, default=_encode)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


class HashJournal:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.verify()

    def verify(self, expected_head: str | None = None) -> tuple[int, str]:
        count, head = 0, "GENESIS"
        if self.path.exists():
            with self.path.open(encoding="utf-8") as handle:
                for line in handle:
                    try:
                        row = json.loads(line, object_pairs_hook=_unique_pairs)
                        if not line.endswith("\n") or set(row) != {"seq", "previous_hash", "event", "hash"}:
                            raise ValueError("Invalid or incomplete record")
                        body = {k: row[k] for k in ("seq", "previous_hash", "event")}
                        if row["seq"] != count or row["previous_hash"] != head or row["hash"] != digest(body):
                            raise ValueError("Journal chain mismatch")
                        head = row["hash"]
                        count += 1
                    except (ValueError, KeyError, TypeError) as exc:
                        raise ValueError(f"Journal integrity failure at record {count}") from exc
        if expected_head is not None and head != expected_head:
            raise ValueError("Journal head does not match the externally retained checkpoint")
        return count, head

    def append(self, event: dict) -> str:
        if not isinstance(event, dict):
            raise TypeError("Journal event must be a dict")
        # A lock file prevents cooperative simultaneous writers. No stale-lock override.
        lock = self.path.with_suffix(self.path.suffix + ".lock")
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise RuntimeError("Journal busy or stale lock; investigate before continuing") from exc
        try:
            os.close(fd)
            count, previous = self.verify()
            body = {"seq": count, "previous_hash": previous, "event": event}
            head = digest(body)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(canonical({**body, "hash": head}) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            return head
        finally:
            lock.unlink()
