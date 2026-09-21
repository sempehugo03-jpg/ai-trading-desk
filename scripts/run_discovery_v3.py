#!/usr/bin/env python3
import argparse,time
from trading_lab.discovery_v3 import V3Store
from trading_lab.discovery_runner_v3 import DiscoveryDeskV3
p=argparse.ArgumentParser();p.add_argument("--db",default="runs/discovery-v3-001.sqlite3");p.add_argument("--data-root",default="data/raw");p.add_argument("--trials-per-market",type=int,default=300);p.add_argument("--max-depth",type=int,default=3);p.add_argument("--max-rules",type=int,default=3);p.add_argument("--patterns-per-market",type=int,default=5);p.add_argument("--max-candidates",type=int,default=300);p.add_argument("--cycles",type=int,default=1000);p.add_argument("--seed",type=int,default=7);p.add_argument("--context-width",type=int,default=4);p.add_argument("--forever",action="store_true");a=p.parse_args()
store=V3Store(a.db);desk=DiscoveryDeskV3(store,data_root=a.data_root);start=time.monotonic();steps=0
while True:
    if not store.pending():
        created=desk.search_once(trials_per_market=a.trials_per_market,max_depth=a.max_depth,max_rules=a.max_rules,patterns_per_market=a.patterns_per_market,candidate_cap=a.max_candidates,seed=a.seed,context_width=a.context_width);print({"phase":"SEARCH","created":created,"trials":store.trial_count(),"stages":store.counts()},flush=True)
        if created==0 and not a.forever:break
    for _ in range(a.cycles):
        if not desk.step():break
        steps+=1
        if steps%5==0:print({"steps":steps,"elapsed_s":round(time.monotonic()-start,1),"trials":store.trial_count(),"stages":store.counts()},flush=True)
    if not a.forever:break
    a.max_candidates+=max(50,a.patterns_per_market*10)
print({"steps":steps,"elapsed_s":round(time.monotonic()-start,1),"trials":store.trial_count(),"stages":store.counts()},flush=True)
