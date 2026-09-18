# Continuous Research + Blind Box — V0.3

## Goal
V0.3 turns the laboratory into a persistent promotion pipeline. Research may run continuously; evidence gates remain non-negotiable.

The north star is still approximately **10% net/month and >=1 portfolio trade/day on average**, but V0.3 does **not** claim this is achieved or achievable at an acceptable risk level.

## Pipeline

`RESEARCH -> VALIDATION -> OOS -> WALK_FORWARD -> STRESS -> BLIND -> SHADOW -> PROMOTED`

A failure at any gate sends the candidate to `REJECTED`. Infrastructure errors do not promote or reject a candidate; it stays at the current stage for inspection.

## Agent roles

- Researcher: proposes formalizable candidates.
- Quant: computes objective metrics and statistical diagnostics.
- Red Team: searches for leakage, fragility, regime dependence and selection bias.
- Regime: tests behavior across market regimes.
- Risk: vetoes unacceptable exposure/fragility.
- Blind Evaluator: is the only role allowed to evaluate sealed datasets.
- Shadow: tracks future paper results.
- Portfolio: evaluates correlations and combined exposure.

The scheduler assigns contradictory roles by stage. A majority vote is never a promotion rule.

## Blind boxes

Blind data must be physically separated from the research agents in the production deployment. The V0.3 application contract adds:

1. metadata-only sealed boxes (fingerprint + opaque ID),
2. a candidate batch frozen **before** results are known,
3. one evaluation for that batch,
4. no trade list, timestamps, period boundaries, path or raw rows returned to Research,
5. retirement of the blind box after evaluation.

This avoids adaptive "try, see blind result, tweak, retry same holdout" behavior. A retired blind sample can later become ordinary research history, while a fresh box is kept sealed. Future shadow/paper data is the strongest naturally unseen sample.

**Important:** the Python module is an application-layer control, not a hard security boundary. A real deployment must place raw blind datasets in a separate service/account/storage permission domain so research agents cannot read them directly.

## Continuous operation

`ContinuousResearchLoop.run_forever()` is restartable because candidate state and events live in SQLite. The process should later run under a supervised service (container/systemd/cloud worker) with health checks and a kill switch. GitHub Actions should remain CI, not the 24/5 research daemon.

## Target validation

The `NorthStar` tracker refuses to mark the target validated until all required evidence exists: OOS, walk-forward, stress, blind, risk-rule compliance and enough paper-live months. A maximum acceptable drawdown must be explicitly defined before the target can become `VALIDATED`.

This intentionally prevents the system from manufacturing a `+10%` claim just because the number is the project objective.
