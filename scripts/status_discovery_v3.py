#!/usr/bin/env python3
import argparse,sqlite3,json
p=argparse.ArgumentParser();p.add_argument("--db",default="runs/discovery-v3-001.sqlite3");a=p.parse_args();db=sqlite3.connect(a.db)
print("=== ETAPES ===")
for s,n in db.execute("SELECT stage,COUNT(*) FROM candidates GROUP BY stage ORDER BY stage"):print(s,":",n)
print("\n=== VERDICTS ===")
for v,n in db.execute("SELECT verdict,COUNT(*) FROM candidates GROUP BY verdict ORDER BY verdict"):print(v,":",n)
print("\n=== RECHERCHE ===")
print("Programmes symboliques testés :",db.execute("SELECT COALESCE(SUM(trials),0) FROM search_runs").fetchone()[0]);print("Patterns :",db.execute("SELECT COUNT(*) FROM patterns").fetchone()[0]);print("Candidats :",db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]);print("Evénements :",db.execute("SELECT COUNT(*) FROM events").fetchone()[0]);print("OOS1 :",db.execute("SELECT COUNT(*) FROM events WHERE stage='OOS1'").fetchone()[0]);print("OOS2 :",db.execute("SELECT COUNT(*) FROM events WHERE stage='OOS2'").fetchone()[0]);print("Blind wait :",db.execute("SELECT COUNT(*) FROM candidates WHERE stage='BLIND_WAIT'").fetchone()[0])
print("\n=== TOP PATTERNS ===")
for payload in db.execute("SELECT payload_json FROM patterns ORDER BY score DESC LIMIT 10"):
    x=json.loads(payload[0]);print(x["target"],x["timeframe"],"min",x["direction"],"h",x["horizon"],"score",round(x["score"],3),"rules",len(x["rules"]))
print("\nMémoire adaptative : RESEARCH + VALIDATION uniquement. OOS1/OOS2 exclus.")
