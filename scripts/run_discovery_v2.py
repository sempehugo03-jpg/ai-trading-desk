#!/usr/bin/env python3
import argparse,time
from pathlib import Path
from trading_lab.discovery_v2 import V2Store
from trading_lab.discovery_runner_v2 import DiscoveryDeskV2

SUPPORTED=("XAUUSD","XAGUSD","EURUSD","GBPUSD","USDJPY","AUDUSD","USDCAD","NAS100","US500","US30","DAX","WTI","BRENT")
p=argparse.ArgumentParser();p.add_argument("--db",default="runs/discovery-v2-001.sqlite3");p.add_argument("--data-root",default="data/raw");p.add_argument("--patterns-per-tf",type=int,default=5);p.add_argument("--max-candidates",type=int,default=150);p.add_argument("--cycles",type=int,default=500);a=p.parse_args()
store=V2Store(a.db);desk=DiscoveryDeskV2(store,data_root=a.data_root);syms=tuple(x for x in SUPPORTED if (Path(a.data_root)/x/"m1.csv").exists())
if sum(store.counts().values())==0:
    print({"phase":"DISCOVERY","instruments":syms},flush=True);n=desk.discover(syms,a.patterns_per_tf,a.max_candidates);print({"phase":"DISCOVERY_DONE","created":n,"stages":store.counts()},flush=True)
start=time.monotonic();ran=0
for _ in range(a.cycles):
    if not desk.step():break
    ran+=1
    if ran%5==0:print({"cycle":ran,"elapsed_s":round(time.monotonic()-start,1),"stages":store.counts()},flush=True)
print({"cycles":ran,"elapsed_s":round(time.monotonic()-start,1),"stages":store.counts()},flush=True)
