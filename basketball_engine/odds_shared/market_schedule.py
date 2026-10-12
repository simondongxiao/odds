"""Time-aware market inventory state shared by daily collectors."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


BJ = timezone(timedelta(hours=8))


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=BJ) if parsed.tzinfo is None else parsed.astimezone(BJ)


def market_inventory_state(tip_at: Any, observed_at: Any, market_found: bool) -> dict[str, Any]:
    observed = _dt(observed_at) or datetime.now(BJ)
    tip = _dt(tip_at)
    hours = (tip - observed).total_seconds() / 3600 if tip else None
    if market_found:
        ttl = 300 if hours is not None and hours <= 1 else 900 if hours is not None and hours <= 6 else 3600
        return {"market_status": "MARKET_FOUND", "pricing_inventory_status": "PRICEABLE_MARKET_PRESENT",
                "market_ttl_seconds": ttl, "next_market_retry_at": None,
                "inventory_retained": True, "hours_to_start": hours}
    if hours is None:
        delay, ttl = 1800, 900
    elif hours > 48:
        delay, ttl = 21600, 10800
    elif hours > 24:
        delay, ttl = 10800, 3600
    elif hours > 6:
        delay, ttl = 5400, 1800
    elif hours > 1:
        delay, ttl = 1800, 600
    else:
        delay, ttl = 600, 300
    return {"market_status": "NO_MARKET", "pricing_inventory_status": "UNPRICEABLE",
            "market_ttl_seconds": ttl,
            "next_market_retry_at": (observed + timedelta(seconds=delay)).isoformat(),
            "inventory_retained": True, "hours_to_start": hours,
            "retry_policy": "TIME_AWARE_NO_MARKET_RECHECK"}
