"""Conservative, read-only G1T schedule schema detection.

G2T keeps its existing, proven behavior. G1T scheduling remains experimental:
only recognize the exact three-period portal schema currently used by G2T.
Never infer fields or create missing settings in the remote configuration.
"""
from __future__ import annotations

import re
from typing import Any

_TIME_PATTERN = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")
_PERIOD_MODES = frozenset({1, 2, 3, 4})
_STRATEGIES = frozenset({0, 1, 2})


def g1t_schedule_schema_matches(settings: Any) -> bool:
    """Whether an existing G1T document has the full known G2T schedule shape.

    This checks structural compatibility, NOT actual support by G1T firmware.
    Nothing may be written unless the caller independently requests an edit.
    """
    if not isinstance(settings, dict):
        return False
    strategy = settings.get("chargeStrategy")
    if type(strategy) is not int or strategy not in _STRATEGIES:
        return False
    periods = settings.get("timePeriods")
    if not isinstance(periods, list) or len(periods) < 3:
        return False

    for period in periods[:3]:
        if not isinstance(period, dict):
            return False
        if type(period.get("isEnable")) is not bool:
            return False
        for key in ("startTime", "endTime"):
            value = period.get(key)
            if not isinstance(value, str) or not _TIME_PATTERN.fullmatch(value):
                return False
        # Only the four G2T-confirmed period modes are permitted in this
        # experimental path. G1T's global ECO mode 0 is not assumed here.
        mode = period.get("chargeMode")
        if type(mode) is not int or mode not in _PERIOD_MODES:
            return False
        current = period.get("chargeCurrent")
        if type(current) is not int or not 6 <= current <= 16:
            return False
    return True


def schedule_supported(generation: str | None, settings: Any) -> bool:
    """Preserve G2T behavior; gate G1T behind observed exact schema."""
    if generation == "g2T":
        return True
    return generation == "g1T" and g1t_schedule_schema_matches(settings)
