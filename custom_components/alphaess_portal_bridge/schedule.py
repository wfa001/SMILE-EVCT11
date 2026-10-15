"""Conservative detection for the observed G1T and G2T time-period schemas.

G2T keeps its existing behavior. G1T currently exposes exactly two periods,
each with an enable flag and start/end times. It does not report a global
charge strategy or per-period mode/current, so those controls remain hidden.
Never infer fields or create missing settings in the remote configuration.
"""
from __future__ import annotations

import re
from typing import Any

_TIME_PATTERN = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")
_STRATEGIES = frozenset({0, 1, 2})


def g1t_schedule_schema_matches(settings: Any) -> bool:
    """Whether settings match the captured G1T two-period time schema."""
    if not isinstance(settings, dict):
        return False
    periods = settings.get("timePeriods")
    if not isinstance(periods, list) or len(periods) != 2:
        return False

    for period in periods:
        if not isinstance(period, dict):
            return False
        if type(period.get("isEnable")) is not bool:
            return False
        for key in ("startTime", "endTime"):
            value = period.get(key)
            if not isinstance(value, str) or not _TIME_PATTERN.fullmatch(value):
                return False
    return True


def schedule_supported(generation: str | None, settings: Any) -> bool:
    """Whether period controls can be shown from the reported schema."""
    if generation == "g2T":
        return True
    return generation == "g1T" and g1t_schedule_schema_matches(settings)


def strategy_supported(generation: str | None, settings: Any) -> bool:
    """Whether the global schedule strategy exists and has a known value."""
    if generation == "g2T":
        return True
    if generation != "g1T" or not g1t_schedule_schema_matches(settings):
        return False
    strategy = settings.get("chargeStrategy")
    return type(strategy) is int and strategy in _STRATEGIES
