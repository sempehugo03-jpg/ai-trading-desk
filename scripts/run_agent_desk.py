#!/usr/bin/env python3
"""Start Research Desk V0.3.

Hypothesis agents run concurrently. Quantitative P&L gates remain deterministic.
No broker adapter and no live-order capability exists.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import time
from pathlib import Path

from trading_lab.agent_desk import AgentResearchDesk, DeskConfig
from trading_lab.agent_provider import OpenAIResponsesProvider
from trading_lab.research import ResearchStore


def campaign_snapshot(store: ResearchStore) -> dict:
    with sqlite3.connect(store.path) as db:
        stages = {
            row[0]: int(row[1])
            for row in db.execute(
                "SELECT stage,COUNT(*) FROM candidates GROUP BY stage ORDER BY stage"
            )
        }
        total = int(db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0])
        events = int(db.execute("SELECT COUNT(*) FROM events").fetchone()[0])
    return {"total_candidates": total, "events": events, "stages": stages}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="runs/research-desk-v03.sqlite3")
    p.add_argument("--data-root", default="data/raw")
    p.add_argument("--cycles", type=int, default=50)
    p.add_argument("--forever", action="store_true")
    p.add_argument("--batch-size", type=int, default=12)
    p.add_argument("--max-candidates", type=int, default=None)
    p.add_argument("--parallel-researchers", type=int, default=6)
    p.add_argument("--exploration-fraction", type=float, default=.70)
    p.add_argument(
        "--memory-db", action="append", default=[],
        help="Optional previous campaign DB used as non-blind research memory; repeatable",
    )
    p.add_argument("--no-llm-reviews", action="store_true")
    p.add_argument("--confirm-api-costs", action="store_true")
    args = p.parse_args()

    if not args.confirm_api_costs:
        raise SystemExit("Refusing paid agent calls without --confirm-api-costs")
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not configured")
    if args.max_candidates is not None and args.max_candidates < 1:
        raise SystemExit("--max-candidates must be >= 1")
    if args.parallel_researchers < 1:
        raise SystemExit("--parallel-researchers must be >= 1")
    if not 0 <= args.exploration_fraction <= 1:
        raise SystemExit("--exploration-fraction must be 0..1")

    store = ResearchStore(Path(args.db))
    provider = OpenAIResponsesProvider()
    cfg = DeskConfig(
        data_root=args.data_root,
        proposal_batch_size=args.batch_size,
        use_llm_reviews=not args.no_llm_reviews,
        total_candidate_cap=args.max_candidates,
        parallel_researchers=args.parallel_researchers,
        exploration_fraction=args.exploration_fraction,
        memory_db_paths=tuple(args.memory_db),
    )
    desk = AgentResearchDesk(store, provider, cfg)

    started = time.monotonic()
    if args.forever:
        print({"mode": "forever", "initial": campaign_snapshot(store)}, flush=True)
        desk.run_forever()
        return

    ran = 0
    try:
        for _ in range(args.cycles):
            if not desk.step():
                break
            ran += 1
            print({
                "cycle": ran,
                "elapsed_s": round(time.monotonic() - started, 1),
                **campaign_snapshot(store),
                "api_calls": provider.calls,
                "api_input_tokens": provider.input_tokens,
                "api_output_tokens": provider.output_tokens,
            }, flush=True)
    except KeyboardInterrupt:
        print("Interrupted by operator; campaign state is persisted.", flush=True)

    print({
        "cycles": ran,
        "elapsed_s": round(time.monotonic() - started, 1),
        **campaign_snapshot(store),
        "api_calls": provider.calls,
        "api_input_tokens": provider.input_tokens,
        "api_output_tokens": provider.output_tokens,
        "pending": len(store.pending()),
    }, flush=True)


if __name__ == "__main__":
    main()
