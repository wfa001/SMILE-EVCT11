"""Number entities for AlphaESS Wallbox Bridge."""
# ---------------------------------------------------------------------------
# Community-Build fuer https://www.storion4you.de/
# G2T-Erweiterung fuer SMILE-G3-EVCT11/S: Kavino
# Basierend auf dem Ausgangsprojekt wfa001/SMILE-EVCT11.
# Details und Attribution: siehe NOTICE.md im Paket.
# ---------------------------------------------------------------------------
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfElectricCurrent
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
            AlphaESSWallboxChargeCurrentNumber(coordinator, entry),
            AlphaESSHouseholdCurrentNumber(coordinator, entry),
            *(AlphaESSTimePeriodCurrentNumber(coordinator, entry, index) for index in range(3)),
        ]
    )


class _CurrentNumberBase(AlphaESSWallboxEntity, NumberEntity):
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 6
    _attr_native_max_value = 16
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_entity_category = EntityCategory.CONFIG


class AlphaESSWallboxChargeCurrentNumber(_CurrentNumberBase):
    """Set current for the active custom charging mode."""

    _attr_name = "Ladestrom (kundenspezifisch)"

    def __init__(self, coordinator: AlphaESSWallboxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "custom_charge_current")

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return {
            "Hinweis": (
                "Dies ist der vom AlphaESS-Portal gemeldete Soll-Ladestrom. "
                "Eine erfolgreiche API-Antwort oder geänderte Anzeige bestätigt "
                "noch keine physisch erfolgte Ladeleistungsänderung. "
                "Für den tatsächlichen Ladezustand die Live-Leistung prüfen."
            )
        }

    @property
    def native_value(self) -> float | None:
        value = self.settings.get("chargeCurrent")
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def available(self) -> bool:
        return super().available and self.settings.get("chargeMode") == 4

    async def async_set_native_value(self, value: float) -> None:
        if self.settings.get("chargeMode") != 4:
            raise HomeAssistantError("Wähle zuerst Kundenspezifische Ladeleistung")
        try:
            await self.coordinator.api.async_update_wallbox_settings(charge_current=int(value))
        except (AuthenticationError, PortalConnectionError, ValueError) as err:
            raise HomeAssistantError(str(err) or "Der Ladestrom wurde nicht übernommen") from err
        await self.coordinator.async_request_refresh()


class AlphaESSHouseholdCurrentNumber(AlphaESSWallboxEntity, NumberEntity):
    """Set the installation/household current limit exposed by AlphaESS."""

    _attr_name = "Hausstrom-Einstellung"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 25
    _attr_native_max_value = 1000
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: AlphaESSWallboxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "household_current")

    @property
    def native_value(self) -> float | None:
        # houseHoldCurrent is part of the wallbox object inside the full
        # configuration document (not a top-level coordinator key).  Reuse
        # the same resolver as the diagnostic sensors so the value is shown
        # immediately after every refresh.
        value = self.wallbox.get("houseHoldCurrent")
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self.coordinator.api.async_update_wallbox_settings(
                household_current=int(value)
            )
        except (AuthenticationError, PortalConnectionError, ValueError) as err:
            raise HomeAssistantError(
                str(err) or "Die Hausstrom-Einstellung wurde nicht übernommen"
            ) from err
        await self.coordinator.async_request_refresh()


class AlphaESSTimePeriodCurrentNumber(_CurrentNumberBase):
    """Custom current for one G2T schedule period."""

    def __init__(
        self, coordinator: AlphaESSWallboxCoordinator, entry: ConfigEntry, index: int
    ) -> None:
        super().__init__(coordinator, entry, f"time_period_{index + 1}_current")
        self._index = index
        self._attr_name = f"Zeitrahmen {index + 1} Maximaler Strom"

    @property
    def available(self) -> bool:
        period = time_period(self.coordinator, self._index)
        return (
            super().available
            and self.settings_generation == "g2T"
            and bool(period)
            and period.get("chargeMode") == 4
        )

    @property
    def native_value(self) -> float | None:
        value = time_period(self.coordinator, self._index).get("chargeCurrent")
        return float(value) if isinstance(value, (int, float)) else None

    async def async_set_native_value(self, value: float) -> None:
        if time_period(self.coordinator, self._index).get("chargeMode") != 4:
            raise HomeAssistantError("Wähle für diesen Zeitrahmen zuerst Kundenspezifische Ladeleistung")
        try:
            await self.coordinator.api.async_update_time_period(
                self._index, charge_current=int(value)
            )
        except (AuthenticationError, PortalConnectionError, ValueError) as err:
            raise HomeAssistantError(str(err) or "Der Ladestrom wurde nicht übernommen") from err
        await self.coordinator.async_request_refresh()
