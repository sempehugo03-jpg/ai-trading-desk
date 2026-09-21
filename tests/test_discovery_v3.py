import unittest
from trading_lab.discovery_v3 import Expr,Rule,StrategyV3,Verdict,classify
class GrammarTests(unittest.TestCase):
    def test_cross_asset_expression(self):
        e=Expr("sub",args=(Expr("feature","self.ret1_atr"),Expr("feature","US500.ret1_atr")))
        self.assertIn("US500.ret1_atr",e.features())
    def test_no_family(self):
        s=StrategyV3("p","XAUUSD",15,"LONG",6,(Rule(Expr("feature","self.ret1_atr"),">=",1.0),),1.0,2.0)
        self.assertNotIn("family",s.as_dict())
class GateTests(unittest.TestCase):
    def test_rare_positive_uncertain(self):
        v,_=classify({"closed_trades":6,"expectancy_r":.1,"profit_factor_r":1.4,"max_drawdown_r":2},"RESEARCH");self.assertEqual(v,Verdict.UNCERTAIN)
    def test_validation_pass(self):
        v,_=classify({"closed_trades":40,"expectancy_r":.04,"profit_factor_r":1.08,"max_drawdown_r":8},"VALIDATION");self.assertEqual(v,Verdict.PASS)
    def test_negative_rejected(self):
        v,_=classify({"closed_trades":100,"expectancy_r":-.05,"profit_factor_r":.9,"max_drawdown_r":10},"RESEARCH");self.assertEqual(v,Verdict.REJECTED)
if __name__=="__main__":unittest.main()
