"""Run the actual tests plus two full synthetic replays. Preserve audit outputs."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
import platform
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from trading_lab.demo import run_demo  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True, help='New output directory; never overwritten')
    args = parser.parse_args()
    out = Path(args.out).resolve()
    if out.exists():
        parser.error('Output directory already exists; preserve it and choose a new name')
    out.mkdir(parents=True)
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    log = stream.getvalue()
    (out / 'tests.txt').write_text(log, encoding='utf-8')
    report = {
        'generated_at_utc': datetime.now(UTC).isoformat(),
        'python': platform.python_version(),
        'tests_run': result.testsRun,
        'failures': len(result.failures),
        'errors': len(result.errors),
        'skipped': len(result.skipped),
        'tests_passed': result.wasSuccessful(),
        'scope': 'Software tests and synthetic simulation only; no profitability validation.',
        'execution_environment': 'GITHUB_ACTIONS' if os.environ.get('GITHUB_ACTIONS') == 'true' else 'LOCAL',
        'publication_status_checked': False,
    }
    if result.wasSuccessful():
        a = run_demo(out / 'replay-a')
        b = run_demo(out / 'replay-b')
        compared = {}
        for name in ('report.json', 'trades.json', 'equity.json', 'journal.jsonl', 'synthetic_m1.csv'):
            left = (out / 'replay-a' / name).read_bytes()
            right = (out / 'replay-b' / name).read_bytes()
            compared[name] = {'identical': left == right, 'sha256': hashlib.sha256(left).hexdigest()}
        report['replay_artifacts'] = compared
        report['two_full_replays_identical'] = a == b and all(v['identical'] for v in compared.values())
        report['synthetic_bar_count'] = a['source_bar_count']
        report['journal_records_per_replay'] = a['journal_records']
    report['technical_checks_passed'] = report['tests_passed'] and report.get('two_full_replays_identical', False)
    (out / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['technical_checks_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
