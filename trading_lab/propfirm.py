"""Generic prop-firm challenge rules.

The FTMO preset mirrors the public 2-Step objectives checked on 2026-09-19.
This simulator is conservative but still an approximation: exact broker/prop
floating-P&L, commissions, swaps and midnight reset mechanics require intraday
equity data from the execution venue.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class PropProfile:
    name: str
    profit_target: float
    max_daily_loss: float
    max_total_loss: float
    min_trading_days: int

    def __post_init__(self):
        for x in (self.profit_target,self.max_daily_loss,self.max_total_loss):
            if not 0 < x < 1: raise ValueError("prop percentages must be fractions")
        if self.min_trading_days < 1: raise ValueError("min trading days must be >=1")


FTMO_2STEP_STEP1 = PropProfile("FTMO_2STEP_STEP1",.10,.05,.10,4)
FTMO_2STEP_STEP2 = PropProfile("FTMO_2STEP_STEP2",.05,.05,.10,4)


@dataclass(frozen=True)
class PropDay:
    start_balance: float
    min_equity: float
    end_balance: float
    traded: bool = True


@dataclass(frozen=True)
class PropResult:
    passed: bool
    breached: bool
    reason: str
    trading_days: int
    return_pct: float
    worst_daily_loss_pct: float
    max_total_drawdown_pct: float


def simulate_prop(days:Sequence[PropDay],profile:PropProfile,initial_balance:float)->PropResult:
    if initial_balance<=0: raise ValueError("initial_balance must be positive")
    traded=0; worst_daily=0.0; worst_total=0.0
    total_floor=initial_balance*(1-profile.max_total_loss)
    end=initial_balance
    for day in days:
        if day.traded: traded+=1
        daily_floor=day.start_balance-initial_balance*profile.max_daily_loss
        daily_loss=max(0,(day.start_balance-day.min_equity)/initial_balance)
        total_dd=max(0,(initial_balance-day.min_equity)/initial_balance)
        worst_daily=max(worst_daily,daily_loss)
        worst_total=max(worst_total,total_dd)
        if day.min_equity < daily_floor-1e-9:
            return PropResult(False,True,"MAX_DAILY_LOSS",traded,day.end_balance/initial_balance-1,worst_daily,worst_total)
        if day.min_equity < total_floor-1e-9:
            return PropResult(False,True,"MAX_TOTAL_LOSS",traded,day.end_balance/initial_balance-1,worst_daily,worst_total)
        end=day.end_balance
    ret=end/initial_balance-1
    if traded < profile.min_trading_days:
        return PropResult(False,False,"MIN_TRADING_DAYS",traded,ret,worst_daily,worst_total)
    if ret < profile.profit_target:
        return PropResult(False,False,"PROFIT_TARGET_NOT_REACHED",traded,ret,worst_daily,worst_total)
    return PropResult(True,False,"PASS",traded,ret,worst_daily,worst_total)
