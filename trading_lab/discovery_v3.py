"""Discovery Engine V3 — open symbolic market search.

No named strategy-family catalogue. The engine searches generic mathematical
programs over target/cross-asset observations, then applies progressive evidence
gates. OOS1/OOS2 never feed adaptive research. No live execution.
"""
from __future__ import annotations
import hashlib, json, math, random, sqlite3
from dataclasses import dataclass, asdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, pstdev
from typing import Mapping, Sequence

from .data import load_csv_segments, resample_closed
from .engine import backtest
from .models import Config, Side, Signal

BASE_FEATURES=(
    "ret1_atr","ret3_atr","ret12_atr","trend_10_40","trend_20_80",
    "dist_sma20","dist_sma50","range_atr","body_atr","close_location",
    "range_position_20","atr_ratio_20_60","upper_wick_atr","lower_wick_atr",
    "spread_atr","hour_sin","hour_cos","dow_sin","dow_cos",
)
TIMEFRAMES=(15,60,240)
HORIZONS=(1,3,6,12,24)
UNARY_OPS=("abs","neg","square","signed_sqrt")
BINARY_OPS=("add","sub","mul","safe_div","min","max")

class Verdict:
    PASS="PASS"; PROMISING="PROMISING"; UNCERTAIN="UNCERTAIN"; REJECTED="REJECTED"

@dataclass(frozen=True)
class Expr:
    op:str
    value:str|float|None=None
    args:tuple["Expr",...]=()
    def __post_init__(self):
        if self.op not in {"feature","const",*UNARY_OPS,*BINARY_OPS}: raise ValueError("bad op")
        if self.op=="feature" and not isinstance(self.value,str): raise ValueError("feature name required")
        if self.op=="const" and not isinstance(self.value,(int,float)): raise ValueError("const number required")
        if self.op in UNARY_OPS and len(self.args)!=1: raise ValueError("unary arity")
        if self.op in BINARY_OPS and len(self.args)!=2: raise ValueError("binary arity")
    def as_dict(self): return {"op":self.op,"value":self.value,"args":[a.as_dict() for a in self.args]}
    @classmethod
    def from_mapping(cls,x): return cls(str(x["op"]),x.get("value"),tuple(cls.from_mapping(a) for a in x.get("args",[])))
    def features(self):
        if self.op=="feature": return {str(self.value)}
        out=set()
        for a in self.args: out|=a.features()
        return out
    def eval(self,row:Mapping[str,float]):
        try:
            if self.op=="feature":
                x=row.get(str(self.value)); return float(x) if x is not None and math.isfinite(float(x)) else None
            if self.op=="const": return float(self.value)
            vals=[a.eval(row) for a in self.args]
            if any(v is None for v in vals): return None
            if self.op=="abs": return abs(vals[0])
            if self.op=="neg": return -vals[0]
            if self.op=="square": return vals[0]*vals[0]
            if self.op=="signed_sqrt": return math.copysign(math.sqrt(abs(vals[0])),vals[0])
            a,b=vals
            if self.op=="add": return a+b
            if self.op=="sub": return a-b
            if self.op=="mul": return a*b
            if self.op=="safe_div": return a/b if abs(b)>1e-9 else 0.0
            if self.op=="min": return min(a,b)
            if self.op=="max": return max(a,b)
        except (OverflowError,ValueError,ZeroDivisionError): return None
        return None

@dataclass(frozen=True)
class Rule:
    expr:Expr
    op:str
    threshold:float
    def matches(self,row):
        x=self.expr.eval(row)
        if x is None:return False
        return x<=self.threshold if self.op=="<=" else x>=self.threshold
    def as_dict(self): return {"expr":self.expr.as_dict(),"op":self.op,"threshold":self.threshold}
    @classmethod
    def from_mapping(cls,x): return cls(Expr.from_mapping(x["expr"]),str(x["op"]),float(x["threshold"]))

@dataclass(frozen=True)
class SymbolicPattern:
    target:str; timeframe:int; direction:str; horizon:int; rules:tuple[Rule,...]
    discovery_count:int; confirm_count:int; discovery_mean:float; confirm_mean:float
    p_discovery:float; p_confirm:float; trial_number:int; score:float
    @property
    def pattern_id(self):
        raw=json.dumps({"target":self.target,"timeframe":self.timeframe,"direction":self.direction,"horizon":self.horizon,"rules":[r.as_dict() for r in self.rules]},sort_keys=True,separators=(",",":"))
        return hashlib.sha256(raw.encode()).hexdigest()[:24]
    def as_dict(self):
        d=asdict(self); d["rules"]=[r.as_dict() for r in self.rules]; d["pattern_id"]=self.pattern_id; return d

