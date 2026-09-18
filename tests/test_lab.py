from __future__ import annotations
import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError, asdict, replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from trading_lab.data import data_fingerprint, load_csv, resample_closed, validate_m1, write_csv
from trading_lab.demo import control_strategy, run_demo, synthetic_bars
from trading_lab.engine import backtest
from trading_lab.journal import HashJournal, canonical
from trading_lab.metrics import summarize
from trading_lab.models import Bar, Config, DataError, Side, Signal, utc

START = datetime(2025, 1, 6, 12, tzinfo=UTC)


def sequence(rows, *, start=START, spread=0.0):
    return tuple(Bar(start + timedelta(minutes=i), *row, spread) for i, row in enumerate(rows))


def config(**changes):
    values = dict(slippage=0.0, commission_per_unit_side=0.0, max_daily_loss=.05,
                  max_drawdown=.15, session_start_utc=0, session_end_utc=24,
                  max_spread_to_stop=.9)
    values.update(changes)
    return Config(**values)


def once(signal, at=1):
    return lambda history: signal if len(history) == at else None


class DataTests(unittest.TestCase):
    def test_empty_rejected(self):
        with self.assertRaises(DataError):
            validate_m1(())

    def test_naive_timestamp_rejected(self):
        with self.assertRaises(DataError):
            Bar(datetime(2025, 1, 1), 1, 2, 1, 1, 0)

    def test_nan_price_rejected(self):
        with self.assertRaises(ValueError):
            Bar(START, float('nan'), 2, 1, 1, 0)

    def test_infinite_price_rejected(self):
        with self.assertRaises(ValueError):
            Bar(START, 1, float('inf'), 1, 1, 0)

    def test_negative_spread_rejected(self):
        with self.assertRaises(ValueError):
            Bar(START, 1, 2, 1, 1, -.1)

    def test_infinite_spread_rejected(self):
        with self.assertRaises(ValueError):
            Bar(START, 1, 2, 1, 1, float('inf'))

    def test_bad_ohlc_rejected(self):
        with self.assertRaises(DataError):
            Bar(START, 4, 3, 1, 2, 0)

    def test_zero_price_rejected(self):
        with self.assertRaises(ValueError):
            Bar(START, 0, 1, 0, 1, 0)

    def test_timestamp_not_minute_aligned(self):
        with self.assertRaises(DataError):
            Bar(START + timedelta(seconds=1), 1, 1, 1, 1, 0)

    def test_bool_price_rejected(self):
        with self.assertRaises(ValueError):
            Bar(START, True, 1, 1, 1, 0)

    def test_duplicate_timestamp_rejected(self):
        b = sequence([(100, 101, 99, 100)])[0]
        with self.assertRaises(DataError):
            validate_m1((b, b))

    def test_missing_minute_rejected(self):
        b = sequence([(100, 101, 99, 100)] * 3)
        with self.assertRaises(DataError):
            validate_m1((b[0], b[2]))

    def test_unordered_rejected(self):
        b = sequence([(100, 101, 99, 100)] * 2)
        with self.assertRaises(DataError):
            validate_m1(tuple(reversed(b)))

    def test_offset_normalizes_to_utc(self):
        value = datetime(2025, 1, 6, 14, tzinfo=timezone(timedelta(hours=2)))
        self.assertEqual(utc(value), START)

    def test_dst_spring_forward_keeps_continuity(self):
        b1 = Bar(datetime.fromisoformat('2025-03-30T01:59:00+01:00'), 1, 1, 1, 1, 0)
        b2 = Bar(datetime.fromisoformat('2025-03-30T03:00:00+02:00'), 1, 1, 1, 1, 0)
        self.assertEqual(len(validate_m1((b1, b2))), 2)

    def test_csv_round_trip(self):
        bars = sequence([(100, 101, 99, 100)] * 4, spread=.1)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bars.csv'
            write_csv(path, bars)
            self.assertEqual(load_csv(path), bars)
            self.assertEqual(data_fingerprint(bars), data_fingerprint(load_csv(path)))

    def test_csv_missing_spread_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.csv'
            path.write_text('timestamp_open,bid_open,bid_high,bid_low,bid_close\n2025-01-01T00:00:00Z,1,1,1,1\n')
            with self.assertRaises(DataError):
                load_csv(path)

    def test_csv_naive_time_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.csv'
            path.write_text('timestamp_open,bid_open,bid_high,bid_low,bid_close,spread_price\n2025-01-01T00:00:00,1,1,1,1,0\n')
            with self.assertRaises(DataError):
                load_csv(path)

    def test_csv_duplicate_headers_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.csv'
            path.write_text('timestamp_open,bid_open,bid_high,bid_low,bid_close,spread_price,spread_price\n')
            with self.assertRaises(DataError):
                load_csv(path)

    def test_csv_nan_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.csv'
            path.write_text('timestamp_open,bid_open,bid_high,bid_low,bid_close,spread_price\n2025-01-01T00:00:00Z,nan,1,1,1,0\n')
            with self.assertRaises(DataError):
                load_csv(path)

    def test_csv_empty_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.csv'
            path.write_text('')
            with self.assertRaises(DataError):
                load_csv(path)

    def test_closed_five_minute_aggregation(self):
        bars = sequence([(100+i, 102+i, 99+i, 101+i) for i in range(5)])
        out = resample_closed(bars, 5, START + timedelta(minutes=5))
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0].open, out[0].high, out[0].low, out[0].close), (100, 106, 99, 105))
        self.assertEqual(out[0].close_time, START + timedelta(minutes=5))

    def test_incomplete_last_bucket_not_emitted(self):
        bars = sequence([(100, 101, 99, 100)] * 7)
        self.assertEqual(len(resample_closed(bars, 5, bars[-1].close_time)), 1)

    def test_partial_first_bucket_not_emitted(self):
        bars = sequence([(100, 101, 99, 100)] * 7, start=START + timedelta(minutes=3))
        out = resample_closed(bars, 5, bars[-1].close_time)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].open_time, START + timedelta(minutes=5))

    def test_as_of_excludes_future_high(self):
        bars = sequence([(100, 101, 99, 100)] * 5 + [(100, 10000, 99, 100)] * 5)
        out = resample_closed(bars, 5, START + timedelta(minutes=5))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].high, 101)

    def test_open_source_bar_not_available(self):
        bars = sequence([(100, 101, 99, 100)] * 5)
        self.assertEqual(resample_closed(bars, 5, START + timedelta(minutes=4, seconds=59)), ())

    def test_all_required_timeframes(self):
        bars = sequence([(100, 101, 99, 100)] * 240)
        for minutes, expected in ((5, 48), (15, 16), (60, 4), (240, 1)):
            with self.subTest(minutes=minutes):
                self.assertEqual(len(resample_closed(bars, minutes, bars[-1].close_time)), expected)

    def test_bad_timeframe_rejected(self):
        with self.assertRaises(ValueError):
            resample_closed(sequence([(1, 1, 1, 1)]), 3, START)

    def test_fingerprint_changes_on_price_change(self):
        bars = sequence([(100, 101, 99, 100)] * 2)
        changed = (*bars[:-1], replace(bars[-1], high=102))
        self.assertNotEqual(data_fingerprint(bars), data_fingerprint(changed))


