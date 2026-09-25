"""Conservative USD allowance for the user's INR 20/day AI budget.

Prices verified on OpenRouter 2026-10-06. Provider max_price prevents routing
above these rates. No daily token ceiling; token counts remain telemetry.
"""
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from fastapi import HTTPException

DAILY_BUDGET_INR = 20
BUDGET_INR_PER_USD = 96.544  # Verified 2026-10-06; excludes payment fees/taxes.
DAILY_BUDGET_NANOS = int((Decimal(DAILY_BUDGET_INR) / Decimal(str(BUDGET_INR_PER_USD)) * 1_000_000_000).to_integral_value(rounding=ROUND_FLOOR))
PRICES = {
    'z-ai/glm-5.3-flash': (Decimal('0.15'), Decimal('0.50')),
    'google/gemini-3.8-flash': (Decimal('0.75'), Decimal('3.75')),
}


def provider_limits(model):
    if model not in PRICES:
        raise HTTPException(503, 'No verified spending policy for this model. Update its pricing before use.')
    prompt, completion = PRICES[model]
    return {'max_price': {'prompt': float(prompt), 'completion': float(completion)},
            'require_parameters': True}


def token_cost_nanos(model, prompt, completion):
    provider_limits(model)
    p, c = PRICES[model]
    return int(((Decimal(max(0, int(prompt))) * p + Decimal(max(0, int(completion))) * c) * 1000).to_integral_value(rounding=ROUND_CEILING))


def reported_cost_nanos(value):
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            return None
        return int((amount * 1_000_000_000).to_integral_value(rounding=ROUND_CEILING))
    except (ValueError, ArithmeticError):
        return None


def rupees(nanos):
    return nanos * BUDGET_INR_PER_USD / 1_000_000_000
