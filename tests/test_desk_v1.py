import unittest
from datetime import date
from trading_lab.desk_v1 import (
    V1Family,V1StrategySpec,V1SideMode,RegimeFilter,all_failures,V1GatePolicy,
    SUPPORTED_INSTRUMENTS,
)
from trading_lab.portfolio_v1 import PortfolioLeg,aggregate
from trading_lab.propfirm import FTMO_2STEP_STEP1,PropDay,simulate_prop


class V1ContractTests(unittest.TestCase):
    def test_universe_is_expanded(self):
        self.assertGreaterEqual(len(SUPPORTED_INSTRUMENTS),13)
        self.assertIn("XAGUSD",SUPPORTED_INSTRUMENTS)
        self.assertIn("DAX",SUPPORTED_INSTRUMENTS)
        self.assertIn("WTI",SUPPORTED_INSTRUMENTS)

    def test_families_are_expanded(self):
        self.assertGreaterEqual(len(V1Family),8)

    def test_spec_roundtrip(self):
        s=V1StrategySpec(V1Family.LIQUIDITY_SWEEP,"XAUUSD",15,10,40,.2,1.5,2,20,V1SideMode.BOTH,7,20,RegimeFilter.HIGH_VOL)
        self.assertEqual(V1StrategySpec.from_mapping(s.as_dict()),s)

    def test_all_failure_reasons(self):
        f=all_failures({"closed_trades":3,"expectancy_r":-.2,"profit_factor_r":.5,"max_drawdown_r":50},V1GatePolicy())
        self.assertEqual(len(f),4)


class PropTests(unittest.TestCase):
    def test_ftmo_step1_pass(self):
        initial=100000
        days=[
            PropDay(100000,99500,102000,True),
            PropDay(102000,101000,104000,True),
            PropDay(104000,103000,107000,True),
            PropDay(107000,106000,110500,True),
        ]
        r=simulate_prop(days,FTMO_2STEP_STEP1,initial)
        self.assertTrue(r.passed)

    def test_daily_breach(self):
        r=simulate_prop([PropDay(100000,94000,95000,True)],FTMO_2STEP_STEP1,100000)
        self.assertTrue(r.breached)
        self.assertEqual(r.reason,"MAX_DAILY_LOSS")


class PortfolioTests(unittest.TestCase):
    def test_aggregate(self):
        d1=date(2026,1,2);d2=date(2026,1,3)
        p=aggregate([
            PortfolioLeg("a",{d1:.01,d2:-.005},daily_trades={d1:1,d2:1}),
            PortfolioLeg("b",{d1:0,d2:.01},daily_trades={d1:0,d2:1}),
        ])
        self.assertEqual(p["days"],2)
        self.assertEqual(p["trades_per_day"],1.5)


if __name__=="__main__": unittest.main()
