"""Managed Lovelace dashboard lifecycle and authenticated template downloads.

Lovelace currently has no public API for integration-owned dashboards. Keep
that small compatibility boundary here, away from cloud/charging operations.
"""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from aiohttp import web
import yaml

from homeassistant.components import frontend
from homeassistant.components.http import HomeAssistantView
from homeassistant.components.http.auth import async_sign_path
from homeassistant.components.lovelace.const import LOVELACE_DATA, MODE_YAML
from homeassistant.components.lovelace.dashboard import LovelaceConfig
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import UnitOfEnergy
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.recorder import get_instance as get_recorder_instance
from homeassistant.helpers.json import cached_json_fragment

from .const import CONF_SHOW_DASHBOARD, CONF_SYSTEM_SERIAL, DIAGNOSTICS_DOWNLOAD_PATH, DOMAIN
from .dashboard_builder import WallboxDashboard, build_dashboard
from .dashboard_capabilities import supported_dashboard_controls
from .entity import settings_object

_LOGGER = logging.getLogger(__name__)
DATA_MANAGER = f"{DOMAIN}_managed_dashboard"
BASE_PATH = "alphaess-wallbox-bridge"
EXPORT_PATH = f"/api/{DOMAIN}/dashboard/export"

# These stable suffixes are the keys used by AlphaESSWallboxEntity. No entity
# name, area name, translation, system serial or account identifier is guessed.
ENTITY_DOMAINS = {
    **{key: "sensor" for key in (
        "status", "api_connection", "power", "vehicle_connected", "gun_locked", "mode",
        "today_energy", "last_energy", "portal_profile", "information_model",
        "information_sn", "information_softwareVersion", "information_hardwareVersion",
        "information_phase", "information_startUpPower")},
    **{key: "select" for key in ("charge_mode_select", "charge_strategy_select", "obc_phase_select")},
    **{key: "number" for key in ("custom_charge_current", "household_current")},
    **{key: "switch" for key in ("smart_mode", "installer_control_allowed", "gun_line_self_lock_enabled")},
    **{key: "button" for key in ("start", "stop")},
}
for _index in range(1, 4):
    for _suffix, _domain in (("start", "time"), ("end", "time"), ("enabled", "switch"),
                             ("mode", "select"), ("current", "number")):
        ENTITY_DOMAINS[f"time_period_{_index}_{_suffix}"] = _domain


def resolve_entities(registry, entry) -> dict[str, str]:
    """Resolve by unique ID, platform AND config entry, ignoring disabled rows."""
    resolved = {}
    serial = entry.data[CONF_SYSTEM_SERIAL]
    for key, domain in ENTITY_DOMAINS.items():
        entity_id = registry.async_get_entity_id(domain, DOMAIN, f"{serial}_{key}")
        if not entity_id:
            continue
        row = registry.async_get(entity_id)
        if row and row.config_entry_id == entry.entry_id and not row.disabled_by:
            resolved[key] = entity_id
    return resolved


def filter_capabilities(entities: dict[str, str], profile: str | None,
                        settings: dict[str, Any]) -> dict[str, str]:
    """Distinguish unsupported fields from temporary unavailable live values."""
    supported = supported_dashboard_controls(profile, settings)
    return {key: entity for key, entity in entities.items()
            if ENTITY_DOMAINS.get(key) not in {"select", "number", "switch", "time", "button"}
            or key in supported}


def daily_statistics_eligibility(hass, entity_id: str | None) -> tuple[bool, str | None]:
    """Check local prerequisites, not whether historical database rows exist."""
    state = hass.states.get(entity_id) if entity_id else None
    if state is None:
        return False, "Der Tageszähler ist noch nicht verfügbar."
    attrs = state.attributes
    if (attrs.get('device_class') != 'energy'
            or attrs.get('state_class') != 'total_increasing'
            or attrs.get('unit_of_measurement') not in UnitOfEnergy):
        return False, "Der Tageszähler hat keine geeignete Energieeinheit oder Summenstatistik."
    try:
        recorder = get_recorder_instance(hass)
    except KeyError:
        return False, "Recorder ist nicht aktiv; Tagesstatistiken können nicht aufgezeichnet werden."
    if recorder.entity_filter is not None and not recorder.entity_filter(entity_id):
        return False, "Der Tageszähler ist von der Recorder-Aufzeichnung ausgeschlossen."
    return True, None


class ManagedDashboard(LovelaceConfig):
    """Read-only, generated on every request; nothing is saved over user YAML."""

    def __init__(self, manager) -> None:
        super().__init__(manager.hass, manager.url_path, {
            "title": "Wallbox Bridge", "icon": "mdi:ev-station",
            "show_in_sidebar": True, "require_admin": False, "mode": MODE_YAML,
        })
        self.manager = manager

    @property
    def mode(self) -> str:
        return MODE_YAML

    async def async_load(self, force: bool) -> dict:
        return self.manager.build()

    async def async_get_info(self) -> dict:
        return {"mode": self.mode, "views": len(self.manager.build()["views"])}

    async def async_json(self, force: bool):
        # No cross-user cache: download links are signed in the requesting context.
        return cached_json_fragment(self.manager.build())


class DashboardExportView(HomeAssistantView):
    """Only dashboard presentation data; never raw coordinator or config data."""

    url = EXPORT_PATH + "/{entry_id}"
    name = f"api:{DOMAIN}:dashboard-export"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request, entry_id: str) -> web.Response:
        manager = self.hass.data.get(DATA_MANAGER)
        if manager is None or entry_id not in manager.entries:
            raise web.HTTPNotFound()
        config = manager.build(entry_id=entry_id, export=True)
        payload = yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
        return web.Response(text=payload, content_type="application/yaml", headers={
            "Content-Disposition": 'attachment; filename="alphaess_wallbox_dashboard.yaml"',
            "Cache-Control": "no-store",
        })