class EngineTests(unittest.TestCase):
    def test_deterministic_replay(self):
        bars = synthetic_bars(180)
        self.assertEqual(backtest(bars, control_strategy), backtest(bars, control_strategy))

    def test_immutable_past_only_strategy_input(self):
        seen = []
        def strategy(history):
            self.assertIsInstance(history, tuple)
            with self.assertRaises(FrozenInstanceError):
                history[-1].close = 999
            seen.append(len(history))
            return None
        backtest(sequence([(100, 101, 99, 100)] * 3), strategy, config())
        self.assertEqual(seen, [1, 2, 3])

    def test_no_same_signal_bar_execution(self):
        bars = sequence([(100, 110, 90, 100), (100, 100.5, 99.5, 100)])
        result = backtest(bars, once(Signal(Side.LONG, 99, 102)), config())
        self.assertEqual(len(result.trades), 0)
        self.assertEqual(result.open_positions, 1)
        entry = next(e for e in result.events if e['kind'] == 'ENTRY')
        self.assertEqual(entry['simulated_time'], bars[1].open_time)

    def test_order_at_end_is_not_filled(self):
        result = backtest(sequence([(100, 101, 99, 100)]), once(Signal(Side.LONG, 99, 102)), config())
        self.assertEqual(result.unfilled_at_end, 1)
        self.assertEqual(len(result.trades), 0)
        self.assertFalse(any(e['kind'] == 'ENTRY' for e in result.events))

    def test_long_target(self):
        result = backtest(sequence([(100, 100, 100, 100), (100, 103, 99.5, 102)]), once(Signal(Side.LONG, 99, 102)), config())
        self.assertAlmostEqual(result.trades[0].r_multiple, 2)
        self.assertEqual(result.trades[0].reason, 'TARGET')

    def test_short_target(self):
        result = backtest(sequence([(100, 100, 100, 100), (100, 100.5, 97, 98)]), once(Signal(Side.SHORT, 101, 98)), config())
        self.assertAlmostEqual(result.trades[0].r_multiple, 2)

    def test_ambiguous_long_stop_first(self):
        result = backtest(sequence([(100, 100, 100, 100), (100, 103, 98, 100)]), once(Signal(Side.LONG, 99, 102)), config())
        self.assertTrue(result.trades[0].ambiguous)
        self.assertAlmostEqual(result.trades[0].r_multiple, -1)

    def test_ambiguous_short_stop_first(self):
        result = backtest(sequence([(100, 100, 100, 100), (100, 102, 97, 100)]), once(Signal(Side.SHORT, 101, 98)), config())
        self.assertTrue(result.trades[0].ambiguous)
        self.assertAlmostEqual(result.trades[0].r_multiple, -1)

    def test_long_adverse_gap_stop_uses_gap_price(self):
        bars = sequence([(100, 100, 100, 100), (100, 100.5, 99.5, 100), (95, 96, 94, 95)])
        result = backtest(bars, once(Signal(Side.LONG, 99, 102)), config())
        self.assertEqual(result.trades[0].reason, 'STOP_GAP')
        self.assertAlmostEqual(result.trades[0].r_multiple, -5)
        self.assertEqual(result.trades[0].exit, 95)

    def test_short_adverse_gap_stop_uses_gap_price(self):
        bars = sequence([(100, 100, 100, 100), (100, 100.5, 99.5, 100), (105, 106, 104, 105)])
        result = backtest(bars, once(Signal(Side.SHORT, 101, 98)), config())
        self.assertEqual(result.trades[0].reason, 'STOP_GAP')
        self.assertAlmostEqual(result.trades[0].r_multiple, -5)

    def test_target_known_at_open_precedes_intrabar_stop(self):
        bars = sequence([(100, 100, 100, 100), (100, 100.5, 99.5, 100), (105, 106, 98, 100)])
        result = backtest(bars, once(Signal(Side.LONG, 99, 102)), config())
        self.assertEqual(result.trades[0].reason, 'TARGET_GAP')
        self.assertEqual(result.trades[0].exit, 102)  # not the favorable open of 105
        self.assertFalse(result.trades[0].ambiguous)

    def test_short_gap_target_conservative_limit(self):
        bars = sequence([(100, 100, 100, 100), (100, 100.5, 99.5, 100), (95, 102, 94, 100)])
        result = backtest(bars, once(Signal(Side.SHORT, 101, 98)), config())
        self.assertEqual(result.trades[0].reason, 'TARGET_GAP')
        self.assertEqual(result.trades[0].exit, 98)

    def test_gap_invalidates_entry(self):
        bars = sequence([(100, 100, 100, 100), (105, 106, 104, 105)])
        result = backtest(bars, once(Signal(Side.LONG, 99, 102)), config())
        self.assertEqual(result.trades, ())
        self.assertTrue(any(e.get('reason') == 'INVALID_ENTRY_AFTER_GAP' for e in result.events))

    def test_short_target_requires_ask_touch(self):
        bars = sequence([(100, 100, 100, 100), (100, 100.5, 98, 99)], spread=.2)
        result = backtest(bars, once(Signal(Side.SHORT, 102, 98)), config())
        self.assertEqual(result.trades, ())
        self.assertEqual(result.open_positions, 1)

    def test_short_stop_uses_ask(self):
        bars = sequence([(100, 100, 100, 100), (100, 100.9, 99.5, 100)], spread=.2)
        result = backtest(bars, once(Signal(Side.SHORT, 101, 98)), config())
        self.assertEqual(result.trades[0].reason, 'STOP')

    def test_long_entry_uses_ask_and_exit_uses_bid(self):
        bars = sequence([(100, 100, 100, 100), (100, 102.2, 99.5, 102)], spread=.2)
        result = backtest(bars, once(Signal(Side.LONG, 99, 102)), config())
        self.assertEqual(result.trades[0].entry, 100.2)
        self.assertEqual(result.trades[0].exit, 102)

    def test_costs_reduce_same_trade_return(self):
        bars = sequence([(100, 100, 100, 100), (100, 103, 99.5, 102)], spread=.1)
        strat = once(Signal(Side.LONG, 99, 102))
        clean = backtest(bars, strat, config())
        costly = backtest(bars, strat, config(slippage=.05, commission_per_unit_side=.01))
        self.assertLess(costly.trades[0].r_multiple, clean.trades[0].r_multiple)

    def test_cost_inclusive_stop_is_minus_one_r(self):
        bars = sequence([(100, 100, 100, 100), (100, 100.5, 98, 99)], spread=.1)
        result = backtest(bars, once(Signal(Side.LONG, 99, 102)), config(slippage=.05, commission_per_unit_side=.01))
        self.assertAlmostEqual(result.trades[0].r_multiple, -1)

    def test_short_cost_inclusive_stop_is_minus_one_r(self):
        bars = sequence([(100, 100, 100, 100), (100, 102, 99.5, 101)], spread=.1)
        result = backtest(bars, once(Signal(Side.SHORT, 101, 98)), config(slippage=.05, commission_per_unit_side=.01))
        self.assertAlmostEqual(result.trades[0].r_multiple, -1)

    def test_ledger_reconciles_after_fees(self):
        bars = sequence([(100, 100, 100, 100), (100, 103, 99.5, 102)], spread=.1)
        result = backtest(bars, once(Signal(Side.LONG, 99, 102)), config(slippage=.05, commission_per_unit_side=.01))
        self.assertAlmostEqual(result.final_cash, result.initial_equity + sum(t.pnl_quote for t in result.trades))
        self.assertAlmostEqual(result.final_equity, result.final_cash)

    def test_time_stop(self):
        bars = sequence([(100, 100, 100, 100), (100, 100.5, 99.5, 100.25)])
        result = backtest(bars, once(Signal(Side.LONG, 99, 102, 1)), config())
        self.assertEqual(result.trades[0].reason, 'TIME_STOP')
        self.assertEqual(result.trades[0].exit, 100.25)

    def test_intraday_session_close(self):
        bars = sequence([(100, 100, 100, 100), (100, 100.5, 99.5, 100)], start=START.replace(hour=19, minute=58))
        result = backtest(bars, once(Signal(Side.LONG, 99, 102)), config(session_end_utc=20))
        self.assertEqual(result.trades[0].reason, 'SESSION_END')
        self.assertEqual(result.open_positions, 0)

    def test_midnight_flat_even_for_all_day_session(self):
        bars = sequence([(100, 100, 100, 100), (100, 100.5, 99.5, 100)], start=START.replace(hour=23, minute=58))
        result = backtest(bars, once(Signal(Side.LONG, 99, 102)), config(session_start_utc=0, session_end_utc=24))
        self.assertEqual(result.trades[0].reason, 'SESSION_END')
        self.assertEqual(result.open_positions, 0)

    def test_no_weekend_entries(self):
        bars = sequence([(100, 100, 100, 100)] * 4, start=datetime(2025, 1, 5, 12, tzinfo=UTC))
        result = backtest(bars, lambda h: Signal(Side.LONG, 99, 102), config())
        self.assertFalse(any(e['kind'] == 'ENTRY' for e in result.events))
        self.assertEqual(result.observed_session_days, 0)

    def test_large_spread_veto(self):
        bars = sequence([(100, 101, 99, 100)] * 3, spread=2)
        result = backtest(bars, once(Signal(Side.LONG, 99, 110)), config(max_spread_to_stop=.1))
        self.assertTrue(any(e.get('reason') == 'SPREAD_TOO_HIGH' for e in result.events))
        self.assertFalse(any(e['kind'] == 'ENTRY' for e in result.events))

    def test_one_position_max(self):
        bars = sequence([(100, 100.1, 99.9, 100)] * 10)
        result = backtest(bars, lambda h: Signal(Side.LONG, 99, 102), config())
        self.assertEqual(sum(e['kind'] == 'ENTRY' for e in result.events), 1)
        self.assertEqual(result.open_positions, 1)

    def test_daily_risk_floor_blocks_new_entry(self):
        bars = sequence([(100, 100, 100, 100), (100, 100.5, 98, 99), (100, 100.5, 99.5, 100), (100, 100.5, 99.5, 100)])
        result = backtest(bars, lambda h: Signal(Side.LONG, 99, 102), config(risk_fraction=.005, max_daily_loss=.005))
        self.assertEqual(sum(e['kind'] == 'ENTRY' for e in result.events), 1)
        self.assertTrue(any(e.get('reason') in ('RISK_HALTED', 'DAILY_RISK_BUDGET') for e in result.events))

    def test_mark_to_market_drawdown_closes_and_halts(self):
        bars = sequence([(100, 100, 100, 100), (100, 130, 99.5, 130), (130, 130, 125, 125), (125, 125, 124, 125)])
        result = backtest(bars, lambda h: Signal(Side.LONG, 99, 200), config(max_daily_loss=.005, max_drawdown=.01))
        self.assertEqual(result.trades[0].reason, 'RISK_CLOSE')
        self.assertEqual(sum(e['kind'] == 'ENTRY' for e in result.events), 1)

    def test_open_position_marked_not_fabricated_closed(self):
        bars = sequence([(100, 100, 100, 100), (100, 100.5, 99.5, 100.4)])
        result = backtest(bars, once(Signal(Side.LONG, 99, 102)), config())
        self.assertEqual(result.open_positions, 1)
        self.assertEqual(len(result.trades), 0)
        self.assertGreater(result.final_equity, result.final_cash)

    def test_missing_data_stops_simulation(self):
        bars = sequence([(100, 101, 99, 100)] * 3)
        with self.assertRaises(DataError):
            backtest((bars[0], bars[2]), lambda h: None)

    def test_invalid_strategy_response_fails_closed(self):
        with self.assertRaises(TypeError):
            backtest(sequence([(100, 101, 99, 100)]), lambda h: 'BUY', config())

    def test_future_mutation_cannot_change_prior_decisions(self):
        bars = synthetic_bars(60)
        changed = bars[:30] + tuple(replace(b, high=b.high+10) for b in bars[30:])
        a, b = backtest(bars, control_strategy), backtest(changed, control_strategy)
        cutoff = bars[29].close_time
        def prefix(result):
            return [e for e in result.events if e['kind'] not in ('RUN_START', 'RUN_END') and e['simulated_time'] <= cutoff]
        self.assertEqual(prefix(a), prefix(b))

    def test_decision_record_precedes_entry_and_exit(self):
        result = backtest(sequence([(100, 100, 100, 100), (100, 103, 99.5, 102)]), once(Signal(Side.LONG, 99, 102)), config())
        kinds = [e['kind'] for e in result.events]
        self.assertLess(kinds.index('ORDER_SUBMITTED'), kinds.index('ENTRY'))
        self.assertLess(kinds.index('ENTRY'), kinds.index('EXIT'))

    def test_invalid_risk_configuration(self):
        with self.assertRaises(ValueError):
            Config(risk_fraction=.02, max_daily_loss=.01)
        with self.assertRaises(ValueError):
            Config(slippage=float('nan'))
        with self.assertRaises(ValueError):
            Config(session_start_utc=20, session_end_utc=7)


