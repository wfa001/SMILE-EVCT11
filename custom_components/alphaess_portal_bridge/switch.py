"""Switch entities for AlphaESS Wallbox Bridge."""
# ---------------------------------------------------------------------------
# Community-Build fuer https://www.storion4you.de/
# G2T-Erweiterung fuer SMILE-G3-EVCT11/S: Kavino
# Basierend auf dem Ausgangsprojekt wfa001/SMILE-EVCT11.
# Details und Attribution: siehe NOTICE.md im Paket.
# ---------------------------------------------------------------------------
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import AuthenticationError, PortalConnectionError
from .const import DOMAIN
from .coordinator import AlphaESSWallboxCoordinator
from .entity import AlphaESSWallboxEntity, time_period


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: AlphaESSWallboxCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            AlphaESSInstallerControlSwitch(coordinator, entry),
            AlphaESSGunLineSelfLockSwitch(coordinator, entry),
            AlphaESSSmartModeSwitch(coordinator, entry),
            *(AlphaESSTimePeriodSwitch(coordinator, entry, index) for index in range(3)),
        ]
    )


class AlphaESSInstallerControlSwitch(AlphaESSWallboxEntity, SwitchEntity):
    """Allow or deny installer control as exposed by the AlphaESS app."""

    _attr_name = "Installateursteuerung erlaubt"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: AlphaESSWallboxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "installer_control_allowed")

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return {
            "Hinweis": (
                "Erlaubt dem verknüpften AlphaESS-Installateur die Fernsteuerung bzw. "
                "Konfiguration über den Installateurzugang. Der genaue Funktionsumfang "
                "dieser Portal-Einstellung ist von AlphaESS nicht vollständig dokumentiert."
            )
        }

    @property
    def is_on(self) -> bool | None:
        value = self.wallbox.get("allowInstallersControl")
        return value if isinstance(value, bool) else None

    async def _set(self, value: bool) -> None:
        try:
            await self.coordinator.api.async_update_wallbox_settings(
                installer_control_allowed=value
            )
        except (AuthenticationError, PortalConnectionError, ValueError) as err:
            raise HomeAssistantError(
                str(err) or "Installateursteuerung wurde nicht übernommen"
            ) from err
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)


class AlphaESSGunLineSelfLockSwitch(AlphaESSWallboxEntity, SwitchEntity):
    """Configure the G2T cable self-lock feature exposed by the AlphaESS app."""

    _attr_name = "Ladekabel an Wallbox automatisch verriegeln"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: AlphaESSWallboxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "gun_line_self_lock_enabled")

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.settings_generation == "g2T"
            and self.settings.get("isSupportGunLineSelfLock") is True
        )

    @property
    def is_on(self) -> bool | None:
        value = self.settings.get("gunLineSelfLockEnable")
        return value if isinstance(value, bool) else None

    async def _set(self, value: bool) -> None:
        try:
            await self.coordinator.api.async_update_wallbox_settings(
                gun_line_self_lock_enabled=value
            )
        except (AuthenticationError, PortalConnectionError, ValueError) as err:
            raise HomeAssistantError(
                str(err) or "Kabel-Selbstverriegelung wurde nicht übernommen"
            ) from err
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)


class AlphaESSSmartModeSwitch(AlphaESSWallboxEntity, SwitchEntity):
    """Enable AlphaESS automatic 3p-to-1p optimization on G2T."""

    _attr_name = "Smart Mode"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: AlphaESSWallboxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "smart_mode")

    @property
    def available(self) -> bool:
        return super().available and self.settings_generation == "g2T"

    @property
    def is_on(self) -> bool | None:
        value = self.settings.get("smartMode")
        return value if isinstance(value, bool) else None

    async def _set(self, value: bool) -> None:
        try:
            await self.coordinator.api.async_update_wallbox_settings(smart_mode=value)
        except (AuthenticationError, PortalConnectionError, ValueError) as err:
            raise HomeAssistantError(str(err) or "Smart Mode wurde nicht übernommen") from err
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)


class AlphaESSTimePeriodSwitch(AlphaESSWallboxEntity, SwitchEntity):
    """Enable or disable one G2T schedule period."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: AlphaESSWallboxCoordinator, entry: ConfigEntry, index: int
    ) -> None:
        super().__init__(coordinator, entry, f"time_period_{index + 1}_enabled")
        self._index = index
        self._attr_name = f"Zeitrahmen {index + 1} Aktiv"

    @property
    def available(self) -> bool:
        return super().available and self.settings_generation == "g2T" and bool(time_period(self.coordinator, self._index))

    @property
    def is_on(self) -> bool | None:
        value = time_period(self.coordinator, self._index).get("isEnable")
        return value if isinstance(value, bool) else None

    async def _set(self, value: bool) -> None:
        try:
            await self.coordinator.api.async_update_time_period(self._index, enabled=value)
        except (AuthenticationError, PortalConnectionError, ValueError) as err:
            raise HomeAssistantError(str(err) or "Der Zeitrahmen wurde nicht übernommen") from err
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
