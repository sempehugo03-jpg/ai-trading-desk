"""Discovery Engine V2 — market-first, composable research.

No named strategy families are used. The engine measures market features,
learns empirical thresholds from early data, confirms them on a second block,
and freezes the discovered pattern before validation/OOS.
"""
from __future__ import annotations

import hashlib, json, math, sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from statistics import mean, pstdev
from typing import Mapping, Sequence

from .data import load_csv_segments, resample_closed
from .engine import backtest
from .models import Config, Side, Signal

TIMEFRAMES = (15, 60, 240)
HORIZONS = (1, 3, 6, 12)
FEATURES = (
    "ret1_atr", "ret3_atr", "trend_10_40", "dist_sma20",
    "range_atr", "body_atr", "close_location", "range_position_20",
    "atr_ratio_20_60", "upper_wick_atr", "lower_wick_atr", "spread_atr",
)

class Verdict(str, Enum):
    PASS="PASS"; PROMISING="PROMISING"; UNCERTAIN="UNCERTAIN"; REJECTED="REJECTED"

@dataclass(frozen=True)
class Condition:
    feature: str
    op: str
    threshold: float
    def __post_init__(self):
        if self.feature not in FEATURES: raise ValueError("unknown feature")
        if self.op not in ("<=", ">="): raise ValueError("bad operator")
        if not math.isfinite(float(self.threshold)): raise ValueError("non-finite threshold")
    def matches(self, row: Mapping[str,float]) -> bool:
        x=row.get(self.feature)
        if x is None or not math.isfinite(float(x)): return False
        return x <= self.threshold if self.op=="<=" else x >= self.threshold

@dataclass(frozen=True)
class Pattern:
    instrument: str
    timeframe: int
    direction: str
    horizon: int
    conditions: tuple[Condition,...]
    discovery_count: int
    discovery_mean: float
    confirm_count: int
    confirm_mean: float
    score: float
    @property
    def pattern_id(self)->str:
        raw=json.dumps({"instrument":self.instrument,"timeframe":self.timeframe,"direction":self.direction,"horizon":self.horizon,"conditions":[asdict(c) for c in self.conditions]},sort_keys=True,separators=(",",":"))
        return hashlib.sha256(raw.encode()).hexdigest()[:20]

@dataclass(frozen=True)
class StrategyV2:
    pattern_id: str
    instrument: str
    timeframe: int
    direction: str
    horizon: int
    conditions: tuple[Condition,...]
    stop_atr: float
    target_r: float
    session_start_utc: int = 0
    session_end_utc: int = 24
    def as_dict(self)->dict:
        return {"pattern_id":self.pattern_id,"instrument":self.instrument,"timeframe":self.timeframe,"direction":self.direction,"horizon":self.horizon,"conditions":[asdict(c) for c in self.conditions],"stop_atr":self.stop_atr,"target_r":self.target_r,"session_start_utc":self.session_start_utc,"session_end_utc":self.session_end_utc}
    @classmethod
    def from_mapping(cls,x:Mapping[str,object])->"StrategyV2":
        return cls(str(x["pattern_id"]),str(x["instrument"]),int(x["timeframe"]),str(x["direction"]),int(x["horizon"]),tuple(Condition(**c) for c in x["conditions"]),float(x["stop_atr"]),float(x["target_r"]),int(x.get("session_start_utc",0)),int(x.get("session_end_utc",24)))
    @property
    def fingerprint(self)->str:
        return hashlib.sha256(json.dumps(self.as_dict(),sort_keys=True,separators=(",",":")).encode()).hexdigest()

def _prefix(xs):
    out=[0.0]
    for x in xs: out.append(out[-1]+float(x))
    return out

def _avg(prefix,i,n): return (prefix[i+1]-prefix[i+1-n])/n

def _percentile(xs,q):
    ys=sorted(xs)
    if len(ys)==1:return ys[0]
    p=(len(ys)-1)*q;lo=int(math.floor(p));hi=int(math.ceil(p))
    if lo==hi:return ys[lo]
    w=p-lo;return ys[lo]*(1-w)+ys[hi]*w

