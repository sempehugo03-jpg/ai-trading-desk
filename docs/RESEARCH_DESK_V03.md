# Research Desk V0.3 — Parallel Scientific Search

## Objective
The north star is unchanged: investigate whether a multi-strategy portfolio can
sustain roughly 10% net/month with >=1 portfolio trade/day on average and an
explicitly controlled drawdown. The target is a research objective, not a promise.

## What changed
V0.3 stops treating research as one LLM inventing one batch at a time.

Independent agents now work concurrently:
- Gold specialist
- US-index specialist
- FX-session specialist
- Frequency-balance specialist
- Contrarian search specialist
- Robustness-first specialist
- Controlled Mutation Agent for informative near-misses

The system uses approximately 70% exploration / 30% controlled mutation by
default. Mutation is hard-limited: same family and instrument, only 1–2 other
fields may change.

## Learning from failure
A new campaign can consume non-blind evidence from earlier campaign DBs with
`--memory-db`. It receives specs + objective metrics + rejection reasons only.
Blind raw data never enters this memory.

Quant gates now return *all* reasons for failure, e.g. a candidate can be both
too rare and negative-expectancy. This prevents the Researcher from learning
from a misleading single first-failure label.

## Parallelism policy
LLM hypothesis calls and independent qualitative reviews run concurrently.
Heavy multi-year Python backtests remain sequential on the 2-core Codespace by
design: running several copies simultaneously would duplicate multi-million-row
market datasets in RAM and can be slower or crash the machine.

This is deliberate: exploit parallel AI where it helps; do not parallelize a
memory bottleneck merely because parallelism is available.

## Suggested next campaign
After Campaign 001:

```bash
python scripts/run_agent_desk.py \
  --db runs/campaign-002.sqlite3 \
  --memory-db runs/campaign-001.sqlite3 \
  --cycles 250 \
  --batch-size 12 \
  --max-candidates 60 \
  --parallel-researchers 6 \
  --exploration-fraction 0.70 \
  --confirm-api-costs
```

Do not interpret an IS survivor as a trading system. Promotion still requires
VALIDATION -> OOS -> WALK_FORWARD -> STRESS -> BLIND -> SHADOW.
