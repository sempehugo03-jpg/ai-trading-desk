import json
import unittest

from trading_lab.agent_provider import FakeProvider
from trading_lab.desk_agents import ResearcherAgent, ReviewAgent
from trading_lab.strategy_dsl import Family, SideMode, StrategySpec


VALID = {
    "family":"MOMENTUM","instrument":"XAUUSD","timeframe_minutes":15,
    "fast_lookback":10,"slow_lookback":40,"threshold_atr":0.2,
    "stop_atr":1.5,"target_r":2.0,"max_holding_bars":20,
    "side_mode":"BOTH","session_start_utc":7,"session_end_utc":20,
}


class StrategyDslTests(unittest.TestCase):
    def test_valid_spec_is_stable(self):
        a=StrategySpec.from_mapping(VALID)
        b=StrategySpec.from_mapping(dict(VALID))
        self.assertEqual(a.fingerprint,b.fingerprint)
        self.assertEqual(a.family,Family.MOMENTUM)

    def test_unknown_field_rejected(self):
        x=dict(VALID); x["python_code"]="import os"
        with self.assertRaises(ValueError): StrategySpec.from_mapping(x)

    def test_unsafe_bounds_rejected(self):
        x=dict(VALID); x["target_r"]=999
        with self.assertRaises(ValueError): StrategySpec.from_mapping(x)

    def test_slow_must_exceed_fast(self):
        x=dict(VALID); x["slow_lookback"]=5; x["fast_lookback"]=10
        with self.assertRaises(ValueError): StrategySpec.from_mapping(x)


class AgentTests(unittest.TestCase):
    def test_researcher_deduplicates_and_validates(self):
        p=FakeProvider([{"strategies":[VALID,dict(VALID)]}])
        out=ResearcherAgent(p).propose(batch_size=2)
        self.assertEqual(len(out),1)

    def test_review_agent_can_veto_but_not_rewrite_metrics(self):
        p=FakeProvider([{"veto":True,"reasons":["fragile"],"concerns":[]}])
        r=ReviewAgent(p,"red_team").review(StrategySpec.from_mapping(VALID),{"expectancy_r":.2},{})
        self.assertTrue(r.veto)
        self.assertEqual(r.reasons,("fragile",))

    def test_researcher_rejects_empty_valid_set(self):
        bad=dict(VALID); bad["instrument"]="BTCUSD"
        p=FakeProvider([{"strategies":[bad]}])
        with self.assertRaises(ValueError): ResearcherAgent(p).propose()


if __name__ == "__main__":
    unittest.main()
