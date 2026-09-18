"""North-star tracking. Targets are evidence checks, never optimization guarantees."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Mapping


class TargetStatus(str, Enum):
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NOT_VALIDATED = "NOT_VALIDATED"
    VALIDATED = "VALIDATED"


@dataclass(frozen=True)
class NorthStar:
    monthly_net_return: float = 0.10
    trades_per_day: float = 1.0
    max_drawdown_limit: float | None = None
    min_live_months: int = 3

    def __post_init__(self) -> None:
        if not (isfinite(self.monthly_net_return) and self.monthly_net_return > 0):
            raise ValueError("monthly target must be positive")
        if not (isfinite(self.trades_per_day) and self.trades_per_day > 0):
            raise ValueError("trade-frequency target must be positive")
        if self.max_drawdown_limit is not None and not (0 < self.max_drawdown_limit < 1):
            raise ValueError("drawdown limit must be a fraction between 0 and 1")
        if self.min_live_months < 1:
            raise ValueError("min_live_months must be positive")

    def assess(self, evidence: Mapping[str, object]) -> tuple[TargetStatus, tuple[str, ...]]:
        required = (
            "paper_live_months", "paper_live_mean_monthly_net_return",
            "paper_live_trades_per_day", "paper_live_max_drawdown",
            "blind_pass", "oos_pass", "walk_forward_pass", "stress_pass",
            "risk_rules_respected",
        )
        missing = [k for k in required if k not in evidence]
        if self.max_drawdown_limit is None:
            missing.append("max_drawdown_limit_not_defined")
        if missing:
            return TargetStatus.INSUFFICIENT_DATA, tuple(missing)

        checks = {
            "paper_live_months": int(evidence["paper_live_months"]) >= self.min_live_months,
            "monthly_net_return": float(evidence["paper_live_mean_monthly_net_return"]) >= self.monthly_net_return,
            "trades_per_day": float(evidence["paper_live_trades_per_day"]) >= self.trades_per_day,
            "max_drawdown": float(evidence["paper_live_max_drawdown"]) <= float(self.max_drawdown_limit),
            "blind_pass": evidence["blind_pass"] is True,
            "oos_pass": evidence["oos_pass"] is True,
            "walk_forward_pass": evidence["walk_forward_pass"] is True,
            "stress_pass": evidence["stress_pass"] is True,
            "risk_rules_respected": evidence["risk_rules_respected"] is True,
        }
        failed = tuple(k for k, v in checks.items() if not v)
        return (TargetStatus.VALIDATED, ()) if not failed else (TargetStatus.NOT_VALIDATED, failed)
