"""Privacy-first diagnostics for G1T and G2T portal profiles.

No raw portal payload, arbitrary keys/values, serials, credentials, URLs,
timestamps, energy readings, or charge reports ever enter the exported data.
"""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import AlphaESSPortalApi
from .schedule import g1t_schedule_schema_matches, strategy_supported
from .const import DOMAIN

# Exact known schema fields only. Unknown fields are never exported.
_WALLBOX_FIELDS = (
    "houseHoldCurrent", "allowInstallersControl", "phase",
    "softwareVersion", "hardwareVersion", "startUpPower",
)
_COMMON_SETTINGS = ("chargeMode", "chargeCurrent")
_SCHEDULE_SETTINGS = ("chargeStrategy", "timePeriods")
_G2T_SETTINGS = (
    "obcPhase", "smartMode",
    "isSupportGunLineSelfLock", "gunLineSelfLockEnable",
)
_LIVE_FIELDS = (
    "status", "chargingStatus", "state", "power", "chargingPower",
    "currentPower", "realPower", "chargingAmount",
    "lastChargingAmount", "gunIsLock", "voltage", "current",
    "phase", "faultCode",
)
_REPORT_FIELDS = ("beginDate", "endDate", "chargingCapacity", "chargingWorkModel")


def _present_fields(document: Any, allowed: tuple[str, ...]) -> list[str]:
    """Reveal only the presence of predefined public schema names."""
    if not isinstance(document, dict):
        return []
    return [key for key in allowed if key in document]


def _bool_capability(document: Any, key: str) -> str:
    """Report type/presence, not the user's actual settings."""
    if not isinstance(document, dict) or key not in document:
        return "not_reported"
    if not isinstance(document[key], bool):
        return "unexpected_type"
    return "supported" if document[key] else "not_supported"


def _period_schema(settings: Any) -> dict[str, Any]:
    periods = settings.get("timePeriods") if isinstance(settings, dict) else None
    if not isinstance(periods, list):
        return {"available": False}
    return {
        "available": True,
        "count": min(len(periods), 100),
        "fields": sorted({
            field for period in periods if isinstance(period, dict)
            for field in ("startTime", "endTime", "chargeMode", "chargeCurrent", "isEnable")
            if field in period
        }),
        # Keep each window separate: a union alone can hide missing fields
        # in one particular G1T period. Never export actual times or values.
        "periods": [
            {
                "fields": [
                    key for key in ("startTime", "endTime", "chargeMode", "chargeCurrent", "isEnable")
                    if key in period
                ],
                "timing_fields_are_strings": (
                    isinstance(period.get("startTime"), str)
                    and isinstance(period.get("endTime"), str)
                ),
            } if isinstance(period, dict) else {
                "fields": [],
                "timing_fields_are_strings": False,
            }
            for period in periods[:3]
        ],
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Produce a useful, deterministic, read-only, allowlisted diagnosis."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data or {}
    configuration = data.get("configuration")
    serial = data.get("wallbox_serial")
    wallbox = coordinator.api._find_wallbox_data(configuration or {}, serial)
    generation, settings = AlphaESSPortalApi._settings_from_wallbox(wallbox)
    status = data.get("wallbox_status")
    report = data.get("latest_report")
    return {
        "diagnostics_schema": 1,
        "privacy": {
            "mode": "allowlist_only",
            "contains_raw_api_responses": False,
            "contains_identifiers_or_credentials": False,
            "contains_charge_history_values": False,
        },
        "portal_profile": generation if generation in ("g1T", "g2T") else "unknown",
        "integration": {
            "configuration_interval_seconds": int(coordinator.update_interval.total_seconds())
            if coordinator.update_interval else None,
            "live_interval_seconds": 5 if coordinator._live_refresh_cancel is not None else None,
            "live_polling_supported": coordinator._live_status_supported,
            "live_consecutive_errors": min(coordinator._live_refresh_errors, 100000),
            "data_available": bool(data),
            "last_update_success": bool(coordinator.last_update_success),
            "live_success_count": min(coordinator._live_success_count, 1000000),
            "live_failure_count": min(coordinator._live_failure_count, 1000000),
            "full_success_count": min(coordinator._full_success_count, 1000000),
            "full_failure_count": min(coordinator._full_failure_count, 1000000),
            "live_last_cycle_duration_ms": coordinator._live_last_duration_ms,
            "full_last_cycle_duration_ms": coordinator._full_last_duration_ms,
            "live_last_http_status": coordinator._live_last_http_status,
        },
        "wallbox_schema": {
            "fields": _present_fields(wallbox, _WALLBOX_FIELDS),
            "settings_fields": _present_fields(
                settings, _COMMON_SETTINGS + _SCHEDULE_SETTINGS + (_G2T_SETTINGS if generation == "g2T" else ())
            ),
            "automatic_cable_lock": _bool_capability(settings, "isSupportGunLineSelfLock"),
            "time_periods": _period_schema(settings),
            "g1t_time_period_schema_matches": (
                g1t_schedule_schema_matches(settings) if generation == "g1T" else None
            ),
            "g1t_schedule_strategy_supported": (
                strategy_supported(generation, settings) if generation == "g1T" else None
            ),
        },
        "live_data": {
            "source": "real_status" if data.get("wallbox_status_source") == "real_status" else "system_or_unknown",
            "available_fields": _present_fields(status, _LIVE_FIELDS),
        },
        "charge_report": {
            "available_fields": _present_fields(report, _REPORT_FIELDS),
            "daily_report_value_available": isinstance(data.get("today_report_energy"), (int, float)),
        },
    }