def feature_rows(tf)->list[dict]:
    if len(tf)<80:return []
    close=[float(b.close) for b in tf];open_=[float(b.open) for b in tf]
    high=[float(b.high) for b in tf];low=[float(b.low) for b in tf];spread=[float(b.spread) for b in tf]
    cp=_prefix(close);tr=[0.0]*len(tf);tp=[0.0]
    for i,b in enumerate(tf):
        if i:
            prev=tf[i-1];tr[i]=max(float(b.high-b.low),abs(float(b.high-prev.close)),abs(float(b.low-prev.close)))
        tp.append(tp[-1]+tr[i])
    rows=[];max_h=max(HORIZONS)
    for i in range(60,len(tf)-max_h):
        atr20=_avg(tp,i,20);atr60=_avg(tp,i,60)
        if atr20<=0 or atr60<=0:continue
        wh=high[i-19:i+1];wl=low[i-19:i+1];hi=max(wh);lo=min(wl)
        rng=max(high[i]-low[i],1e-12);rng20=max(hi-lo,1e-12)
        feats={
            "ret1_atr":(close[i]-close[i-1])/atr20,
            "ret3_atr":(close[i]-close[i-3])/atr20,
            "trend_10_40":(_avg(cp,i,10)-_avg(cp,i,40))/atr20,
            "dist_sma20":(close[i]-_avg(cp,i,20))/atr20,
            "range_atr":(high[i]-low[i])/atr20,
            "body_atr":(close[i]-open_[i])/atr20,
            "close_location":(close[i]-low[i])/rng,
            "range_position_20":(close[i]-lo)/rng20,
            "atr_ratio_20_60":atr20/atr60,
            "upper_wick_atr":(high[i]-max(open_[i],close[i]))/atr20,
            "lower_wick_atr":(min(open_[i],close[i])-low[i])/atr20,
            "spread_atr":spread[i]/atr20,
            "_atr":atr20,"_close":close[i],
        }
        rows.append({"time":tf[i].close_time,"features":feats,"outcomes":{h:(close[i+h]-close[i])/atr20 for h in HORIZONS}})
    return rows

def market_rows(segments,timeframe,start,end):
    total=sum(len(s) for s in segments);lo,hi=int(total*start),int(total*end);cursor=0;rows=[]
    for seg in segments:
        a,b=cursor,cursor+len(seg);tl,th=max(lo,a),min(hi,b)
        if tl<th:
            part=tuple(seg[tl-a:th-a])
            if len(part)>=timeframe*100:
                rows.extend(feature_rows(resample_closed(part,timeframe,part[-1].close_time)))
        cursor=b
        if cursor>=hi:break
    rows.sort(key=lambda r:r["time"]);return rows

def _stats(rows,conds,horizon):
    vals=[r["outcomes"][horizon] for r in rows if all(c.matches(r["features"]) for c in conds)]
    if not vals:return 0,None,0.0
    m=mean(vals);sd=pstdev(vals) if len(vals)>1 else 0.0;se=sd/math.sqrt(len(vals)) if sd>0 else 0.0
    return len(vals),m,(m/se if se>0 else 0.0)

def discover_patterns(instrument,segments,timeframe,*,start=0.0,end=.40,min_count=35,top_conditions=16,top_patterns=6):
    rows=market_rows(segments,timeframe,start,end)
    if len(rows)<min_count*4:return ()
    cut=len(rows)//2;first,second=rows[:cut],rows[cut:]
    conds=[]
    for feature in FEATURES:
        vals=[float(r["features"][feature]) for r in first]
        if len(vals)<min_count*2:continue
        for q in (.10,.25,.50,.75,.90):
            th=_percentile(vals,q);conds.extend((Condition(feature,"<=",th),Condition(feature,">=",th)))
    prim=[]
    for c in conds:
        for h in HORIZONS:
            n1,m1,t1=_stats(first,(c,),h);n2,m2,t2=_stats(second,(c,),h)
            if n1<min_count or n2<min_count or m1 is None or m2 is None:continue
            if m1==0 or m2==0 or (m1>0)!=(m2>0):continue
            score=min(abs(m1),abs(m2))*math.sqrt(min(n1,n2))*min(abs(t1)+1,abs(t2)+1)
            prim.append((score,c,h,"LONG" if m1>0 else "SHORT",n1,m1,n2,m2))
    prim.sort(reverse=True,key=lambda x:x[0]);prim=prim[:top_conditions]
    found=[]
    for score,c,h,d,n1,m1,n2,m2 in prim:found.append(Pattern(instrument,timeframe,d,h,(c,),n1,m1,n2,m2,score))
    for i in range(len(prim)):
        for j in range(i+1,len(prim)):
            _,c1,h1,d1,*_=prim[i];_,c2,h2,d2,*_=prim[j]
            if h1!=h2 or d1!=d2 or c1.feature==c2.feature:continue
            n1,m1,t1=_stats(first,(c1,c2),h1);n2,m2,t2=_stats(second,(c1,c2),h1)
            if n1<min_count or n2<min_count or m1 is None or m2 is None:continue
            if m1==0 or m2==0 or (m1>0)!=(m2>0):continue
            score=min(abs(m1),abs(m2))*math.sqrt(min(n1,n2))*min(abs(t1)+1,abs(t2)+1)
            found.append(Pattern(instrument,timeframe,d1,h1,(c1,c2),n1,m1,n2,m2,score))
    dedup={}
    for p in found:
        if p.pattern_id not in dedup or p.score>dedup[p.pattern_id].score:dedup[p.pattern_id]=p
    return tuple(sorted(dedup.values(),key=lambda p:p.score,reverse=True)[:top_patterns])