class JournalTests(unittest.TestCase):
    def test_append_verify_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'journal.jsonl'
            journal = HashJournal(path)
            journal.append({'kind': 'A', 'time': START})
            head = journal.append({'kind': 'B'})
            self.assertEqual(HashJournal(path).verify(head), (2, head))

    def test_payload_tampering_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'journal.jsonl'
            journal = HashJournal(path)
            journal.append({'kind': 'A'})
            path.write_text(path.read_text().replace('"A"', '"B"'))
            with self.assertRaises(ValueError):
                HashJournal(path)

    def test_duplicate_json_key_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'journal.jsonl'
            j = HashJournal(path)
            j.append({'n': 1})
            path.write_text(path.read_text().replace('"n":1', '"n":999,"n":1'))
            with self.assertRaises(ValueError):
                j.verify()

    def test_reordering_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'journal.jsonl'
            j = HashJournal(path)
            j.append({'n': 1})
            j.append({'n': 2})
            lines = path.read_text().splitlines(True)
            path.write_text(''.join(reversed(lines)))
            with self.assertRaises(ValueError):
                j.verify()

    def test_tail_deletion_needs_external_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'journal.jsonl'
            j = HashJournal(path)
            j.append({'n': 1})
            head = j.append({'n': 2})
            path.write_text(path.read_text().splitlines(True)[0])
            self.assertEqual(j.verify()[0], 1)  # honest limitation: valid prefix alone passes
            with self.assertRaises(ValueError):
                j.verify(head)

    def test_nan_journal_event_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = HashJournal(Path(tmp) / 'journal.jsonl')
            with self.assertRaises(ValueError):
                j.append({'x': float('nan')})
            self.assertEqual(j.verify(), (0, 'GENESIS'))

    def test_corrupt_journal_prevents_append(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'journal.jsonl'
            j = HashJournal(path)
            j.append({'n': 1})
            path.write_text(path.read_text()[:-1])
            with self.assertRaises(ValueError):
                j.append({'n': 2})

    def test_busy_journal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'journal.jsonl'
            j = HashJournal(path)
            path.with_suffix('.jsonl.lock').write_text('busy')
            with self.assertRaises(RuntimeError):
                j.append({'n': 1})

    def test_simulation_events_are_journaled_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = HashJournal(Path(tmp) / 'journal.jsonl')
            result = backtest(sequence([(100, 100, 100, 100)] * 2), lambda h: None, config(), journal=j)
            self.assertEqual(j.verify()[0], len(result.events))


class MetricsAndIntegrationTests(unittest.TestCase):
    def test_no_trades_metrics_are_not_nan_or_infinity(self):
        result = backtest(sequence([(100, 100, 100, 100)] * 2), lambda h: None, config())
        metrics = summarize(result)
        self.assertIsNone(metrics['expectancy_r'])
        self.assertIsNone(metrics['profit_factor_quote'])
        json.dumps(metrics, allow_nan=False)

    def test_all_winners_pf_is_explicitly_undefined(self):
        result = backtest(sequence([(100, 100, 100, 100), (100, 103, 99.5, 102)]), once(Signal(Side.LONG, 99, 102)), config())
        self.assertIsNone(summarize(result)['profit_factor_quote'])
        self.assertEqual(summarize(result)['profit_factor_status'], 'UNDEFINED_NO_GROSS_LOSS')

    def test_drawdown_starts_at_initial_equity(self):
        result = backtest(sequence([(100, 100, 100, 100), (100, 100.5, 98, 99)]), once(Signal(Side.LONG, 99, 102)), config())
        metrics = summarize(result)
        self.assertAlmostEqual(metrics['max_drawdown_closed_trades_r'], 1)
        self.assertAlmostEqual(metrics['max_drawdown_m1_close_pct'], .25)

    def test_canonical_results_repeat(self):
        bars = synthetic_bars(100)
        a = canonical(asdict(backtest(bars, control_strategy)))
        b = canonical(asdict(backtest(bars, control_strategy)))
        self.assertEqual(a, b)

    def test_no_performance_target_is_claimed(self):
        result = backtest(sequence([(100, 100, 100, 100)] * 2), lambda h: None, config())
        self.assertFalse(summarize(result)['monthly_target_demonstrated'])
        self.assertFalse(summarize(result)['robustness_demonstrated'])

    def test_cli_demo_end_to_end_and_preserves_past_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'new'
            csv_path = Path(tmp) / 'input.csv'
            write_csv(csv_path, synthetic_bars(60))
            report = run_demo(out, csv_path)
            self.assertTrue(report['identical_replays'])
            self.assertEqual(report['data_kind'], 'USER_CSV_NOT_PROVIDER_VERIFIED')
            self.assertTrue((out / 'trades.json').exists())
            self.assertTrue((out / 'equity.json').exists())
            self.assertEqual(HashJournal(out / 'journal.jsonl').verify()[1], report['journal_head'])
            with self.assertRaises(FileExistsError):
                run_demo(out, csv_path)

    def test_invalid_data_creates_no_success_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / 'bad.csv'
            bad.write_text('bad\n')
            out = Path(tmp) / 'new'
            with self.assertRaises(DataError):
                run_demo(out, bad)
            self.assertFalse((out / 'report.json').exists())


if __name__ == '__main__':
    unittest.main()