@dataclass(frozen=True)
class StrategyV3:
    pattern_id:str; target:str; timeframe:int; direction:str; horizon:int; rules:tuple[Rule,...]
    stop_atr:float; target_r:float; session_start_utc:int=0; session_end_utc:int=24
    def as_dict(self): return {"pattern_id":self.pattern_id,"target":self.target,"timeframe":self.timeframe,"direction":self.direction,"horizon":self.horizon,"rules":[r.as_dict() for r in self.rules],"stop_atr":self.stop_atr,"target_r":self.target_r,"session_start_utc":self.session_start_utc,"session_end_utc":self.session_end_utc}
    @classmethod
    def from_mapping(cls,x): return cls(str(x["pattern_id"]),str(x["target"]),int(x["timeframe"]),str(x["direction"]),int(x["horizon"]),tuple(Rule.from_mapping(r) for r in x["rules"]),float(x["stop_atr"]),float(x["target_r"]),int(x.get("session_start_utc",0)),int(x.get("session_end_utc",24)))
    @property
    def fingerprint(self): return hashlib.sha256(json.dumps(self.as_dict(),sort_keys=True,separators=(",",":")).encode()).hexdigest()

def _prefix(xs):
    out=[0.0]
    for x in xs: out.append(out[-1]+float(x))
    return out

def _avg(p,i,n): return (p[i+1]-p[i+1-n])/n

def feature_rows(tf):
    if len(tf)<110:return []
    c=[float(b.close) for b in tf];o=[float(b.open) for b in tf];h=[float(b.high) for b in tf];l=[float(b.low) for b in tf];sp=[float(b.spread) for b in tf]
    cp=_prefix(c);tr=[0.0]*len(tf);tp=[0.0]
    for i,b in enumerate(tf):
        if i:
            prev=tf[i-1];tr[i]=max(float(b.high-b.low),abs(float(b.high-prev.close)),abs(float(b.low-prev.close)))
        tp.append(tp[-1]+tr[i])
    rows=[];mh=max(HORIZONS)
    for i in range(80,len(tf)-mh):
        a20=_avg(tp,i,20);a60=_avg(tp,i,60)
        if a20<=0 or a60<=0:continue
        hi=max(h[i-19:i+1]);lo=min(l[i-19:i+1]);rng=max(h[i]-l[i],1e-12);rng20=max(hi-lo,1e-12)
        t=tf[i].close_time;hour=t.hour+t.minute/60;dow=t.weekday()
        feats={
            "ret1_atr":(c[i]-c[i-1])/a20,"ret3_atr":(c[i]-c[i-3])/a20,"ret12_atr":(c[i]-c[i-12])/a20,
            "trend_10_40":(_avg(cp,i,10)-_avg(cp,i,40))/a20,"trend_20_80":(_avg(cp,i,20)-_avg(cp,i,80))/a20,
            "dist_sma20":(c[i]-_avg(cp,i,20))/a20,"dist_sma50":(c[i]-_avg(cp,i,50))/a20,
            "range_atr":(h[i]-l[i])/a20,"body_atr":(c[i]-o[i])/a20,"close_location":(c[i]-l[i])/rng,
            "range_position_20":(c[i]-lo)/rng20,"atr_ratio_20_60":a20/a60,
            "upper_wick_atr":(h[i]-max(o[i],c[i]))/a20,"lower_wick_atr":(min(o[i],c[i])-l[i])/a20,"spread_atr":sp[i]/a20,
            "hour_sin":math.sin(2*math.pi*hour/24),"hour_cos":math.cos(2*math.pi*hour/24),"dow_sin":math.sin(2*math.pi*dow/5),"dow_cos":math.cos(2*math.pi*dow/5),
            "_atr":a20,"_close":c[i],
        }
        rows.append({"time":t,"features":feats,"outcomes":{hz:(c[i+hz]-c[i])/a20 for hz in HORIZONS}})
    return rows

def _fraction_segments(path,start,end):
    segs=load_csv_segments(path);total=sum(len(s) for s in segs);lo,hi=int(total*start),int(total*end);cursor=0;out=[]
    for seg in segs:
        a,b=cursor,cursor+len(seg);tl,th=max(lo,a),min(hi,b)
        if tl<th:
            part=tuple(seg[tl-a:th-a])
            if len(part)>=2:out.append(part)
        cursor=b
        if cursor>=hi:break
    return tuple(out)