def build_variants(p):
    return tuple(StrategyV2(p.pattern_id,p.instrument,p.timeframe,p.direction,p.horizon,p.conditions,s,t) for s,t in ((1.5,4.0),(1.25,1.5),(1.0,2.0)))

def compile_strategy(spec,source):
    tf=resample_closed(source,spec.timeframe,source[-1].close_time)
    if not tf:return lambda history:None
    rows=feature_rows(tf);row_by_time={r["time"]:r for r in rows};times=[b.close_time for b in tf];signals=[None]*len(tf)
    side=Side.LONG if spec.direction=="LONG" else Side.SHORT
    for i,b in enumerate(tf):
        r=row_by_time.get(b.close_time)
        if not r or not all(c.matches(r["features"]) for c in spec.conditions):continue
        atr=r["features"]["_atr"];price=r["features"]["_close"];risk=spec.stop_atr*atr
        stop,target=((price-risk,price+risk*spec.target_r) if side is Side.LONG else (price+risk,price-risk*spec.target_r))
        signals[i]=Signal(side,stop,target,spec.horizon*spec.timeframe)
    idx=-1;emitted=-1
    def strategy(history):
        nonlocal idx,emitted
        if not history:return None
        now=history[-1].close_time
        while idx+1<len(times) and times[idx+1]<=now:idx+=1
        if idx<0 or idx==emitted:return None
        sig=signals[idx]
        if sig is not None:emitted=idx
        return sig
    return strategy

def _fraction(segments,start,end):
    total=sum(len(x) for x in segments);lo,hi=int(total*start),int(total*end);cursor=0;out=[]
    for seg in segments:
        a,b=cursor,cursor+len(seg);tl,th=max(lo,a),min(hi,b)
        if tl<th:
            part=tuple(seg[tl-a:th-a])
            if len(part)>=2:out.append(part)
        cursor=b
        if cursor>=hi:break
    return tuple(out)

def _aggregate(results):
    trades=[t for r in results for t in r.trades];rs=[float(t.r_multiple) for t in trades]
    wins=sum(x for x in rs if x>0);losses=-sum(x for x in rs if x<0);eq=peak=dd=0.0
    for x in rs:eq+=x;peak=max(peak,eq);dd=max(dd,peak-eq)
    days=sum(r.observed_session_days for r in results);entries=sum(sum(e.get("kind")=="ENTRY" for e in r.events) for r in results)
    return {"closed_trades":len(trades),"expectancy_r":mean(rs) if rs else None,"profit_factor_r":wins/losses if losses else None,"max_drawdown_r":dd,"entries_per_observed_session_day":entries/days if days else None,"observed_session_days":days}

def evaluate(spec,data_root,start,end):
    segs=_fraction(load_csv_segments(Path(data_root)/spec.instrument/"m1.csv"),start,end);cfg=Config(session_start_utc=spec.session_start_utc,session_end_utc=spec.session_end_utc)
    return _aggregate([backtest(seg,compile_strategy(spec,seg),cfg,strategy_id=spec.fingerprint[:16],compact_events=True,copy_history=False) for seg in segs])

