from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from trading_lab.agent_desk import AgentResearchDesk, DeskConfig
from trading_lab.agent_provider import FakeProvider
from trading_lab.demo import synthetic_bars
from trading_lab.engine import backtest
from trading_lab.models import Config
from trading_lab.research import ResearchStore
from trading_lab.strategy_dsl import (
    Family, SideMode, StrategySpec, compile_strategy, compile_strategy_cached,
)


def spec(family=Family.MOMENTUM, instrument="XAUUSD"):
    return StrategySpec(
        family, instrument, 15, 5, 20, .2, 1.5, 2.0, 10,
        SideMode.BOTH, 0, 24,
    )


class FastCompilerTests(unittest.TestCase):
    def test_cached_compiler_matches_legacy_signal_by_signal(self):
        bars = synthetic_bars(2500)
        for family in Family:
            s = spec(family)
            legacy = compile_strategy(s)
            fast = compile_strategy_cached(s, bars)
            history = []
            for bar in bars:
                history.append(bar)
                self.assertEqual(legacy(tuple(history)), fast(history), (family, bar.open_time))

    def test_fast_research_backtest_preserves_trade_results(self):
        bars = synthetic_bars(5000)
        s = spec(Family.MEAN_REVERSION)
        cfg = Config(
            session_start_utc=0, session_end_utc=24,
            slippage=0.0, commission_per_unit_side=0.0,
            max_daily_loss=.05, max_drawdown=.15, max_spread_to_stop=.9,
        )
        legacy = backtest(bars, compile_strategy(s), cfg, strategy_id="legacy")
        fast = backtest(
            bars, compile_strategy_cached(s, bars), cfg, strategy_id="fast",
            compact_events=True, copy_history=False,
        )
        self.assertEqual(legacy.trades, fast.trades)
        self.assertEqual(legacy.final_cash, fast.final_cash)
        self.assertEqual(legacy.final_equity, fast.final_equity)
        self.assertFalse(any(e["kind"] == "NO_TRADE" for e in fast.events))
        self.assertLess(len(fast.events), len(legacy.events))


class CampaignCapTests(unittest.TestCase):
    def test_total_candidate_cap_is_hard(self):
        def raw(family, instrument, fast):
            return {
                "family": family, "instrument": instrument, "timeframe_minutes": 15,
                "fast_lookback": fast, "slow_lookback": 40, "threshold_atr": .2,
                "stop_atr": 1.5, "target_r": 2.0, "max_holding_bars": 20,
                "side_mode": "BOTH", "session_start_utc": 7, "session_end_utc": 20,
            }
        response = {"strategies": [
            raw("MOMENTUM", "XAUUSD", 5),
            raw("MEAN_REVERSION", "EURUSD", 6),
            raw("BREAKOUT", "US500", 7),
            raw("MOMENTUM", "NAS100", 8),
            raw("MEAN_REVERSION", "GBPUSD", 9),
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            store = ResearchStore(Path(tmp) / "campaign.sqlite3")
            provider = FakeProvider([response])
            desk = AgentResearchDesk(store, provider, DeskConfig(proposal_batch_size=5, total_candidate_cap=3))
            self.assertEqual(desk.generate(), 3)
            self.assertEqual(desk.generate(), 0)
            self.assertEqual(len(store.pending()), 3)
            self.assertEqual(provider.calls, 1)


if __name__ == "__main__":
    unittest.main()
