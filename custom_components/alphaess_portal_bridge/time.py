"""Schedule time entities for AlphaESS Wallbox Bridge."""
# ---------------------------------------------------------------------------
# Community-Build fuer https://www.storion4you.de/
# G2T-Erweiterung fuer SMILE-G3-EVCT11/S: Kavino
# Basierend auf dem Ausgangsprojekt wfa001/SMILE-EVCT11.
# Details und Attribution: siehe NOTICE.md im Paket.
# ---------------------------------------------------------------------------
from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import AuthenticationError, PortalConnectionError
from .const import DOMAIN
from .coordinator import AlphaESSWallboxCoordinator
from .entity import AlphaESSWallboxEntity, time_period, time_period_selected


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: AlphaESSWallboxCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for index in range(3):
        entities.append(AlphaESSTimePeriodTime(coordinator, entry, index, "start"))
        entities.append(AlphaESSTimePeriodTime(coordinator, entry, index, "end"))
    async_add_entities(entities)


class AlphaESSTimePeriodTime(AlphaESSWallboxEntity, TimeEntity):
    """Start or end time for one G2T schedule period."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: AlphaESSWallboxCoordinator,
        entry: ConfigEntry,
        index: int,
        boundary: str,
    ) -> None:
        super().__init__(coordinator, entry, f"time_period_{index + 1}_{boundary}")
        self._index = index
        self._boundary = boundary
        self._attr_name = f"Zeitrahmen {index + 1} {'Beginn' if boundary == 'start' else 'Ende'}"

    @property
    def extra_state_attributes(self) -> dict[str, str | bool]:
        return {
            "Hinweis": "Minutengenaue Eingabe (HH:MM); die Cloud-Akzeptanz ist noch nicht live bestätigt.",
            "Zeitfenster laut Portal-Modus ausgewählt": time_period_selected(
                self.coordinator, self._index
            ),
        }

    @property
    def available(self) -> bool:
        return super().available and self.settings_generation == "g2T" and bool(time_period(self.coordinator, self._index))

    @property
    def native_value(self) -> time | None:
        key = "startTime" if self._boundary == "start" else "endTime"
        value = time_period(self.coordinator, self._index).get(key)
        if not isinstance(value, str):
            return None
        try:
            hour, minute = (int(part) for part in value.split(":", 1))
            return time(hour=hour, minute=minute)
        except (ValueError, TypeError):
            return None

    async def async_set_value(self, value: time) -> None:
        if value.second != 0 or value.microsecond != 0:
            raise HomeAssistantError("Bitte eine minutengenaue Zeit ohne Sekunden einstellen")
        hhmm = value.strftime("%H:%M")
        kwargs = {"start_time": hhmm} if self._boundary == "start" else {"end_time": hhmm}
        try:
            await self.coordinator.api.async_update_time_period(self._index, **kwargs)
        except (AuthenticationError, PortalConnectionError, ValueError) as err:
            raise HomeAssistantError(str(err) or "Die Zeit wurde nicht übernommen") from err
        await self.coordinator.async_request_refresh()
