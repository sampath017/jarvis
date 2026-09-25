"""Finite test headroom, with deployed instances always using production limits."""
from dataclasses import dataclass
from typing import Mapping
import os


@dataclass(frozen=True)
class BudgetLimits:
    profile: str
    requests_per_minute: int
    daily_calls: int
    daily_tokens: int


# Zero disables daily token/call ceilings; the shared money allowance governs.
PRODUCTION_LIMITS = BudgetLimits('production', 15, 0, 0)
TESTING_LIMITS = BudgetLimits('testing', 120, 2_000, 3_000_000)


def budget_limits(environ: Mapping[str, str] | None = None) -> BudgetLimits:
    values = os.environ if environ is None else environ
    # Cloud Run owns these markers. Test configuration cannot raise a deployed budget.
    if values.get('K_SERVICE') or values.get('K_REVISION'):
        return PRODUCTION_LIMITS
    requested = (values.get('JARVIS_BUDGET_PROFILE') or values.get('ENVIRONMENT') or 'production').strip().lower()
    return TESTING_LIMITS if requested in {'test', 'testing'} else PRODUCTION_LIMITS
