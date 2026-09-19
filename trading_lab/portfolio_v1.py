"""Deterministic portfolio helpers for Desk V1."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from math import sqrt
from statistics import mean
from typing import Mapping, Sequence


def pearson(a:Sequence[float],b:Sequence[float])->float:
    if len(a)!=len(b) or len(a)<2: return 0.0
    ma,mb=mean(a),mean(b)
    xa=[x-ma for x in a]; xb=[x-mb for x in b]
    den=sqrt(sum(x*x for x in xa)*sum(y*y for y in xb))
    return sum(x*y for x,y in zip(xa,xb))/den if den else 0.0


@dataclass(frozen=True)
class PortfolioLeg:
    name:str
    daily_returns:Mapping[date,float]
    weight:float=1.0
    daily_trades:Mapping[date,int]|None=None


def aggregate(legs:Sequence[PortfolioLeg])->dict:
    if not legs: raise ValueError("portfolio needs at least one leg")
    dates=sorted(set().union(*(leg.daily_returns.keys() for leg in legs)))
    total_weight=sum(abs(leg.weight) for leg in legs)
    if total_weight<=0: raise ValueError("weights cannot all be zero")
    daily={}
    trades={}
    for d in dates:
        daily[d]=sum(leg.weight*leg.daily_returns.get(d,0.0) for leg in legs)/total_weight
        trades[d]=sum((leg.daily_trades or {}).get(d,0) for leg in legs)
    equity=1.0; peak=1.0; dd=0.0
    months={}
    for d in dates:
        equity*=1+daily[d]
        peak=max(peak,equity); dd=max(dd,1-equity/peak)
        k=(d.year,d.month)
        months[k]=months.get(k,1.0)*(1+daily[d])
    monthly=[x-1 for x in months.values()]
    return {
        "days":len(dates),
        "total_return":equity-1,
        "max_drawdown":dd,
        "mean_monthly_return":mean(monthly) if monthly else None,
        "median_like_monthly_midpoint":sorted(monthly)[len(monthly)//2] if monthly else None,
        "trades_per_day":sum(trades.values())/len(dates) if dates else None,
        "monthly_returns":monthly,
    }
