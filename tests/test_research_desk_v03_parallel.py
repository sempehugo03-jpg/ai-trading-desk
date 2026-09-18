from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from trading_lab.desk_agents import MutationAgent
from trading_lab.parallel_agents import ParallelIdeaFactory, SpecialistPlan
from trading_lab.quant_desk import GatePolicy, gate_failures
from trading_lab.strategy_dsl import StrategySpec


BASE = {
    "family":"MOMENTUM","instrument":"XAUUSD","timeframe_minutes":15,
    "fast_lookback":10,"slow_lookback":40,"threshold_atr":0.2,
    "stop_atr":1.5,"target_r":2.0,"max_holding_bars":20,
    "side_mode":"BOTH","session_start_utc":7,"session_end_utc":20,
}


class PromptProvider:
    def __init__(self):
        self.lock=threading.Lock()
        self.active=0
        self.max_active=0
        self.calls=0

    def complete_json(self, **kwargs):
        with self.lock:
            self.active += 1
            self.calls += 1
            self.max_active=max(self.max_active,self.active)
            i=self.calls
        time.sleep(.03)
        item=dict(BASE)
        item["fast_lookback"]=5 + i
        item["slow_lookback"]=40 + i
        with self.lock:
            self.active -= 1
        return {"strategies":[item]}


class ParallelIdeaTests(unittest.TestCase):
    def test_explorers_actually_overlap(self):
        p=PromptProvider()
        plans=tuple(SpecialistPlan(str(i),f"focus {i}") for i in range(4))
        f=ParallelIdeaFactory(p,workers=4,exploration_fraction=1.0,specialists=plans)
        out=f.propose(total=4)
        self.assertEqual(len(out),4)
        self.assertGreaterEqual(p.max_active,2)

    def test_gate_failures_reports_all_failures(self):
        failures=gate_failures({
            "closed_trades":2,
            "expectancy_r":-.2,
            "profit_factor_r":.5,
            "max_drawdown_r":99,
        },GatePolicy(min_trades=30,max_drawdown_r=12))
        self.assertEqual(
            failures,
            ("INSUFFICIENT_TRADES","NON_POSITIVE_EXPECTANCY","PROFIT_FACTOR_GATE","DRAWDOWN_R_GATE")
        )

    def test_mutation_distance_guard(self):
        parent=StrategySpec.from_mapping(BASE)
        child=dict(BASE); child["fast_lookback"]=11; child["target_r"]=2.5
        c=StrategySpec.from_mapping(child)
        self.assertEqual(MutationAgent.distance(parent,c),2)


if __name__=="__main__":
    unittest.main()