def classify(metrics,stage):
    n=int(metrics.get("closed_trades") or 0);exp=metrics.get("expectancy_r");pf=metrics.get("profit_factor_r");dd=float(metrics.get("max_drawdown_r") or 999)
    expf=float(exp) if exp is not None and math.isfinite(float(exp)) else -999;pff=float(pf) if pf is not None and math.isfinite(float(pf)) else 0
    if stage=="RESEARCH":
        if n>=20 and expf<=-.02:return Verdict.REJECTED,("CLEAR_NEGATIVE_EDGE",)
        if n>=20 and pff<.80:return Verdict.REJECTED,("VERY_LOW_PROFIT_FACTOR",)
        if dd>30:return Verdict.REJECTED,("EXTREME_DRAWDOWN",)
        if n<20 and expf>.02 and pff>=1:return Verdict.UNCERTAIN,("POSITIVE_BUT_RARE",)
        if n>=30 and expf>.02 and pff>=1.05 and dd<=15:return Verdict.PASS,()
        if n>=15 and expf>.005 and pff>=1 and dd<=20:return Verdict.PROMISING,("BORDERLINE_EVIDENCE",)
        return Verdict.REJECTED,("WEAK_RESEARCH_EVIDENCE",)
    if stage=="VALIDATION":
        if n<12 and expf>0 and pff>=1:return Verdict.UNCERTAIN,("VALIDATION_TOO_RARE",)
        if n>=15 and expf>.01 and pff>=1.02 and dd<=12:return Verdict.PASS,()
        if n>=10 and expf>0 and pff>=1 and dd<=15:return Verdict.PROMISING,("VALIDATION_BORDERLINE",)
        return Verdict.REJECTED,("VALIDATION_FAIL",)
    if stage=="OOS":
        return (Verdict.PASS,()) if (n>=12 and expf>.01 and pff>=1.02 and dd<=10) else (Verdict.REJECTED,("OOS_FAIL",))
    raise ValueError(stage)

class V2Store:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS patterns(pattern_id TEXT PRIMARY KEY,instrument TEXT,timeframe INTEGER,payload_json TEXT,score REAL,created_at TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS candidates(candidate_id TEXT PRIMARY KEY,spec_json TEXT,stage TEXT,verdict TEXT,created_at TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,candidate_id TEXT,stage TEXT,verdict TEXT,metrics_json TEXT,reason TEXT,created_at TEXT)")
    @staticmethod
    def now():return datetime.now(UTC).isoformat()
    def add_pattern(self,p):
        payload={"pattern_id":p.pattern_id,"instrument":p.instrument,"timeframe":p.timeframe,"direction":p.direction,"horizon":p.horizon,"conditions":[asdict(c) for c in p.conditions],"discovery_count":p.discovery_count,"discovery_mean":p.discovery_mean,"confirm_count":p.confirm_count,"confirm_mean":p.confirm_mean,"score":p.score}
        with sqlite3.connect(self.path) as db:db.execute("INSERT OR IGNORE INTO patterns VALUES(?,?,?,?,?,?)",(p.pattern_id,p.instrument,p.timeframe,json.dumps(payload,sort_keys=True),p.score,self.now()))
    def add_candidate(self,s):
        cid=f"v2-{s.instrument.lower()}-{s.pattern_id[:8]}-{s.fingerprint[:8]}"
        with sqlite3.connect(self.path) as db:db.execute("INSERT OR IGNORE INTO candidates VALUES(?,?,?,?,?)",(cid,json.dumps(s.as_dict(),sort_keys=True),"RESEARCH","NEW",self.now()))
        return cid
    def pending(self):
        with sqlite3.connect(self.path) as db:return db.execute("SELECT candidate_id,spec_json,stage FROM candidates WHERE stage NOT IN ('REJECTED','UNCERTAIN','BLIND_WAIT') ORDER BY created_at,candidate_id").fetchall()
    def advance(self,cid,stage,verdict,metrics,reason,next_stage):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO events(candidate_id,stage,verdict,metrics_json,reason,created_at) VALUES(?,?,?,?,?,?)",(cid,stage,verdict,json.dumps(metrics,sort_keys=True),reason,self.now()))
            db.execute("UPDATE candidates SET stage=?,verdict=? WHERE candidate_id=?",(next_stage,verdict,cid))
    def counts(self):
        with sqlite3.connect(self.path) as db:return dict(db.execute("SELECT stage,COUNT(*) FROM candidates GROUP BY stage").fetchall())
    def adaptive_memory(self):
        with sqlite3.connect(self.path) as db:return db.execute("SELECT candidate_id,stage,verdict,metrics_json,reason FROM events WHERE stage IN ('RESEARCH','VALIDATION') ORDER BY id DESC").fetchall()