def market_feature_map(path,timeframe,start,end):
    out={}
    for seg in _fraction_segments(path,start,end):
        if len(seg)<timeframe*120:continue
        tf=resample_closed(seg,timeframe,seg[-1].close_time)
        for r in feature_rows(tf):out[r["time"]]=r
    return out

def joined_rows(data_root,target,contexts,timeframe,start,end):
    root=Path(data_root);tm=market_feature_map(root/target/"m1.csv",timeframe,start,end)
    cms={s:market_feature_map(root/s/"m1.csv",timeframe,start,end) for s in contexts if s!=target and (root/s/"m1.csv").exists()}
    rows=[]
    for t,r in tm.items():
        f={f"self.{k}":v for k,v in r["features"].items() if not k.startswith("_")}
        for s,cm in cms.items():
            cr=cm.get(t)
            if cr:
                for k,v in cr["features"].items():
                    if not k.startswith("_"):f[f"{s}.{k}"]=v
        rows.append({"time":t,"features":f,"outcomes":r["outcomes"],"_atr":r["features"]["_atr"],"_close":r["features"]["_close"]})
    rows.sort(key=lambda x:x["time"]);return rows

def random_expr(rng,features,depth):
    if depth<=0 or rng.random()<.40:
        return Expr("feature",rng.choice(features)) if rng.random()<.93 else Expr("const",rng.choice((-2.,-1.,-.5,.5,1.,2.)))
    if rng.random()<.30:return Expr(rng.choice(UNARY_OPS),args=(random_expr(rng,features,depth-1),))
    return Expr(rng.choice(BINARY_OPS),args=(random_expr(rng,features,depth-1),random_expr(rng,features,depth-1)))

def mutate_expr(rng,e,features,depth):
    if depth<=0 or rng.random()<.25:return random_expr(rng,features,max(0,depth))
    if e.op=="feature":return Expr("feature",rng.choice(features))
    if e.op=="const":return Expr("const",float(e.value)*rng.choice((.5,.8,1.2,2.0)))
    args=list(e.args);i=rng.randrange(len(args));args[i]=mutate_expr(rng,args[i],features,depth-1);return Expr(e.op,e.value,tuple(args))

def _percentile(xs,q):
    ys=sorted(xs);p=(len(ys)-1)*q;lo=int(math.floor(p));hi=int(math.ceil(p))
    if lo==hi:return ys[lo]
    w=p-lo;return ys[lo]*(1-w)+ys[hi]*w

def _p(t):return math.erfc(abs(t)/math.sqrt(2))

def _stats(rows,rules,hz):
    vals=[r["outcomes"][hz] for r in rows if all(rule.matches(r["features"]) for rule in rules)]
    if not vals:return 0,None,1.0,0.0
    m=mean(vals);sd=pstdev(vals) if len(vals)>1 else 0.;se=sd/math.sqrt(len(vals)) if sd>0 else 0.;t=m/se if se>0 else 0.
    return len(vals),m,_p(t),t

