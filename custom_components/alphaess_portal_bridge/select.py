"""Select entities for AlphaESS Wallbox Bridge."""
# ---------------------------------------------------------------------------
# Community-Build fuer https://www.storion4you.de/
# G2T-Erweiterung fuer SMILE-G3-EVCT11/S: Kavino
# Basierend auf dem Ausgangsprojekt wfa001/SMILE-EVCT11.
# Details und Attribution: siehe NOTICE.md im Paket.
# ---------------------------------------------------------------------------
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import AuthenticationError, PortalConnectionError
from .const import DOMAIN
from .coordinator import AlphaESSWallboxCoordinator
from .entity import (
    G1_MODES,
    G2_MODES,
    PHASES,
    STRATEGIES,
    AlphaESSWallboxEntity,
    settings_object,
    time_period,
    scheduled_charging_selected,
    time_period_selected,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: AlphaESSWallboxCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            AlphaESSWallboxModeSelect(coordinator, entry),
            AlphaESSWallboxStrategySelect(coordinator, entry),
            AlphaESSWallboxPhaseSelect(coordinator, entry),
            *(AlphaESSTimePeriodModeSelect(coordinator, entry, index) for index in range(3)),
        ]
    )


class AlphaESSWallboxModeSelect(AlphaESSWallboxEntity, SelectEntity):
    """Select the active charging mode for G1T or G2T."""

    _attr_name = "Lademodus"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: AlphaESSWallboxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "charge_mode_select")

    @property
    def options(self) -> list[str]:
        generation, _ = settings_object(self.coordinator)
        return list(G2_MODES if generation == "g2T" else G1_MODES)

    @property
    def available(self) -> bool:
        generation, settings = settings_object(self.coordinator)
        # The portal hides the global Lademodus while G2T is controlled by
        # time periods.  Mirror that behavior instead of showing "unknown".
        return super().available and not (generation == "g2T" and settings.get("chargeStrategy") == 1)

    @property
    def current_option(self) -> str | None:
        generation, settings = settings_object(self.coordinator)
        modes = G2_MODES if generation == "g2T" else G1_MODES
        value = settings.get("chargeMode")
        return next((name for name, mode in modes.items() if mode == value), None)

    async def async_select_option(self, option: str) -> None:
        generation, _ = settings_object(self.coordinator)
        modes = G2_MODES if generation == "g2T" else G1_MODES
        if option not in modes:
            raise HomeAssistantError("Unbekannter Lademodus")
        try:
            await self.coordinator.api.async_update_wallbox_settings(charge_mode=modes[option])
        except (AuthenticationError, PortalConnectionError, ValueError) as err:
            raise HomeAssistantError(str(err) or "Der Lademodus wurde vom Portal nicht übernommen") from err
        await self.coordinator.async_request_refresh()


class AlphaESSWallboxStrategySelect(AlphaESSWallboxEntity, SelectEntity):
    """G2T charging strategy: manual, schedule or plug-and-play."""

    _attr_name = "Ladeeinstellung"
    _attr_options = list(STRATEGIES)
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: AlphaESSWallboxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "charge_strategy_select")

    @property
    def available(self) -> bool:
        return super().available and self.settings_generation == "g2T"

    @property
    def current_option(self) -> str | None:
        value = self.settings.get("chargeStrategy")
        return next((name for name, strategy in STRATEGIES.items() if strategy == value), None)

    @property
    def extra_state_attributes(self) -> dict[str, str | bool]:
        return {
            "Zeitgesteuertes Laden ausgewählt": scheduled_charging_selected(self.coordinator),
            "Hinweis": (
                "Gespeicherte Zeitfenster werden beim Wechsel zu Manuell oder "
                "Plug and Play nicht gelöscht. Die Integration zeigt nur die "
                "Ladeeinstellung aus dem AlphaESS-Portal; eine tatsächliche "
                "Wirkung der Zeitfenster ist damit nicht nachgewiesen."
            ),
        }

    async def async_select_option(self, option: str) -> None:
        if option not in STRATEGIES:
            raise HomeAssistantError("Unbekannte Ladeeinstellung")
        try:
            await self.coordinator.api.async_update_wallbox_settings(
                charge_strategy=STRATEGIES[option]
            )
        except (AuthenticationError, PortalConnectionError, ValueError) as err:
            raise HomeAssistantError(str(err) or "Die Ladeeinstellung wurde nicht übernommen") from err
        await self.coordinator.async_request_refresh()


class AlphaESSWallboxPhaseSelect(AlphaESSWallboxEntity, SelectEntity):
    """G2T OBC phase selection."""

    _attr_name = "OBC Phasenwahl"
    _attr_options = list(PHASES)
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: AlphaESSWallboxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "obc_phase_select")

    @property
    def available(self) -> bool:
        return super().available and self.settings_generation == "g2T"

    @property
    def current_option(self) -> str | None:
        value = self.settings.get("obcPhase")
        return next((name for name, phase in PHASES.items() if phase == value), None)

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return {
            "Hinweis": (
                "OBC-Phasenwahl ist ein Sollwert. Die tatsächlich verwendete "
                "Phasenanzahl kann von Wallbox und Fahrzeug abweichen; insbesondere "
                "2-phasig sollte bei Bedarf extern gemessen werden."
            )
        }

    async def async_select_option(self, option: str) -> None:
        if option not in PHASES:
            raise HomeAssistantError("Unbekannte Phasenwahl")
        try:
            await self.coordinator.api.async_update_wallbox_settings(obc_phase=PHASES[option])
        except (AuthenticationError, PortalConnectionError, ValueError) as err:
            raise HomeAssistantError(str(err) or "Die Phasenwahl wurde nicht übernommen") from err
        await self.coordinator.async_request_refresh()


class AlphaESSTimePeriodModeSelect(AlphaESSWallboxEntity, SelectEntity):
    """Charge mode for one G2T schedule period."""

    _attr_options = list(G2_MODES)
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: AlphaESSWallboxCoordinator, entry: ConfigEntry, index: int
    ) -> None:
        super().__init__(coordinator, entry, f"time_period_{index + 1}_mode")
        self._index = index
        self._attr_name = f"Zeitrahmen {index + 1} Lademodus"

    @property
    def extra_state_attributes(self) -> dict[str, bool]:
        return {
            "Zeitfenster laut Portal-Modus ausgewählt": time_period_selected(
                self.coordinator, self._index
            )
        }

    @property
    def available(self) -> bool:
        return super().available and self.settings_generation == "g2T" and bool(time_period(self.coordinator, self._index))

    @property
    def current_option(self) -> str | None:
        value = time_period(self.coordinator, self._index).get("chargeMode")
        return next((name for name, mode in G2_MODES.items() if mode == value), None)

    async def async_select_option(self, option: str) -> None:
        if option not in G2_MODES:
            raise HomeAssistantError("Unbekannter Lademodus")
        try:
            await self.coordinator.api.async_update_time_period(
                self._index, charge_mode=G2_MODES[option]
            )
        except (AuthenticationError, PortalConnectionError, ValueError) as err:
            raise HomeAssistantError(str(err) or "Der Zeitrahmen wurde nicht übernommen") from err
        await self.coordinator.async_request_refresh()
