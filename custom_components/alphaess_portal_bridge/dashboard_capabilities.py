"""Presentation capabilities from verified portal fields, never model names.

This does not enable new API write paths. G1T phase selection and Smart Mode
remain excluded even if a similarly named field is returned by that portal.
"""
from __future__ import annotations

import re
from typing import Any


def _choice(value: Any, choices: set[int]) -> bool:
    return type(value) is int and value in choices


def _current(value: Any) -> bool:
    return type(value) in (int, float) and 6 <= value <= 16 and value == int(value)


def _period(value: Any) -> bool:
    return isinstance(value, dict) and type(value.get("isEnable")) is bool and all(
        isinstance(value.get(key), str)
        and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value[key])
        for key in ("startTime", "endTime"))


def supported_dashboard_controls(profile: str | None, settings: Any) -> set[str]:
    """Whitelist controls only for a known profile and usable returned fields."""
    if profile not in {"g1T", "g2T"} or not isinstance(settings, dict):
        return set()
    # These settings live on the wallbox object; their entities handle values.
    controls = {"start", "stop", "household_current", "installer_control_allowed"}
    if _choice(settings.get("chargeMode"), {0, 1, 2, 3, 4}):
        controls.add("charge_mode_select")
    if _current(settings.get("chargeCurrent")):
        controls.add("custom_charge_current")
    periods = settings.get("timePeriods")
    count = 2 if profile == "g1T" else 3
    # G1T requires its complete observed schema. G2T's existing write path
    # requires at least three entries; shorter arrays must not suggest controls.
    schema = isinstance(periods, list) and (
        len(periods) == 2 and all(_period(p) for p in periods)
        if profile == "g1T" else len(periods) >= 3)
    if _choice(settings.get("chargeStrategy"), {0, 1, 2}) and (profile == "g2T" or schema):
        controls.add("charge_strategy_select")
    if profile == "g2T":
        if _choice(settings.get("obcPhase"), {1, 2, 3}):
            controls.add("obc_phase_select")
        if type(settings.get("smartMode")) is bool:
            controls.add("smart_mode")
        if (settings.get("isSupportGunLineSelfLock") is True
                and type(settings.get("gunLineSelfLockEnable")) is bool):
            controls.add("gun_line_self_lock_enabled")
    if schema:
        for index, item in enumerate(periods[:count], 1):
            if not _period(item):
                continue
            controls.update(f"time_period_{index}_{suffix}" for suffix in ("enabled", "start", "end"))
            if _choice(item.get("chargeMode"), {1, 2, 3, 4}):
                controls.add(f"time_period_{index}_mode")
            if _current(item.get("chargeCurrent")):
                controls.add(f"time_period_{index}_current")
    return controls
