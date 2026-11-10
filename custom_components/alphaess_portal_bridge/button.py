"""Guarded wallbox controls for AlphaESS Wallbox Bridge."""
# ---------------------------------------------------------------------------
# Community-Build fuer https://www.storion4you.de/
# G2T-Erweiterung fuer SMILE-G3-EVCT11/S: Kavino
# Basierend auf dem Ausgangsprojekt wfa001/SMILE-EVCT11.
# Details und Attribution: siehe NOTICE.md im Paket.
# ---------------------------------------------------------------------------
from __future__ import annotations

from datetime import timedelta
import time

from homeassistant.const import EntityCategory

from homeassistant.components import persistent_notification
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import AuthenticationError, PortalConnectionError
from .const import DOMAIN
from .coordinator import AlphaESSWallboxCoordinator
from .entity import AlphaESSWallboxEntity
from .control_feedback import control_reason


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
    def extra_state_attributes(self):
        status = (self.coordinator.data or {}).get('wallbox_status')
        return {'Bedienhinweis': control_reason(
            self._control, self.settings_generation, self.settings,
            status.get('status') if isinstance(status, dict) else None,
            self.coordinator.last_update_success)}

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
        self._notification_id = f"{DOMAIN}_advanced_diagnostics_{entry.entry_id}"

    async def async_press(self) -> None:
        self.coordinator._advanced_diagnostics_until = time.monotonic() + 300
        expires = dt_util.now() + timedelta(minutes=5)
        persistent_notification.async_create(
            self.hass,
            f"Einmaliger ZIP-Download bis **{expires:%H:%M:%S} Uhr**. Der normale Diagnosedownload "
            "enthält während der Freigabe den ZIP-Link im Feld `advanced_archive_download`.",
            title="Erweiterte API-Diagnose freigegeben",
            notification_id=self._notification_id,
        )
