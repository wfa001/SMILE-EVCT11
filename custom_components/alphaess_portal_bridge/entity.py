"""Shared entities and helpers for AlphaESS Wallbox Bridge."""
# ---------------------------------------------------------------------------
# Community-Build fuer https://www.storion4you.de/
# G2T-Erweiterung fuer SMILE-G3-EVCT11/S: Kavino
# Basierend auf dem Ausgangsprojekt wfa001/SMILE-EVCT11.
# Details und Attribution: siehe NOTICE.md im Paket.
# ---------------------------------------------------------------------------
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SYSTEM_SERIAL, DOMAIN
from .coordinator import AlphaESSWallboxCoordinator

G1_MODES = {
    "ECO-Ladung": 0,
    "Langsamladung": 1,
    "Schonladung / Standardleistung": 2,
    "Schnellladung": 3,
    "Kundenspezifische Ladeleistung": 4,
}
G2_MODES = {
    "Langsamladung": 1,
    "Schonladung / Standardleistung": 2,
    "Schnellladung": 3,
    "Kundenspezifische Ladeleistung": 4,
}
STRATEGIES = {
    "Manuell": 0,
    "Zeitgesteuertes Aufladen": 1,
    "Plug and Play": 2,
}
PHASES = {"1-phasig": 1, "2-phasig": 2, "3-phasig": 3}

STATUS_NAMES = {
    "NotInsertedGun": "Nicht angeschlossen",
    "PendingStart": "Bereit",
    "Charging": "Lädt",
    "ChargingStopped": "Laden gestoppt",
    "CharingStopped": "Laden gestoppt",
    "InsufficientPower": "Unzureichende Leistung",
    "WaitingForChargingPile": "Warten auf Antwort des E-Autos",
}


def wallbox_object(coordinator: AlphaESSWallboxCoordinator) -> dict[str, Any]:
    data = coordinator.data or {}
    configuration = data.get("configuration") or {}
    serial = data.get("wallbox_serial")
    return coordinator.api._find_wallbox_data(configuration, serial)


def settings_object(coordinator: AlphaESSWallboxCoordinator) -> tuple[str | None, dict[str, Any]]:
    wallbox = wallbox_object(coordinator)
    if isinstance(wallbox.get("g2T"), dict):
        return "g2T", wallbox["g2T"]
    if isinstance(wallbox.get("g1T"), dict):
        return "g1T", wallbox["g1T"]
    return None, {}


def time_period(coordinator: AlphaESSWallboxCoordinator, index: int) -> dict[str, Any]:
    generation, settings = settings_object(coordinator)
    if generation != "g2T":
        return {}
    periods = settings.get("timePeriods")
    if not isinstance(periods, list) or index < 0 or index >= len(periods):
        return {}
    period = periods[index]
    return period if isinstance(period, dict) else {}

def scheduled_charging_selected(coordinator: AlphaESSWallboxCoordinator) -> bool:
    """Whether G2T reports the scheduled charging strategy as selected.

    This is the *portal configuration*, not proof that the wallbox has applied
    a schedule at the hardware level.
    """
    generation, settings = settings_object(coordinator)
    return generation == "g2T" and settings.get("chargeStrategy") == 1


def time_period_selected(coordinator: AlphaESSWallboxCoordinator, index: int) -> bool:
    """Whether a configured time period is enabled in scheduled mode.

    Other strategies retain the saved periods so switching back to scheduled
    charging does not destroy the user's previous time configuration.
    """
    return (
        scheduled_charging_selected(coordinator)
        and time_period(coordinator, index).get("isEnable") is True
    )


class AlphaESSWallboxEntity(CoordinatorEntity[AlphaESSWallboxCoordinator]):
    """Base entity for the AlphaESS wallbox."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AlphaESSWallboxCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        system_serial = entry.data[CONF_SYSTEM_SERIAL]
        self._attr_unique_id = f"{system_serial}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, system_serial)},
            name="AlphaESS Wallbox",
            manufacturer="AlphaESS",
            model="SMILE-EVCT11",
        )

    @property
    def wallbox(self) -> dict[str, Any]:
        return wallbox_object(self.coordinator)

    @property
    def settings_generation(self) -> str | None:
        return settings_object(self.coordinator)[0]

    @property
    def settings(self) -> dict[str, Any]:
        return settings_object(self.coordinator)[1]
