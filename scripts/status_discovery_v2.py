#!/usr/bin/env python3
import argparse,sqlite3,json
p=argparse.ArgumentParser();p.add_argument("--db",default="runs/discovery-v2-001.sqlite3");a=p.parse_args();db=sqlite3.connect(a.db)
print("=== ETAPES ===")
for s,n in db.execute("SELECT stage,COUNT(*) FROM candidates GROUP BY stage ORDER BY stage"):print(s,":",n)
print("\n=== VERDICTS ===")
for v,n in db.execute("SELECT verdict,COUNT(*) FROM candidates GROUP BY verdict ORDER BY verdict"):print(v,":",n)
print("\n=== TOP PATTERNS ===")
for payload, in db.execute("SELECT payload_json FROM patterns ORDER BY score DESC LIMIT 15"):
    x=json.loads(payload);print(x["instrument"],x["timeframe"],"min",x["direction"],"h",x["horizon"],"score",round(x["score"],3),x["conditions"])
print("\nMémoire adaptative = RESEARCH + VALIDATION uniquement. OOS est exclu.")
