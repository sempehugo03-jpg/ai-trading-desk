#!/usr/bin/env python3
"""Run the V0.3 research scheduler.

V0.3 intentionally ships without LLM/provider handlers. Use --smoke to prove
persistence and stage mechanics. A real handler integration is the next gate.
"""
from __future__ import annotations
import argparse
from pathlib import Path
from trading_lab.research import ContinuousResearchLoop, ResearchStore, Stage, StageOutcome


def smoke_handler(candidate, roles):
    # Infrastructure-only deterministic pass. Never interpreted as trading evidence.
    return StageOutcome(True, {"infrastructure_smoke": True}, {"roles": [r.value for r in roles]}, "SMOKE_ONLY")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="runs/research-v03.sqlite3")
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--cycles", type=int, default=10)
    args = p.parse_args()
    store = ResearchStore(Path(args.db))
    if not store.pending():
        store.add_candidate("smoke-001", "infrastructure-smoke", 1, {"not_a_strategy": True})
    if not args.smoke:
        raise SystemExit("No real agent handlers are wired yet. Run with --smoke for infrastructure verification.")
    handlers = {s: smoke_handler for s in (Stage.RESEARCH, Stage.VALIDATION, Stage.OOS, Stage.WALK_FORWARD, Stage.STRESS, Stage.BLIND, Stage.SHADOW)}
    loop = ContinuousResearchLoop(store, handlers)
    ran = loop.run_cycles(args.cycles)
    c = store.get("smoke-001")
    print({"cycles": ran, "candidate": c.candidate_id, "stage": c.stage.value, "note": "SMOKE ONLY - no profitability evidence"})

if __name__ == "__main__":
    main()
