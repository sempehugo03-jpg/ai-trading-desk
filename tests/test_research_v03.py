import tempfile
import unittest
from pathlib import Path

from trading_lab.blind import BlindBoxVault, BlindEvaluator
from trading_lab.research import (
    AgentRole, ContinuousResearchLoop, ROLE_PLAN, ResearchStore,
    Stage, StageOutcome,
)
from trading_lab.target import NorthStar, TargetStatus


class ResearchLoopTests(unittest.TestCase):
    def test_candidate_advances_all_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ResearchStore(Path(tmp)/"r.sqlite3")
            store.add_candidate("c1", "momentum", 1, {"x": 1})
            def ok(candidate, roles):
                return StageOutcome(True, {"expectancy_r": .1}, {"roles": [r.value for r in roles]})
            handlers = {s: ok for s in (Stage.RESEARCH,Stage.VALIDATION,Stage.OOS,Stage.WALK_FORWARD,Stage.STRESS,Stage.BLIND,Stage.SHADOW)}
            loop = ContinuousResearchLoop(store, handlers)
            self.assertEqual(loop.run_cycles(20), 7)
            self.assertEqual(store.get("c1").stage, Stage.PROMOTED)
            self.assertEqual(len(store.events("c1")), 8)  # creation + seven stages

    def test_failure_rejects_immediately(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=ResearchStore(Path(tmp)/"r.sqlite3")
            store.add_candidate("c1","mean-reversion",1,{})
            loop=ContinuousResearchLoop(store,{Stage.RESEARCH: lambda c,r: StageOutcome(False,{}, {},"bad")})
            self.assertTrue(loop.step())
            self.assertEqual(store.get("c1").stage,Stage.REJECTED)

    def test_handler_exception_does_not_promote(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=ResearchStore(Path(tmp)/"r.sqlite3")
            store.add_candidate("c1","x",1,{})
            def boom(c,r): raise RuntimeError("infra")
            loop=ContinuousResearchLoop(store,{Stage.RESEARCH:boom})
            with self.assertRaises(RuntimeError): loop.step()
            self.assertEqual(store.get("c1").stage,Stage.RESEARCH)

    def test_role_plan_is_contradictory_by_design(self):
        self.assertIn(AgentRole.RED_TEAM, ROLE_PLAN[Stage.VALIDATION])
        self.assertIn(AgentRole.RISK, ROLE_PLAN[Stage.STRESS])
        self.assertEqual(ROLE_PLAN[Stage.BLIND][0], AgentRole.BLIND_EVALUATOR)


class BlindBoxTests(unittest.TestCase):
    def test_box_is_one_shot_and_batch_is_frozen(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault=BlindBoxVault(Path(tmp)/"blind.sqlite3")
            vault.seal("box-A","a"*64)
            h=vault.reserve_batch("batch-1","box-A",["c1","c2"])
            self.assertEqual(len(h),64)
            self.assertEqual(vault.frozen_candidates("batch-1"),("c1","c2"))
            with self.assertRaises(RuntimeError):
                vault.reserve_batch("batch-2","box-A",["c3"])
            evaluator=BlindEvaluator(vault,{"box-A":{"secret_rows":[1,2,3],"secret_period":"hidden"}})
            out=evaluator.evaluate_batch("batch-1","box-A",lambda cid,data:{"pass":cid=="c1","trades":[1],"start":"SECRET","score":1})
            self.assertEqual(vault.status("box-A"),"RETIRED")
            public=out.public_view()
            self.assertNotIn("trades",public["results"]["c1"])
            self.assertNotIn("start",public["results"]["c1"])
            with self.assertRaises(RuntimeError):
                evaluator.evaluate_batch("batch-1","box-A",lambda cid,data:{})

    def test_duplicate_candidates_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            v=BlindBoxVault(Path(tmp)/"b.sqlite3")
            v.seal("b","b"*64)
            with self.assertRaises(ValueError): v.reserve_batch("x","b",["c1","c1"])


class TargetTests(unittest.TestCase):
    def test_target_cannot_validate_without_drawdown_limit(self):
        n=NorthStar()
        status, why=n.assess({})
        self.assertEqual(status,TargetStatus.INSUFFICIENT_DATA)
        self.assertIn("max_drawdown_limit_not_defined",why)

    def test_target_validates_only_with_all_evidence(self):
        n=NorthStar(max_drawdown_limit=.10,min_live_months=3)
        evidence={
            "paper_live_months":3,
            "paper_live_mean_monthly_net_return":.101,
            "paper_live_trades_per_day":1.2,
            "paper_live_max_drawdown":.08,
            "blind_pass":True,"oos_pass":True,"walk_forward_pass":True,
            "stress_pass":True,"risk_rules_respected":True,
        }
        self.assertEqual(n.assess(evidence)[0],TargetStatus.VALIDATED)
        evidence["blind_pass"]=False
        status,why=n.assess(evidence)
        self.assertEqual(status,TargetStatus.NOT_VALIDATED)
        self.assertIn("blind_pass",why)


if __name__ == "__main__":
    unittest.main()
