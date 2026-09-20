import unittest
from trading_lab.discovery_v2 import Condition,StrategyV2,Verdict,classify,FEATURES

class ProgressiveGateTests(unittest.TestCase):
    def test_positive_rare_is_uncertain(self):
        v,_=classify({"closed_trades":8,"expectancy_r":.12,"profit_factor_r":1.4,"max_drawdown_r":2},"RESEARCH");self.assertEqual(v,Verdict.UNCERTAIN)
    def test_negative_is_rejected(self):
        v,_=classify({"closed_trades":100,"expectancy_r":-.1,"profit_factor_r":.8,"max_drawdown_r":20},"RESEARCH");self.assertEqual(v,Verdict.REJECTED)
    def test_good_research_passes(self):
        v,_=classify({"closed_trades":60,"expectancy_r":.08,"profit_factor_r":1.2,"max_drawdown_r":8},"RESEARCH");self.assertEqual(v,Verdict.PASS)

class OpenStrategyTests(unittest.TestCase):
    def test_strategy_has_no_family(self):
        s=StrategyV2("p","XAUUSD",15,"LONG",3,(Condition("trend_10_40",">=",.5),Condition("range_position_20","<=",.3)),1.5,2.0);self.assertNotIn("family",s.as_dict())
    def test_unknown_feature_rejected(self):
        with self.assertRaises(ValueError):Condition("magic",">=",1)
    def test_feature_space_is_observational(self):self.assertGreaterEqual(len(FEATURES),10)

if __name__=="__main__":unittest.main()
