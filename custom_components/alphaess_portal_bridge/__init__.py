"""Set up AlphaESS Portal Bridge."""
# ---------------------------------------------------------------------------
# Community-Build fuer https://www.storion4you.de/
# G2T-Erweiterung fuer SMILE-G3-EVCT11/S: Kavino
# Basierend auf dem Ausgangsprojekt wfa001/SMILE-EVCT11.
# Details und Attribution: siehe README.md im Paket.
# ---------------------------------------------------------------------------
from __future__ import annotations

from pathlib import Path

from datetime import timedelta

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry, ConfigEntryNotReady
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .api import AlphaESSPortalApi
from .const import (
    CONF_SYSTEM_SERIAL,
    CONF_UPDATE_INTERVAL,
    DEFAULT_G2T_UPDATE_INTERVAL_SECONDS,
    DEFAULT_UPDATE_INTERVAL_SECONDS,
    DOMAIN,
    UPDATE_INTERVAL_OPTIONS,
)
from .coordinator import AlphaESSWallboxCoordinator

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.TIME,
]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate older config entries to the current integration version."""
    if entry.version > 2:
        return False

    if entry.version == 1:
        # Version 2 adds G2T support and an optional wallbox serial in the
        # config flow, but the persisted v1 data schema remains valid.
        # Therefore no user data has to be changed; only the entry version
        # needs to be advanced so Home Assistant can load it.
        hass.config_entries.async_update_entry(entry, version=2)

    return True


async def async_setup(hass: HomeAssistant, config: dict[str, object]) -> bool:
    """Register the profile images served to the Home Assistant frontend."""
    image_dir = Path(__file__).parent
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                f"/api/{DOMAIN}/profiles/g1t.png",
                str(image_dir / "g1t.png"),
                cache_headers=True,
            ),
            StaticPathConfig(
                f"/api/{DOMAIN}/profiles/g2t.png",
                str(image_dir / "g2t.png"),
                cache_headers=True,
            ),
        ]
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a validated portal session without exposing credentials."""
    api = AlphaESSPortalApi(hass, dict(entry.data))
    coordinator = AlphaESSWallboxCoordinator(
        hass,
        api,
        update_interval_seconds=entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_SECONDS
        ),
    )
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        raise
    configured_interval = entry.options.get(CONF_UPDATE_INTERVAL)
    if configured_interval not in UPDATE_INTERVAL_OPTIONS:
        generation = AlphaESSPortalApi.wallbox_generation(coordinator.data)
        configured_interval = (
            DEFAULT_G2T_UPDATE_INTERVAL_SECONDS
            if generation == "g2T"
            else DEFAULT_UPDATE_INTERVAL_SECONDS
        )
        coordinator.update_interval = timedelta(seconds=configured_interval)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    system_serial = entry.data[CONF_SYSTEM_SERIAL]

    # 0.5.3 changes the two user-facing yes/no values from generic binary
    # sensors (rendered as Ein/Aus) to normal sensors (Ja/Nein). Remove the
    # obsolete registry entries so Home Assistant does not leave unavailable
    # duplicates behind after the upgrade.
    entity_registry = er.async_get(hass)
    for unique_id in (
        f"{system_serial}_vehicle_connected",
        f"{system_serial}_gun_locked",
    ):
        old_entity_id = entity_registry.async_get_entity_id(
            Platform.BINARY_SENSOR, DOMAIN, unique_id
        )
        if old_entity_id:
            entity_registry.async_remove(old_entity_id)

    # 0.5.4 promotes Hausstrom-Einstellung from a read-only sensor to a
    # writable number entity. Remove the former sensor registry entry first.
    old_household_entity_id = entity_registry.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{system_serial}_household_current"
    )
    if old_household_entity_id:
        entity_registry.async_remove(old_household_entity_id)

    # 0.5.11 promotes the two app-only diagnostic flags to writable switches.
    # Remove their former binary-sensor registry entries so Home Assistant
    # does not keep unavailable duplicates after the upgrade.
    for unique_id in (
        f"{system_serial}_installer_control_allowed",
        f"{system_serial}_gun_line_self_lock_enabled",
    ):
        old_entity_id = entity_registry.async_get_entity_id(
            Platform.BINARY_SENSOR, DOMAIN, unique_id
        )
        if old_entity_id:
            entity_registry.async_remove(old_entity_id)

    # 0.5.5 hides the portal's Power Share diagnostics for this G2T model.
    # The EVCT11/S reports availability=HIDDEN_NOT_SUPPORTED and
    # powerShareRole=STANDALONE, so these values do not represent a usable
    # feature on the installed single-wallbox setup. Remove stale registry
    # entries from earlier test builds.
    for platform, unique_id in (
        (Platform.SENSOR, f"{system_serial}_power_share_role"),
        (Platform.BINARY_SENSOR, f"{system_serial}_power_share_enabled"),
    ):
        old_entity_id = entity_registry.async_get_entity_id(platform, DOMAIN, unique_id)
        if old_entity_id:
            entity_registry.async_remove(old_entity_id)

    desired_title = f"AlphaESS Wallbox {system_serial}"
    if entry.title != desired_title:
        hass.config_entries.async_update_entry(entry, title=desired_title)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the portal session."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id, None)
        if coordinator is not None:
            coordinator.stop_followup_refresh()
    return unload_ok
