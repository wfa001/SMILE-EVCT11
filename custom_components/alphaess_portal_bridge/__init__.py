"""Set up AlphaESS Portal Bridge."""
# ---------------------------------------------------------------------------
# Community-Build fuer https://www.storion4you.de/
# G2T-Erweiterung fuer SMILE-G3-EVCT11/S: Kavino
# Basierend auf dem Ausgangsprojekt wfa001/SMILE-EVCT11.
# Details und Attribution: siehe README.md im Paket.
# ---------------------------------------------------------------------------
from __future__ import annotations

from pathlib import Path
import logging

from datetime import timedelta

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry, ConfigEntryNotReady
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_interval

from .api import AlphaESSPortalApi
from .api_history import ApiHistory, purge_expired_archives, remove_archive
from .const import (
    CONF_PASSWORD,
    CONF_RECORD_API_HISTORY,
    CONF_SYSTEM_SERIAL,
    CONF_USERNAME,
    CONF_WALLBOX_SERIAL,
    CONF_UPDATE_INTERVAL,
    DEFAULT_G2T_UPDATE_INTERVAL_SECONDS,
    DEFAULT_UPDATE_INTERVAL_SECONDS,
    DOMAIN,
    UPDATE_INTERVAL_OPTIONS,
)
from .coordinator import AlphaESSWallboxCoordinator
from .diagnostics_archive import DiagnosticsArchiveView

_LOGGER = logging.getLogger(__name__)

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
    """Register profile images and the advanced diagnostics download."""
    hass.http.register_view(DiagnosticsArchiveView(hass))

    async def prune_history(_now=None) -> None:
        await hass.async_add_executor_job(purge_expired_archives, hass.config.path(".storage"))

    await prune_history()
    async_track_time_interval(hass, prune_history, timedelta(hours=1))
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
    try:
        from .dashboard import DashboardExportView

        hass.http.register_view(DashboardExportView(hass))
    except Exception:
        _LOGGER.exception("Dashboard export unavailable; wallbox setup continues")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a validated portal session without exposing credentials."""
    api = AlphaESSPortalApi(hass, dict(entry.data))
    api.history = ApiHistory(
        hass, entry.entry_id, entry.options.get(CONF_RECORD_API_HISTORY, True),
        tuple(entry.data.get(key, "") for key in (CONF_SYSTEM_SERIAL, CONF_WALLBOX_SERIAL, CONF_USERNAME)),
        entry.data[CONF_PASSWORD],
    )
    api.history.record("bridge", event="recording_started")
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
        await api.history.async_close()
        raise
    configured_interval = entry.options.get(CONF_UPDATE_INTERVAL)
    if configured_interval not in UPDATE_INTERVAL_OPTIONS:
        generation = AlphaESSPortalApi.wallbox_generation(coordinator.data)
        configured_interval = (
            DEFAULT_UPDATE_INTERVAL_SECONDS
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

    # These report-backed sensors were removed because AlphaESS reports can
    # lag well behind live charging. Clear their registry entries so upgrades
    # do not leave permanently unavailable entities behind.
    for unique_id in (
        f"{system_serial}_today_report_energy",
        f"{system_serial}_latest_charge_report",
    ):
        old_entity_id = entity_registry.async_get_entity_id(
            Platform.SENSOR, DOMAIN, unique_id
        )
        if old_entity_id:
            entity_registry.async_remove(old_entity_id)

    desired_title = f"AlphaESS Wallbox {system_serial}"
    if entry.title != desired_title:
        hass.config_entries.async_update_entry(entry, title=desired_title)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.start_live_polling()
    entry.async_on_unload(async_track_time_interval(
        hass, api.history.async_flush, timedelta(seconds=10)
    ))
    entry.async_on_unload(hass.bus.async_listen_once(
        EVENT_HOMEASSISTANT_STOP, api.history.async_close
    ))
    try:
        from .dashboard import async_setup_dashboard

        await async_setup_dashboard(hass, entry, coordinator)
    except Exception:
        _LOGGER.exception("Managed dashboard unavailable; wallbox integration remains active")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the portal session."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        try:
            from .dashboard import async_unload_dashboard

            async_unload_dashboard(hass, entry.entry_id)
        except Exception:
            _LOGGER.exception("Managed dashboard cleanup failed")
        coordinator = hass.data[DOMAIN].pop(entry.entry_id, None)
        if coordinator is not None:
            coordinator.stop_followup_refresh()
            coordinator.stop_live_polling()
            await coordinator.api.history.async_close()
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove local diagnostics when the user deletes the Bridge entry."""
    try:
        await hass.async_add_executor_job(remove_archive, hass.config.path(".storage"), entry.entry_id)
    except OSError:
        _LOGGER.warning("Could not remove local AlphaESS API diagnostics history")
