# Research Desk V0.1

Research Desk V0.1 wires real contradictory agent roles into the V0.3 promotion pipeline while keeping P&L calculation deterministic.

## Safety architecture

Agents can propose only a bounded JSON strategy DSL. They cannot emit Python that the simulator executes. Quantitative metrics are calculated by trusted local code. Red Team, Risk and Regime agents may veto a candidate but cannot override a failed quantitative gate.

`RESEARCH -> VALIDATION -> OOS -> WALK_FORWARD -> STRESS -> BLIND -> SHADOW`

Research may continue while older candidates wait at BLIND or SHADOW. A blocked candidate does not freeze the queue.

## Continuous agent team

- Researcher: generates diverse falsifiable specs.
- Quant: deterministic IS/validation/OOS metrics.
- Red Team: adversarial review at validation/OOS.
- Regime: challenges temporal stability after walk-forward testing.
- Risk: vetoes fragile stress-test survivors.
- Blind Evaluator: remains isolated in the V0.3 one-shot blind service.
- Shadow + Portfolio: remain blocked until future paper data exists.

The north star remains ~10% net/month and >=1 portfolio trade/day, but no individual candidate is optimized directly to that number and the desk cannot mark it validated without blind + paper-live evidence.

## OpenAI API

The provider uses the Responses API with strict JSON Schema outputs and `store=false`. By default it uses `gpt-5.6-luna`; override globally with `TRADING_DESK_MODEL` or per role, e.g. `TRADING_DESK_MODEL_RED_TEAM`.

No API request occurs unless `OPENAI_API_KEY` exists and `scripts/run_agent_desk.py` is launched with `--confirm-api-costs`.

## Run a finite research batch

```bash
python scripts/run_agent_desk.py --cycles 50 --confirm-api-costs
```

For supervised continuous operation:

```bash
python scripts/run_agent_desk.py --forever --confirm-api-costs
```

A Codespace is not guaranteed to remain alive 24/5. Persistent deployment is a later infrastructure gate. There is still no broker/live-order adapter.
