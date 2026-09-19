#!/usr/bin/env python3
"""Desk V1 finite campaign runner."""
from __future__ import annotations
import argparse, os, sqlite3, time
from pathlib import Path
from trading_lab.agent_provider import OpenAIResponsesProvider
from trading_lab.desk_v1 import DeskV1
from trading_lab.research import ResearchStore


def snap(store):
    with sqlite3.connect(store.path) as db:
        stages={r[0]:int(r[1]) for r in db.execute("SELECT stage,COUNT(*) FROM candidates GROUP BY stage")}
        return {"total":int(db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]),"stages":stages}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--db",default="runs/desk-v1-campaign-001.sqlite3")
    p.add_argument("--cycles",type=int,default=300)
    p.add_argument("--batch-size",type=int,default=12)
    p.add_argument("--max-candidates",type=int,default=100)
    p.add_argument("--parallel-researchers",type=int,default=8)
    p.add_argument("--data-root",default="data/raw")
    p.add_argument("--confirm-api-costs",action="store_true")
    a=p.parse_args()
    if not a.confirm_api_costs: raise SystemExit("Use --confirm-api-costs")
    if not os.getenv("OPENAI_API_KEY"): raise SystemExit("OPENAI_API_KEY missing")
    store=ResearchStore(Path(a.db)); provider=OpenAIResponsesProvider()
    desk=DeskV1(store,provider,data_root=a.data_root,workers=a.parallel_researchers,total_cap=a.max_candidates)
    started=time.monotonic(); ran=0
    for _ in range(a.cycles):
        if not desk.step(a.batch_size): break
        ran+=1
        print({"cycle":ran,"elapsed_s":round(time.monotonic()-started,1),**snap(store),
               "api_calls":provider.calls,"api_input_tokens":provider.input_tokens,
               "api_output_tokens":provider.output_tokens},flush=True)
    print({"cycles":ran,**snap(store),"pending":len(store.pending()),
           "api_calls":provider.calls,"api_input_tokens":provider.input_tokens,
           "api_output_tokens":provider.output_tokens},flush=True)

if __name__=="__main__": main()
