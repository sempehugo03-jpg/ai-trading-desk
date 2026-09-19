"""Desk V1: expanded multi-asset, multi-family scientific research.

This layer is intentionally separate from V0.x so existing campaigns remain
reproducible. It reuses the deterministic execution engine and ResearchStore.
No broker/live-order capability exists here.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from bisect import bisect_right
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from enum import Enum
from math import isfinite
from pathlib import Path
from statistics import mean
from typing import Mapping, Sequence

from .agent_provider import JsonAgentProvider
from .data import load_csv_segments, resample_closed, validate_m1
from .engine import backtest
from .models import Config, Side, Signal
from .research import Candidate, ResearchStore, Stage, StageOutcome
from .stress import cost_multiplier, spread_multiplier


class V1Family(str, Enum):
    MOMENTUM = "MOMENTUM"
    MEAN_REVERSION = "MEAN_REVERSION"
    BREAKOUT = "BREAKOUT"
    TREND_PULLBACK = "TREND_PULLBACK"
    REVERSAL = "REVERSAL"
    VOLATILITY_EXPANSION = "VOLATILITY_EXPANSION"
    VOLATILITY_COMPRESSION = "VOLATILITY_COMPRESSION"
    LIQUIDITY_SWEEP = "LIQUIDITY_SWEEP"


class V1SideMode(str, Enum):
    BOTH = "BOTH"
    LONG_ONLY = "LONG_ONLY"
    SHORT_ONLY = "SHORT_ONLY"


class RegimeFilter(str, Enum):
    ANY = "ANY"
    TREND = "TREND"
    RANGE = "RANGE"
    HIGH_VOL = "HIGH_VOL"
    LOW_VOL = "LOW_VOL"


# Supported by the data adapter. A campaign only exposes instruments whose
# normalized M1 files actually exist, so expansion is data-gated.
SUPPORTED_INSTRUMENTS = (
    "XAUUSD", "XAGUSD",
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
    "NAS100", "US500", "US30", "DAX",
    "WTI", "BRENT",
)

TIMEFRAMES = (5, 15, 60, 240)


@dataclass(frozen=True)
class V1StrategySpec:
    family: V1Family
    instrument: str
    timeframe_minutes: int
    fast_lookback: int
    slow_lookback: int
    threshold_atr: float
    stop_atr: float
    target_r: float
    max_holding_bars: int
    side_mode: V1SideMode = V1SideMode.BOTH
    session_start_utc: int = 0
    session_end_utc: int = 24
    regime_filter: RegimeFilter = RegimeFilter.ANY

    def __post_init__(self):
        if not isinstance(self.family, V1Family):
            raise ValueError("unsupported family")
        if self.instrument not in SUPPORTED_INSTRUMENTS:
            raise ValueError("unsupported instrument")
        if self.timeframe_minutes not in TIMEFRAMES:
            raise ValueError("unsupported timeframe")
        if not 2 <= self.fast_lookback <= 100:
            raise ValueError("fast_lookback out of bounds")
        if not 5 <= self.slow_lookback <= 300 or self.slow_lookback <= self.fast_lookback:
            raise ValueError("slow_lookback must be > fast_lookback")
        for name, value, lo, hi in (
            ("threshold_atr", self.threshold_atr, 0.0, 5.0),
            ("stop_atr", self.stop_atr, 0.25, 8.0),
            ("target_r", self.target_r, 0.25, 10.0),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
            if not lo <= float(value) <= hi:
                raise ValueError(f"{name} out of bounds")
        if not 1 <= self.max_holding_bars <= 240:
            raise ValueError("max_holding_bars out of bounds")
        if not isinstance(self.side_mode, V1SideMode):
            raise ValueError("invalid side mode")
        if not isinstance(self.regime_filter, RegimeFilter):
            raise ValueError("invalid regime filter")
        if not 0 <= self.session_start_utc < self.session_end_utc <= 24:
            raise ValueError("invalid session")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "V1StrategySpec":
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"unknown V1 fields: {sorted(unknown)}")
        x = dict(value)
        x["family"] = V1Family(str(x["family"]))
        x["side_mode"] = V1SideMode(str(x.get("side_mode", "BOTH")))
        x["regime_filter"] = RegimeFilter(str(x.get("regime_filter", "ANY")))
        for k in (
            "timeframe_minutes", "fast_lookback", "slow_lookback",
            "max_holding_bars", "session_start_utc", "session_end_utc",
        ):
            if k in x:
                x[k] = int(x[k])
        for k in ("threshold_atr", "stop_atr", "target_r"):
            if k in x:
                x[k] = float(x[k])
        return cls(**x)

    def as_dict(self) -> dict:
        x = asdict(self)
        x["family"] = self.family.value
        x["side_mode"] = self.side_mode.value
        x["regime_filter"] = self.regime_filter.value
        return x

    @property
    def fingerprint(self) -> str:
        raw = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()


def available_instruments(data_root: str | Path = "data/raw") -> tuple[str, ...]:
    root = Path(data_root)
    return tuple(
        symbol for symbol in SUPPORTED_INSTRUMENTS
        if (root / symbol / "m1.csv").exists()
    )


def compile_v1_cached(spec: V1StrategySpec, source: Sequence):
    """O(n) compiler using only already-closed information."""
    m1 = validate_m1(source)
    tf = resample_closed(m1, spec.timeframe_minutes, m1[-1].close_time)
    if not tf:
        return lambda history: None

    n = len(tf)
    closes = [float(b.close) for b in tf]
    opens = [float(b.open) for b in tf]
    highs = [float(b.high) for b in tf]
    lows = [float(b.low) for b in tf]
    ranges = [h-l for h,l in zip(highs,lows)]
    close_times = [b.close_time for b in tf]

    close_prefix = [0.0]*(n+1)
    range_prefix = [0.0]*(n+1)
    tr = [0.0]*n
    tr_prefix = [0.0]*(n+1)
    for i,b in enumerate(tf):
        close_prefix[i+1] = close_prefix[i] + closes[i]
        range_prefix[i+1] = range_prefix[i] + ranges[i]
        if i:
            prev = tf[i-1]
            tr[i] = max(
                float(b.high-b.low),
                abs(float(b.high-prev.close)),
                abs(float(b.low-prev.close)),
            )
        tr_prefix[i+1] = tr_prefix[i] + tr[i]

    def avg(prefix, i, width):
        return (prefix[i+1]-prefix[i+1-width])/width

    atr_n = min(20, spec.slow_lookback)
    regime_long = min(60, spec.slow_lookback)
    signals = [None]*n
    need = max(spec.slow_lookback+2, regime_long+2, 10)

    maxq, minq = deque(), deque()
    for i in range(n):
        prev_i=i-1
        if prev_i >= 0:
            while maxq and highs[maxq[-1]] <= highs[prev_i]:
                maxq.pop()
            maxq.append(prev_i)
            while minq and lows[minq[-1]] >= lows[prev_i]:
                minq.pop()
            minq.append(prev_i)
        lower=i-spec.slow_lookback
        while maxq and maxq[0] < lower: maxq.popleft()
        while minq and minq[0] < lower: minq.popleft()

        if i+1 < need or i < atr_n:
            continue

        atr = avg(tr_prefix, i, atr_n)
        if atr <= 0:
            continue
        fast = avg(close_prefix, i, spec.fast_lookback)
        slow = avg(close_prefix, i, spec.slow_lookback)
        current = closes[i]
        score = (fast-slow)/atr

        # Regime filter uses only data available at i.
        trend = abs(score) >= .45
        atr_long = avg(tr_prefix, i, regime_long)
        vol_ratio = atr/atr_long if atr_long > 0 else 1.0
        current_regimes = {
            RegimeFilter.TREND if trend else RegimeFilter.RANGE,
            RegimeFilter.HIGH_VOL if vol_ratio >= 1.25 else (
                RegimeFilter.LOW_VOL if vol_ratio <= .80 else RegimeFilter.ANY
            ),
        }
        if spec.regime_filter is not RegimeFilter.ANY and spec.regime_filter not in current_regimes:
            continue

        side=None
        pad=spec.threshold_atr*atr
        prior_hi = highs[maxq[0]] if maxq else None
        prior_lo = lows[minq[0]] if minq else None

        if spec.family is V1Family.MOMENTUM:
            if score >= spec.threshold_atr: side=Side.LONG
            elif score <= -spec.threshold_atr: side=Side.SHORT

        elif spec.family is V1Family.MEAN_REVERSION:
            z=(current-slow)/atr
            if z <= -spec.threshold_atr: side=Side.LONG
            elif z >= spec.threshold_atr: side=Side.SHORT

        elif spec.family is V1Family.BREAKOUT and prior_hi is not None:
            if current >= prior_hi+pad: side=Side.LONG
            elif current <= prior_lo-pad: side=Side.SHORT

        elif spec.family is V1Family.TREND_PULLBACK:
            distance=(current-fast)/atr
            if score > .25 and distance <= -spec.threshold_atr: side=Side.LONG
            elif score < -.25 and distance >= spec.threshold_atr: side=Side.SHORT

        elif spec.family is V1Family.REVERSAL:
            body=(closes[i]-opens[i])/atr
            if i and (closes[i-1]-opens[i-1])/atr <= -spec.threshold_atr and body > 0:
                side=Side.LONG
            elif i and (closes[i-1]-opens[i-1])/atr >= spec.threshold_atr and body < 0:
                side=Side.SHORT

        elif spec.family is V1Family.VOLATILITY_EXPANSION:
            range_ratio=ranges[i]/atr
            trigger=max(1.0, spec.threshold_atr)
            if range_ratio >= trigger:
                if closes[i] > opens[i]: side=Side.LONG
                elif closes[i] < opens[i]: side=Side.SHORT

        elif spec.family is V1Family.VOLATILITY_COMPRESSION and prior_hi is not None:
            avg_range=avg(range_prefix, i-1, spec.fast_lookback)
            compression=avg_range/atr
            trigger=max(.15, min(1.5, spec.threshold_atr))
            if compression <= trigger:
                if current > prior_hi: side=Side.LONG
                elif current < prior_lo: side=Side.SHORT

        elif spec.family is V1Family.LIQUIDITY_SWEEP and prior_hi is not None:
            # Sweep an old extreme, but close back inside it.
            if highs[i] > prior_hi+pad and current < prior_hi:
                side=Side.SHORT
            elif lows[i] < prior_lo-pad and current > prior_lo:
                side=Side.LONG

        if side is None:
            continue
        if spec.side_mode is V1SideMode.LONG_ONLY and side is Side.SHORT:
            continue
        if spec.side_mode is V1SideMode.SHORT_ONLY and side is Side.LONG:
            continue

        risk=spec.stop_atr*atr
        if side is Side.LONG:
            stop,target=current-risk,current+risk*spec.target_r
        else:
            stop,target=current+risk,current-risk*spec.target_r
        signals[i]=Signal(
            side, stop, target,
            spec.max_holding_bars*spec.timeframe_minutes,
        )

    index=-1
    last_as_of=None
    def strategy(history):
        nonlocal index,last_as_of
        if not history: return None
        as_of=history[-1].close_time
        if last_as_of is None or as_of < last_as_of:
            index=bisect_right(close_times,as_of)-1
        else:
            while index+1<n and close_times[index+1] <= as_of:
                index+=1
        last_as_of=as_of
        return signals[index] if index>=0 else None
    return strategy


@dataclass(frozen=True)
class V1GatePolicy:
    min_trades: int = 30
    min_expectancy_r: float = 0.0
    min_profit_factor_r: float = 1.0
    max_drawdown_r: float = 12.0


@dataclass(frozen=True)
class V1Outcome:
    passed: bool
    metrics: dict
    evidence: dict
    reason: str


def _aggregate(results) -> dict:
    trades=[t for r in results for t in r.trades]
    rs=[float(t.r_multiple) for t in trades]
    wins=sum(x for x in rs if x>0)
    losses=-sum(x for x in rs if x<0)
    eq=peak=dd=0.0
    for x in rs:
        eq+=x; peak=max(peak,eq); dd=max(dd,peak-eq)
    days=sum(r.observed_session_days for r in results)
    entries=sum(sum(e.get("kind")=="ENTRY" for e in r.events) for r in results)
    return {
        "closed_trades":len(trades),
        "expectancy_r":mean(rs) if rs else None,
        "profit_factor_r":wins/losses if losses else None,
        "max_drawdown_r":dd,
        "entries_per_observed_session_day":entries/days if days else None,
        "observed_session_days":days,
    }


def all_failures(metrics: Mapping[str, object], policy: V1GatePolicy) -> tuple[str,...]:
    out=[]
    n=int(metrics.get("closed_trades") or 0)
    exp=metrics.get("expectancy_r")
    pf=metrics.get("profit_factor_r")
    dd=metrics.get("max_drawdown_r")
    if n < policy.min_trades: out.append("INSUFFICIENT_TRADES")
    if exp is None or not isfinite(float(exp)) or float(exp) <= policy.min_expectancy_r:
        out.append("NON_POSITIVE_EXPECTANCY")
    if pf is None or not isfinite(float(pf)) or float(pf) < policy.min_profit_factor_r:
        out.append("PROFIT_FACTOR_GATE")
    if dd is None or float(dd) > policy.max_drawdown_r:
        out.append("DRAWDOWN_R_GATE")
    return tuple(out)


_CACHE={}


def _load_market(root: str|Path, symbol: str):
    path=(Path(root)/symbol/"m1.csv").resolve()
    stat=path.stat()
    key=(str(path),stat.st_size,stat.st_mtime_ns)
    if key not in _CACHE:
        # Keep cache bounded to two symbols.
        if len(_CACHE)>=2:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key]=load_csv_segments(path)
    return _CACHE[key]


def _fraction(segments,start,end):
    total=sum(len(x) for x in segments)
    lo,hi=int(total*start),int(total*end)
    cursor=0; out=[]
    for seg in segments:
        a,b=cursor,cursor+len(seg)
        tl,th=max(lo,a),min(hi,b)
        if tl<th:
            part=tuple(seg[tl-a:th-a])
            if len(part)>=2: out.append(part)
        cursor=b
        if cursor>=hi: break
    return tuple(out)


def _run_segments(segs,spec):
    cfg=Config(
        session_start_utc=spec.session_start_utc,
        session_end_utc=spec.session_end_utc,
    )
    results=[]
    for seg in segs:
        strategy=compile_v1_cached(spec,seg)
        results.append(backtest(
            seg,strategy,cfg,strategy_id=spec.fingerprint[:16],
            compact_events=True,copy_history=False,
        ))
    return results


def evaluate_v1_split(
    spec: V1StrategySpec, *, data_root="data/raw", split="IS",
    policy: V1GatePolicy|None=None,
) -> V1Outcome:
    fractions={"IS":(0,.60),"VALIDATION":(.60,.80),"OOS":(.80,1)}
    p=policy or V1GatePolicy()
    segs=_fraction(_load_market(data_root,spec.instrument),*fractions[split])
    metrics=_aggregate(_run_segments(segs,spec))
    failures=all_failures(metrics,p)
    return V1Outcome(
        not failures, metrics,
        {"split":split,"failed_gates":failures,"strategy_hash":spec.fingerprint},
        failures[0] if failures else "QUANT_PASS",
    )


def evaluate_v1_walk_forward(spec:V1StrategySpec,*,data_root="data/raw",folds=5)->V1Outcome:
    segments=_load_market(data_root,spec.instrument)
    fold_metrics=[]
    for i in range(1,folds+1):
        segs=_fraction(segments,i/(folds+1),(i+1)/(folds+1))
        fold_metrics.append(_aggregate(_run_segments(segs,spec)))
    valid=[m for m in fold_metrics if (m.get("closed_trades") or 0)>0 and m.get("expectancy_r") is not None]
    positive=sum(float(m["expectancy_r"])>0 for m in valid)
    frac=positive/len(valid) if valid else 0
    avg=mean(float(m["expectancy_r"]) for m in valid) if valid else None
    worst=min((float(m["expectancy_r"]) for m in valid),default=None)
    metrics={
        "folds_with_trades":len(valid),"positive_fold_fraction":frac,
        "mean_fold_expectancy_r":avg,"worst_fold_expectancy_r":worst,
    }
    ok=len(valid)>=3 and frac>=.60 and (avg or -1)>0
    return V1Outcome(ok,metrics,{"fold_metrics":fold_metrics},"WALK_FORWARD_PASS" if ok else "WALK_FORWARD_UNSTABLE")


def evaluate_v1_stress(spec:V1StrategySpec,*,data_root="data/raw")->V1Outcome:
    segs=_fraction(_load_market(data_root,spec.instrument),.80,1)
    base=Config(session_start_utc=spec.session_start_utc,session_end_utc=spec.session_end_utc)
    scenarios=[]
    for name,sf,cf in (("BASE",1,1),("X1_5",1.5,1.5),("X2",2,2)):
        cfg=cost_multiplier(base,cf) if cf>1 else base
        results=[]
        for seg in segs:
            stressed=spread_multiplier(seg,sf) if sf>1 else tuple(seg)
            strategy=compile_v1_cached(spec,stressed)
            results.append(backtest(stressed,strategy,cfg,strategy_id=spec.fingerprint[:16],compact_events=True,copy_history=False))
        scenarios.append({"name":name,**_aggregate(results)})
    worst=scenarios[-1]
    ok=(worst.get("closed_trades") or 0)>=10 and (worst.get("expectancy_r") is not None and float(worst["expectancy_r"])>0)
    return V1Outcome(ok,{"scenarios":scenarios},{"stress_max":"2x"},"STRESS_PASS" if ok else "STRESS_FAIL")


def research_schema(available: Sequence[str]) -> dict:
    return {
        "type":"object",
        "properties":{
            "strategies":{
                "type":"array","minItems":1,"maxItems":12,
                "items":{
                    "type":"object",
                    "properties":{
                        "family":{"type":"string","enum":[x.value for x in V1Family]},
                        "instrument":{"type":"string","enum":list(available)},
                        "timeframe_minutes":{"type":"integer","enum":list(TIMEFRAMES)},
                        "fast_lookback":{"type":"integer","minimum":2,"maximum":100},
                        "slow_lookback":{"type":"integer","minimum":5,"maximum":300},
                        "threshold_atr":{"type":"number","minimum":0,"maximum":5},
                        "stop_atr":{"type":"number","minimum":0.25,"maximum":8},
                        "target_r":{"type":"number","minimum":0.25,"maximum":10},
                        "max_holding_bars":{"type":"integer","minimum":1,"maximum":240},
                        "side_mode":{"type":"string","enum":[x.value for x in V1SideMode]},
                        "session_start_utc":{"type":"integer","minimum":0,"maximum":23},
                        "session_end_utc":{"type":"integer","minimum":1,"maximum":24},
                        "regime_filter":{"type":"string","enum":[x.value for x in RegimeFilter]},
                    },
                    "required":[
                        "family","instrument","timeframe_minutes","fast_lookback",
                        "slow_lookback","threshold_atr","stop_atr","target_r",
                        "max_holding_bars","side_mode","session_start_utc",
                        "session_end_utc","regime_filter",
                    ],
                    "additionalProperties":False,
                },
            }
        },
        "required":["strategies"],"additionalProperties":False,
    }


class V1IdeaFactory:
    SPECIALISTS=(
        ("metals","Gold/silver specialists: momentum, reversal, sweep, volatility and trend-pullback."),
        ("fx","FX specialists: EURUSD/GBPUSD/USDJPY/AUDUSD/USDCAD, session and regime diversity."),
        ("us_indices","US indices specialists: NAS100/US500/US30, breakout, volatility, trend and reversal."),
        ("europe","European index specialist: DAX when data is available."),
        ("energy","Energy specialist: WTI/BRENT when data is available."),
        ("regime","Regime specialist: explicitly use TREND/RANGE/HIGH_VOL/LOW_VOL filters."),
        ("liquidity","Liquidity/sweep specialist. Prefer falsifiable reversal-at-extreme hypotheses."),
        ("contrarian","Search parameter/family regions unlike recent failures; avoid cosmetic variants."),
    )

    def __init__(self,provider:JsonAgentProvider,workers=8):
        self.provider=provider; self.workers=max(1,workers)

    def propose(self,total:int,available:Sequence[str],memory:Sequence[Mapping[str,object]])->tuple[V1StrategySpec,...]:
        schema=research_schema(available)
        jobs=[]
        for i in range(total):
            name,focus=self.SPECIALISTS[i%len(self.SPECIALISTS)]
            prompt=(
                "Generate exactly one falsifiable intraday strategy. "
                f"Available instruments: {list(available)}. Specialist focus: {focus}. "
                "Portfolio objective is ~10% net/month with controlled drawdown and prop-firm compatibility, "
                "but do NOT force this single strategy to hit the portfolio target. Prefer independent small edges. "
                f"Non-blind past evidence: {list(memory)[-25:]}"
            )
            jobs.append((i,name,prompt))
        out={}
        def call(name,prompt):
            return self.provider.complete_json(
                role=f"v1_{name}",
                instructions="You are one independent quant research specialist. Return strategy JSON only; no claims.",
                prompt=prompt,schema_name="desk_v1_strategy",schema=schema,
            )
        with ThreadPoolExecutor(max_workers=min(self.workers,len(jobs))) as pool:
            futs={pool.submit(call,name,prompt):i for i,name,prompt in jobs}
            for fut in as_completed(futs):
                i=futs[fut]
                try: out[i]=fut.result()
                except Exception: out[i]={}
        result=[]; seen=set()
        for i in sorted(out):
            for item in out[i].get("strategies",[])[:1]:
                try: spec=V1StrategySpec.from_mapping(item)
                except Exception: continue
                if spec.instrument not in available or spec.fingerprint in seen: continue
                seen.add(spec.fingerprint); result.append(spec)
        return tuple(result)


class DeskV1:
    def __init__(self,store:ResearchStore,provider:JsonAgentProvider,*,data_root="data/raw",workers=8,total_cap=100):
        self.store=store; self.provider=provider; self.data_root=data_root
        self.workers=workers; self.total_cap=total_cap
        self.factory=V1IdeaFactory(provider,workers)

    def _total(self):
        with sqlite3.connect(self.store.path) as db:
            return int(db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0])

    def _memory(self):
        with sqlite3.connect(self.store.path) as db:
            rows=db.execute("""
                SELECT c.spec_json,e.stage,e.reason,e.metrics_json
                FROM events e JOIN candidates c ON c.candidate_id=e.candidate_id
                WHERE e.passed=0 AND e.stage!='BLIND'
                ORDER BY e.id DESC LIMIT 30
            """).fetchall()
        ans=[]
        for spec,stage,reason,metrics in rows:
            try:
                m=json.loads(metrics); s=json.loads(spec)
            except Exception: continue
            ans.append({"stage":stage,"reason":reason,"metrics":{
                k:m.get(k) for k in ("closed_trades","expectancy_r","profit_factor_r","max_drawdown_r","entries_per_observed_session_day")
            },"spec":s})
        return tuple(ans)

    def generate(self,batch=12):
        remaining=self.total_cap-self._total()
        if remaining<=0: return 0
        available=available_instruments(self.data_root)
        if not available: raise RuntimeError("No V1 market data available")
        specs=self.factory.propose(min(batch,remaining),available,self._memory())
        created=0
        for spec in specs:
            cid=f"v1-{spec.family.value.lower()}-{spec.instrument.lower()}-{spec.fingerprint[:10]}"
            try:
                self.store.add_candidate(cid,spec.family.value,1,spec.as_dict()); created+=1
            except sqlite3.IntegrityError: pass
        return created

    def _spec(self,c): return V1StrategySpec.from_mapping(c.spec)

    def step(self,batch=12):
        for c in self.store.pending():
            spec=self._spec(c)
            if c.stage is Stage.RESEARCH:
                out=evaluate_v1_split(spec,data_root=self.data_root,split="IS",policy=V1GatePolicy(min_trades=30))
            elif c.stage is Stage.VALIDATION:
                out=evaluate_v1_split(spec,data_root=self.data_root,split="VALIDATION",policy=V1GatePolicy(min_trades=20))
            elif c.stage is Stage.OOS:
                out=evaluate_v1_split(spec,data_root=self.data_root,split="OOS",policy=V1GatePolicy(min_trades=20,min_expectancy_r=.01,min_profit_factor_r=1.02))
            elif c.stage is Stage.WALK_FORWARD:
                out=evaluate_v1_walk_forward(spec,data_root=self.data_root)
            elif c.stage is Stage.STRESS:
                out=evaluate_v1_stress(spec,data_root=self.data_root)
            elif c.stage in (Stage.BLIND,Stage.SHADOW):
                continue
            else:
                continue
            self.store.record(c.candidate_id,c.stage,StageOutcome(out.passed,out.metrics,out.evidence,out.reason))
            return True
        return self.generate(batch)>0
