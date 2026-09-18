#!/usr/bin/env python3
"""Start Research Desk V0.2.

Research only: no broker adapter, no live orders. Finite campaigns can be capped
at an exact total number of candidates and print progress after every completed
stage so a long Codespace run never appears frozen.
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
        stages = {row[0]: int(row[1]) for row in db.execute(
            "SELECT stage,COUNT(*) FROM candidates GROUP BY stage ORDER BY stage"
        )}
        total = int(db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0])
        events = int(db.execute("SELECT COUNT(*) FROM events").fetchone()[0])
    return {"total_candidates": total, "events": events, "stages": stages}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="runs/research-desk-v01.sqlite3")
    p.add_argument("--data-root", default="data/raw")
    p.add_argument("--cycles", type=int, default=20)
    p.add_argument("--forever", action="store_true")
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--max-candidates", type=int, default=None,
                   help="Hard cap on total candidates in this campaign DB")
    p.add_argument("--no-llm-reviews", action="store_true")
    p.add_argument("--confirm-api-costs", action="store_true", help="Required before paid OpenAI API calls")
    args = p.parse_args()
    if not args.confirm_api_costs:
        raise SystemExit("Refusing paid agent calls without --confirm-api-costs")
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not configured")
    if args.max_candidates is not None and args.max_candidates < 1:
        raise SystemExit("--max-candidates must be >= 1")

    store = ResearchStore(Path(args.db))
    provider = OpenAIResponsesProvider()
    cfg = DeskConfig(
        data_root=args.data_root,
        proposal_batch_size=args.batch_size,
        use_llm_reviews=not args.no_llm_reviews,
        total_candidate_cap=args.max_candidates,
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
            snap = campaign_snapshot(store)
            print({
                "cycle": ran,
                "elapsed_s": round(time.monotonic() - started, 1),
                **snap,
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
