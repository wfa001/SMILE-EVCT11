"""Guarded wallbox controls for AlphaESS Wallbox Bridge."""
# ---------------------------------------------------------------------------
# Community-Build fuer https://www.storion4you.de/
# G2T-Erweiterung fuer SMILE-G3-EVCT11/S: Kavino
# Basierend auf dem Ausgangsprojekt wfa001/SMILE-EVCT11.
# Details und Attribution: siehe NOTICE.md im Paket.
# ---------------------------------------------------------------------------
from __future__ import annotations

import time

from homeassistant.const import EntityCategory

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import AuthenticationError, PortalConnectionError
from .const import DOMAIN
from .coordinator import AlphaESSWallboxCoordinator
from .entity import AlphaESSWallboxEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: AlphaESSWallboxCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            AlphaESSWallboxControlButton(coordinator, entry, "START"),
            AlphaESSWallboxControlButton(coordinator, entry, "STOP"),
            AlphaESSAdvancedDiagnosticsButton(coordinator, entry),
        ]
    )


class AlphaESSWallboxControlButton(AlphaESSWallboxEntity, ButtonEntity):
    """Expose a wallbox control only when the live state permits it."""

    def __init__(
        self, coordinator: AlphaESSWallboxCoordinator, entry: ConfigEntry, control: str
    ) -> None:
        super().__init__(coordinator, entry, control.lower())
        self._control = control
        self._attr_name = "Laden starten" if control == "START" else "Laden stoppen"

    @property
    def available(self) -> bool:
        if not super().available or not self.coordinator.data:
            return False
        # G2T START/STOP is only effective in Manual mode.  Do not present
        # an actionable button in schedule or Plug-and-Play mode.
        if self.settings_generation == "g2T" and self.settings.get("chargeStrategy") != 0:
            return False
        status_data = self.coordinator.data.get("wallbox_status") or {}
        status = status_data.get("status") if isinstance(status_data, dict) else None
        allowed = (
            {"PendingStart", "ChargingStopped", "CharingStopped"}
            if self._control == "START"
            else {"Charging", "WaitingForChargingPile"}
        )
        return status in allowed

    async def async_press(self) -> None:
        try:
            await self.coordinator.api.async_control_wallbox(self._control)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        except (AuthenticationError, PortalConnectionError) as err:
            raise HomeAssistantError("Der Wallbox-Befehl wurde vom Live-Status abgelehnt") from err
        await self.coordinator.async_request_refresh()


class AlphaESSAdvancedDiagnosticsButton(AlphaESSWallboxEntity, ButtonEntity):
    """Temporarily allow a sanitized extended snapshot in HA diagnostics."""

    _attr_name = "Erweiterte API-Diagnose freigeben"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:file-search-outline"

    def __init__(self, coordinator: AlphaESSWallboxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "advanced_diagnostics")

    async def async_press(self) -> None:
        # Valid for 5 minutes, consumed by the next diagnostics download.
        # No remote commands or additional API calls are made.
        self.coordinator._advanced_diagnostics_until = time.monotonic() + 300
