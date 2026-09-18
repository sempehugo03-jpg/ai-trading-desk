#!/usr/bin/env python3
"""Start Research Desk V0.1.

This process performs research only. It has no broker adapter and cannot place live orders.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from trading_lab.agent_desk import AgentResearchDesk, DeskConfig
from trading_lab.agent_provider import OpenAIResponsesProvider
from trading_lab.research import ResearchStore


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="runs/research-desk-v01.sqlite3")
    p.add_argument("--data-root", default="data/raw")
    p.add_argument("--cycles", type=int, default=20)
    p.add_argument("--forever", action="store_true")
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--no-llm-reviews", action="store_true")
    p.add_argument("--confirm-api-costs", action="store_true", help="Required before paid OpenAI API calls")
    args = p.parse_args()
    if not args.confirm_api_costs:
        raise SystemExit("Refusing paid agent calls without --confirm-api-costs")
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not configured")
    store = ResearchStore(Path(args.db))
    provider = OpenAIResponsesProvider()
    cfg = DeskConfig(data_root=args.data_root, proposal_batch_size=args.batch_size, use_llm_reviews=not args.no_llm_reviews)
    desk = AgentResearchDesk(store, provider, cfg)
    if args.forever:
        desk.run_forever()
    else:
        print({"cycles": desk.run_cycles(args.cycles), "pending": len(store.pending())})


if __name__ == "__main__":
    main()