def mine_symbolic_patterns(*,data_root,target,contexts,timeframe,trials,max_depth,max_rules,seed,min_count=30,top_k=10):
    a=joined_rows(data_root,target,contexts,timeframe,0,.225);b=joined_rows(data_root,target,contexts,timeframe,.225,.45)
    if len(a)<min_count*4 or len(b)<min_count*4:return ()
    features=sorted(set().union(*(r["features"].keys() for r in a)));rng=random.Random(seed);elites=[];found={}
    for trial in range(1,trials+1):
        expr=mutate_expr(rng,rng.choice(elites),features,max_depth) if elites and rng.random()<.55 else random_expr(rng,features,max_depth)
        exprs=[expr]+[random_expr(rng,features,max_depth) for _ in range(rng.randint(0,max(0,max_rules-1)))]
        rules=[]
        for ex in exprs:
            xs=[x for r in a if (x:=ex.eval(r["features"])) is not None and math.isfinite(x)]
            if len(xs)<min_count*2:break
            q=rng.choice((.10,.20,.30,.50,.70,.80,.90));rules.append(Rule(ex,"<=" if q<=.5 else ">=",_percentile(xs,q)))
        if len(rules)!=len(exprs):continue
        for hz in HORIZONS:
            n1,m1,p1,t1=_stats(a,rules,hz);n2,m2,p2,t2=_stats(b,rules,hz)
            if n1<min_count or n2<min_count or m1 is None or m2 is None or m1==0 or m2==0 or (m1>0)!=(m2>0):continue
            alpha=min(.20,.05*math.sqrt(max(1,1000/max(trials,1))))
            if max(p1,p2)>alpha:continue
            score=min(abs(m1),abs(m2))*math.sqrt(min(n1,n2))*min(abs(t1)+1,abs(t2)+1)/(1+.20*(len(rules)-1)+.08*max_depth)
            pat=SymbolicPattern(target,timeframe,"LONG" if m1>0 else "SHORT",hz,tuple(rules),n1,n2,m1,m2,p1,p2,trial,score)
            if pat.pattern_id not in found or score>found[pat.pattern_id].score:found[pat.pattern_id]=pat
        if found and trial%max(10,trials//20)==0:elites=[r.expr for p in sorted(found.values(),key=lambda x:x.score,reverse=True)[:20] for r in p.rules]
    return tuple(sorted(found.values(),key=lambda x:x.score,reverse=True)[:top_k])

def strategy_variants(p):return tuple(StrategyV3(p.pattern_id,p.target,p.timeframe,p.direction,p.horizon,p.rules,s,t) for s,t in ((1.,2.),(1.25,2.5),(1.5,4.)))

def _joined_eval(data_root,spec,start,end):
    needed=set().union(*(r.expr.features() for r in spec.rules));contexts=sorted({x.split('.',1)[0] for x in needed if '.' in x and not x.startswith('self.')})
    rows=joined_rows(data_root,spec.target,contexts,spec.timeframe,start,end);return {r["time"]:r for r in rows}

def compile_strategy(spec,target_segment,jmap):
    tf=resample_closed(target_segment,spec.timeframe,target_segment[-1].close_time);times=[b.close_time for b in tf];signals=[None]*len(tf);side=Side.LONG if spec.direction=="LONG" else Side.SHORT
    for i,b in enumerate(tf):
        row=jmap.get(b.close_time)
        if not row or not all(rule.matches(row["features"]) for rule in spec.rules):continue
        price=row["_close"];risk=spec.stop_atr*row["_atr"]
        stop,target=((price-risk,price+risk*spec.target_r) if side is Side.LONG else (price+risk,price-risk*spec.target_r));signals[i]=Signal(side,stop,target,spec.horizon*spec.timeframe)
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

def _aggregate(results):
    trades=[t for r in results for t in r.trades];rs=[float(t.r_multiple) for t in trades];wins=sum(x for x in rs if x>0);losses=-sum(x for x in rs if x<0);eq=peak=dd=0.
    for x in rs:eq+=x;peak=max(peak,eq);dd=max(dd,peak-eq)
    days=sum(r.observed_session_days for r in results);entries=sum(sum(e.get("kind")=="ENTRY" for e in r.events) for r in results)
    return {"closed_trades":len(trades),"expectancy_r":mean(rs) if rs else None,"profit_factor_r":wins/losses if losses else None,"max_drawdown_r":dd,"entries_per_observed_session_day":entries/days if days else None,"observed_session_days":days}

def evaluate_strategy(spec,data_root,start,end):
    parts=_fraction_segments(Path(data_root)/spec.target/"m1.csv",start,end);jmap=_joined_eval(data_root,spec,start,end);cfg=Config(session_start_utc=spec.session_start_utc,session_end_utc=spec.session_end_utc)
    return _aggregate([backtest(seg,compile_strategy(spec,seg,jmap),cfg,strategy_id=spec.fingerprint[:16],compact_events=True,copy_history=False) for seg in parts])

def classify(metrics,stage):
    n=int(metrics.get("closed_trades") or 0);exp=metrics.get("expectancy_r");pf=metrics.get("profit_factor_r");dd=float(metrics.get("max_drawdown_r") or 999);expf=float(exp) if exp is not None and math.isfinite(float(exp)) else -999;pff=float(pf) if pf is not None and math.isfinite(float(pf)) else 0.
    if stage=="RESEARCH":
        if n>=20 and expf<=-.02:return Verdict.REJECTED,("CLEAR_NEGATIVE_EDGE",)
        if dd>35:return Verdict.REJECTED,("EXTREME_DRAWDOWN",)
        if n<20 and expf>.02 and pff>=1:return Verdict.UNCERTAIN,("POSITIVE_BUT_LOW_SAMPLE",)
        if n>=30 and expf>.015 and pff>=1.03 and dd<=18:return Verdict.PASS,()
        if n>=12 and expf>0 and pff>=1 and dd<=22:return Verdict.PROMISING,("BORDERLINE_EVIDENCE",)
        return Verdict.REJECTED,("WEAK_RESEARCH_EVIDENCE",)
    if stage=="VALIDATION":
        if n<10 and expf>0 and pff>=1:return Verdict.UNCERTAIN,("LOW_SAMPLE_VALIDATION",)
        if n>=12 and expf>.005 and pff>=1.01 and dd<=15:return Verdict.PASS,()
        if n>=8 and expf>0 and pff>=1 and dd<=18:return Verdict.PROMISING,("BORDERLINE_VALIDATION",)
        return Verdict.REJECTED,("VALIDATION_FAIL",)
    if stage in ("OOS1","OOS2"):
        if n>=10 and expf>.005 and pff>=1.01 and dd<=12:return Verdict.PASS,()
        if n<10 and expf>0 and pff>=1:return Verdict.UNCERTAIN,("LOW_SAMPLE_OOS",)
        return Verdict.REJECTED,(stage+"_FAIL",)
    raise ValueError(stage)

class V3Store:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS patterns(pattern_id TEXT PRIMARY KEY,target TEXT,timeframe INTEGER,payload_json TEXT,score REAL,trial_number INTEGER,created_at TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS candidates(candidate_id TEXT PRIMARY KEY,spec_json TEXT,stage TEXT,verdict TEXT,created_at TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,candidate_id TEXT,stage TEXT,verdict TEXT,metrics_json TEXT,reason TEXT,adaptive INTEGER,created_at TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS search_runs(id INTEGER PRIMARY KEY AUTOINCREMENT,target TEXT,timeframe INTEGER,trials INTEGER,max_depth INTEGER,max_rules INTEGER,seed INTEGER,created_at TEXT)")
    @staticmethod
    def now():return datetime.now(UTC).isoformat()
    def add_search_run(self,target,timeframe,trials,max_depth,max_rules,seed):
        with sqlite3.connect(self.path) as db:db.execute("INSERT INTO search_runs(target,timeframe,trials,max_depth,max_rules,seed,created_at) VALUES(?,?,?,?,?,?,?)",(target,timeframe,trials,max_depth,max_rules,seed,self.now()))
    def add_pattern(self,p):
        with sqlite3.connect(self.path) as db:db.execute("INSERT OR IGNORE INTO patterns VALUES(?,?,?,?,?,?,?)",(p.pattern_id,p.target,p.timeframe,json.dumps(p.as_dict(),sort_keys=True),p.score,p.trial_number,self.now()))
    def add_candidate(self,s):
        cid=f"v3-{s.target.lower()}-{s.pattern_id[:8]}-{s.fingerprint[:8]}"
        with sqlite3.connect(self.path) as db:db.execute("INSERT OR IGNORE INTO candidates VALUES(?,?,?,?,?)",(cid,json.dumps(s.as_dict(),sort_keys=True),"RESEARCH","NEW",self.now()))
        return cid
    def pending(self):
        with sqlite3.connect(self.path) as db:return db.execute("SELECT candidate_id,spec_json,stage FROM candidates WHERE stage NOT IN ('REJECTED','UNCERTAIN','BLIND_WAIT','PROMOTED') ORDER BY created_at,candidate_id").fetchall()
    def advance(self,cid,stage,verdict,metrics,reason,next_stage,adaptive):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO events(candidate_id,stage,verdict,metrics_json,reason,adaptive,created_at) VALUES(?,?,?,?,?,?,?)",(cid,stage,verdict,json.dumps(metrics,sort_keys=True),reason,int(bool(adaptive)),self.now()));db.execute("UPDATE candidates SET stage=?,verdict=? WHERE candidate_id=?",(next_stage,verdict,cid))
    def counts(self):
        with sqlite3.connect(self.path) as db:return dict(db.execute("SELECT stage,COUNT(*) FROM candidates GROUP BY stage").fetchall())
    def adaptive_memory(self):
        with sqlite3.connect(self.path) as db:return db.execute("SELECT candidate_id,stage,verdict,metrics_json,reason FROM events WHERE adaptive=1 ORDER BY id DESC").fetchall()
    def trial_count(self):
        with sqlite3.connect(self.path) as db:return int(db.execute("SELECT COALESCE(SUM(trials),0) FROM search_runs").fetchone()[0])