class DashboardManager:
    """One panel shared by loaded bridge entries, removed with the last entry."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.entries: dict[str, tuple[Any, Any]] = {}
        self.unsubscribers: dict[str, Any] = {}
        lovelace = hass.data[LOVELACE_DATA]
        path = BASE_PATH
        index = 2
        while path in lovelace.dashboards or frontend.async_panel_exists(hass, path):
            path = f"{BASE_PATH}-{index}"
            index += 1
        self.url_path = path
        self.dashboard = ManagedDashboard(self)
        lovelace.dashboards[path] = self.dashboard
        try:
            frontend.async_register_built_in_panel(
                hass, "lovelace", sidebar_title="Wallbox Bridge", sidebar_icon="mdi:ev-station",
                frontend_url_path=path, config={"mode": MODE_YAML}, require_admin=False,
            )
        except Exception:
            lovelace.dashboards.pop(path, None)
            raise
        self._unsub_registry = hass.bus.async_listen("entity_registry_updated", self._registry_changed)

    @callback
    def _registry_changed(self, event) -> None:
        # Renames, enable/disable, unit overrides and late platform registrations.
        self.dashboard._config_updated()

    def build(self, *, entry_id: str | None = None, export: bool = False) -> dict:
        registry = er.async_get(self.hass)
        boxes = []
        for key, (entry, coordinator) in self.entries.items():
            if entry_id is not None and key != entry_id:
                continue
            profile, settings = settings_object(coordinator)
            entities = filter_capabilities(resolve_entities(registry, entry), profile, settings)
            power = self.hass.states.get(entities.get("power", ""))
            energy_statistics, energy_note = daily_statistics_eligibility(
                self.hass, entities.get('today_energy'))
            title = entry.title
            device = dr.async_get(self.hass).async_get_device(identifiers={
                (DOMAIN, entry.data[CONF_SYSTEM_SERIAL])})
            if device and device.name_by_user:
                title = device.name_by_user
            url = None if export else async_sign_path(
                self.hass, f"{EXPORT_PATH}/{entry.entry_id}", timedelta(minutes=10))
            boxes.append(WallboxDashboard(
                entry_id=entry.entry_id, title=title, profile=profile, entities=entities,
                settings=settings, power_unit=power.attributes.get("unit_of_measurement", "W") if power else "W",
                energy_statistics=energy_statistics, energy_statistics_note=energy_note,
                export_url=url,
                diagnostics_path=None if export else f"{DIAGNOSTICS_DOWNLOAD_PATH}/{entry.entry_id}",
            ))
        # An exported independent dashboard navigates within itself, not back to the managed panel.
        config = build_dashboard(boxes, url_path=self.url_path, export=export)
        if export:
            self._relative_links(config)
        return config

    def _relative_links(self, value) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if isinstance(child, str):
                    value[key] = child.replace(f"/{self.url_path}/", "")
                else:
                    self._relative_links(child)
        elif isinstance(value, list):
            for child in value:
                self._relative_links(child)

    @callback
    def add(self, entry, coordinator) -> None:
        self.remove(entry.entry_id, close=False)
        self.entries[entry.entry_id] = (entry, coordinator)
        # Only reload layout for capability changes, not on every live power update.
        previous = None

        @callback
        def config_changed() -> None:
            nonlocal previous
            profile, settings = settings_object(coordinator)
            entities = filter_capabilities(resolve_entities(er.async_get(self.hass), entry), profile, settings)
            energy_ready = daily_statistics_eligibility(self.hass, entities.get('today_energy'))
            power = self.hass.states.get(entities.get('power', ''))
            power_unit = power.attributes.get('unit_of_measurement', 'W') if power else 'W'
            signature = (profile, tuple(sorted(filter_capabilities(ENTITY_DOMAINS, profile, settings))),
                         energy_ready, power_unit)
            if signature != previous:
                previous = signature
                self.dashboard._config_updated()

        self.unsubscribers[entry.entry_id] = coordinator.async_add_listener(config_changed)
        config_changed()
        self.dashboard._config_updated()

    @callback
    def remove(self, entry_id: str, *, close: bool = True) -> None:
        if unsubscribe := self.unsubscribers.pop(entry_id, None):
            unsubscribe()
        self.entries.pop(entry_id, None)
        if not close:
            return
        self.dashboard._config_updated()
        if self.entries:
            return
        self._unsub_registry()
        lovelace = self.hass.data.get(LOVELACE_DATA)
        if lovelace and lovelace.dashboards.get(self.url_path) is self.dashboard:
            lovelace.dashboards.pop(self.url_path)
            frontend.async_remove_panel(self.hass, self.url_path)
        self.hass.data.pop(DATA_MANAGER, None)


async def async_setup_dashboard(hass: HomeAssistant, entry, coordinator) -> None:
    """Register this wallbox if its managed dashboard is enabled."""
    if not entry.options.get(CONF_SHOW_DASHBOARD, True):
        return

    try:
        manager = hass.data.get(DATA_MANAGER)
        if manager is None:
            manager = DashboardManager(hass)
            hass.data[DATA_MANAGER] = manager
        manager.add(entry, coordinator)
    except Exception:
        _LOGGER.exception("Wallbox dashboard could not be registered; wallbox integration remains active")


@callback
def async_unload_dashboard(hass: HomeAssistant, entry_id: str) -> None:
    if manager := hass.data.get(DATA_MANAGER):
        manager.remove(entry_id)
