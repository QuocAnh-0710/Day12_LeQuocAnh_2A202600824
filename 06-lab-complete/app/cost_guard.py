"""Per-user monthly budget guard — prevents runaway LLM spending."""
from datetime import datetime
from fastapi import HTTPException

from app.config import settings

PRICE_PER_1K_INPUT = 0.00015   # $0.15 / 1M input tokens (gpt-4o-mini)
PRICE_PER_1K_OUTPUT = 0.0006   # $0.60 / 1M output tokens

# user_id -> {"month": "YYYY-MM", "cost": float}
_user_budgets: dict[str, dict] = {}


def _current_month() -> str:
    return datetime.now().strftime("%Y-%m")


def _get_record(user_id: str) -> dict:
    month = _current_month()
    record = _user_budgets.get(user_id)
    if not record or record["month"] != month:
        _user_budgets[user_id] = {"month": month, "cost": 0.0}
    return _user_budgets[user_id]


def check_budget(user_id: str = "anonymous") -> None:
    """Raise HTTP 402 if user has exceeded their monthly budget."""
    record = _get_record(user_id)
    if record["cost"] >= settings.monthly_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Monthly budget exceeded",
                "used_usd": round(record["cost"], 4),
                "budget_usd": settings.monthly_budget_usd,
                "resets_at": "start of next month",
            },
        )


def record_usage(user_id: str, input_tokens: int, output_tokens: int) -> None:
    """Accumulate token costs for the user after an LLM call."""
    record = _get_record(user_id)
    record["cost"] += (input_tokens / 1000) * PRICE_PER_1K_INPUT
    record["cost"] += (output_tokens / 1000) * PRICE_PER_1K_OUTPUT


def get_usage(user_id: str = "anonymous") -> dict:
    record = _get_record(user_id)
    return {
        "user_id": user_id,
        "month": record["month"],
        "cost_usd": round(record["cost"], 4),
        "budget_usd": settings.monthly_budget_usd,
        "remaining_usd": round(max(0.0, settings.monthly_budget_usd - record["cost"]), 4),
    }
