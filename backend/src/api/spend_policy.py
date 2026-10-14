"""USD allowance for the user's $0.50/day AI budget.

Prices verified on OpenRouter. Provider max_price prevents routing
above these rates. No daily token ceiling; token counts remain telemetry.
"""
from __future__ import annotations
from ..settings import OPENROUTER_DAILY_BUDGET_USD, LLM_MODEL

import logging
import os
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

logger = logging.getLogger(__name__)

DAILY_BUDGET_NANOS = int((Decimal(str(OPENROUTER_DAILY_BUDGET_USD))
                         * 1_000_000_000).to_integral_value(rounding=ROUND_FLOOR))

# Pre-seeded pricing cache (USD per 1M tokens)
PRICES: dict[str, tuple[Decimal, Decimal]] = {
    'z-ai/glm-5.3-flash': (Decimal('0.15'), Decimal('0.50')),
    'xiaomi/mimo-v2.6-flash': (Decimal('0.14'), Decimal('0.28')),
    'google/gemini-3.8-flash': (Decimal('0.75'), Decimal('3.75')),
    'qwen/qwen-2.5-7b-instruct': (Decimal('0.06'), Decimal('0.12')),
    'qwen/qwen-2.5-72b-instruct': (Decimal('0.35'), Decimal('0.40')),
}


def get_model_pricing(model: str | None) -> tuple[Decimal, Decimal]:
    """Dynamically resolve model pricing per million tokens (prompt, completion).

    Checks memory cache first. If model is unknown, fetches published pricing
    from OpenRouter API or falls back dynamically based on environment or safe defaults.
    """
    if not model:
        model = LLM_MODEL

    if model in PRICES:
        return PRICES[model]

    # Check for explicit manual override in environment
    env_prompt = os.getenv('OPENROUTER_PRICE_PROMPT')
    env_comp = os.getenv('OPENROUTER_PRICE_COMPLETION')
    if env_prompt and env_comp:
        try:
            pricing = (Decimal(str(env_prompt)), Decimal(str(env_comp)))
            PRICES[model] = pricing
            return pricing
        except Exception:
            pass

    # Attempt dynamic fetch from OpenRouter models catalog
    try:
        import httpx
        resp = httpx.get('https://openrouter.ai/api/v1/models', timeout=3.0)
        if resp.status_code == 200:
            for item in resp.json().get('data', []):
                mid = item.get('id')
                p_info = item.get('pricing') or {}
                if mid and p_info:
                    try:
                        p_val = Decimal(
                            str(p_info.get('prompt', '0'))) * 1_000_000
                        c_val = Decimal(
                            str(p_info.get('completion', '0'))) * 1_000_000
                        PRICES[mid] = (p_val, c_val)
                    except Exception:
                        pass
            if model in PRICES:
                logger.info(
                    "Dynamically resolved pricing for model '%s': %s", model, PRICES[model])
                return PRICES[model]
    except Exception as exc:
        logger.debug("Dynamic OpenRouter pricing query failed: %s", exc)

    # Safe dynamic fallback for unlisted/mock/custom models
    default_p = Decimal(os.getenv('OPENROUTER_DEFAULT_PRICE_PROMPT', '0.20'))
    default_c = Decimal(
        os.getenv('OPENROUTER_DEFAULT_PRICE_COMPLETION', '0.60'))
    PRICES[model] = (default_p, default_c)
    logger.info("Using dynamic fallback pricing for model '%s': prompt=%s, completion=%s",
                model, default_p, default_c)
    return PRICES[model]


def provider_limits(model: str | None) -> dict:
    prompt, completion = get_model_pricing(model)
    return {
        'max_price': {'prompt': float(prompt), 'completion': float(completion)},
        'require_parameters': True,
    }


def token_cost_nanos(model: str | None, prompt: int, completion: int) -> int:
    p, c = get_model_pricing(model)
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


def dollars(nanos: int | float) -> float:
    return float(nanos) / 1_000_000_000


def rupees(nanos: int | float) -> float:
    return dollars(nanos)
