"""Authenticated, session-based access to the AlphaESS customer portal."""
# ---------------------------------------------------------------------------
# Community-Build fuer https://www.storion4you.de/
# G2T-Erweiterung fuer SMILE-G3-EVCT11/S: Kavino
# Basierend auf dem Ausgangsprojekt wfa001/SMILE-EVCT11.
# Details und Attribution: siehe NOTICE.md im Paket.
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import base64
import copy
from collections.abc import Callable
from datetime import timedelta
from functools import wraps
import hashlib
import logging
from math import isfinite
import re
import time
from typing import Any

import aiohttp
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .schedule import schedule_supported, strategy_supported
from .write_feedback import SettingsWriteFeedback, settings_targets

from .const import (
    API_URL,
    CONF_AUTHENTICATION_PAUSED,
    CONF_PASSWORD,
    CONF_SYSTEM_SERIAL,
    CONF_USERNAME,
    CONF_WALLBOX_SERIAL,
)

_LOGGER = logging.getLogger(__name__)

PORTAL_HEADERS = {
    "Tenant": "alphaess",
    "Client-End": "Web",
    "Client-Name": "Portal",
}


class AuthenticationError(Exception):
    """The portal did not authorize the current session."""

    def __init__(self, step: str = "login", *, status: int | None = None) -> None:
        self.step = step
        self.status = status
        super().__init__(f"Portal authorization failed during {step}")


class PortalConnectionError(Exception):
    """The portal could not be reached or rejected a request."""

    def __init__(self, status: int | None = None, step: str = "connection") -> None:
        self.status = status
        self.step = step
        super().__init__(f"Portal request failed during {step}: {status}")


def _serialize_settings_write(method):
    """Serialize settings updates; coalesce only queued current-only requests.

    Once a PATCH has started it cannot safely be cancelled: the portal might
    accept the request despite a client-side cancellation or timeout. A newer
    charge-current request supersedes older *waiting* requests, not an
    in-flight write. No artificial delay is added to wallbox commands.
    """

    @wraps(method)
    async def wrapped(self, *args, **kwargs):
        request_id = None
        if (
            method.__name__ == "async_update_wallbox_settings"
            and len(kwargs) == 1
            and "charge_current" in kwargs
            and isinstance(kwargs["charge_current"], int)
            and not isinstance(kwargs["charge_current"], bool)
            and 6 <= kwargs["charge_current"] <= 16
        ):
            self._charge_current_request_id += 1
            request_id = self._charge_current_request_id

        async with self._settings_write_lock:
            if (
                request_id is not None
                and request_id != self._charge_current_request_id
            ):
                # The user requested a newer current while this call waited.
                # Only drop a request which never began its portal transaction.
                return
            self._settings_request_context = (method.__name__, args, kwargs)
            try:
                return await method(self, *args, **kwargs)
            finally:
                self._settings_request_context = None

    return wrapped


class AlphaESSPortalApi:
    """Keep an AlphaESS customer-portal session in memory."""

    def __init__(self, hass: HomeAssistant, config: dict[str, Any]) -> None:
        self._session = async_get_clientsession(hass)
        self.history = None
        self._token_lock = asyncio.Lock()
        self._authentication_error: AuthenticationError | None = (
            AuthenticationError("reauthentication required")
            if config.get(CONF_AUTHENTICATION_PAUSED)
            else None
        )
        self._settings_write_lock = asyncio.Lock()
        self._live_status_lock = asyncio.Lock()
        self._live_status_cache: dict[str, Any] | None = None
        self._live_status_cached_at = 0.0
        self._live_status_cached_serial: str | None = None
        self._live_status_unavailable_serials: set[str] = set()
        self._charge_current_request_id = 0
        self._settings_written_callback: Callable[[], None] | None = None
        self.settings_feedback = SettingsWriteFeedback()
        self._settings_request_context = None
        self._username = config[CONF_USERNAME]
        self._password = config[CONF_PASSWORD]
        self._system_serial = config[CONF_SYSTEM_SERIAL]
        self._wallbox_serial = config.get(CONF_WALLBOX_SERIAL)
        self._token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at = 0.0
        self._api_url = API_URL
        self._report_cache: dict[str, Any] = {}
        self._report_items_cache: list[dict[str, Any]] = []
        self._report_cache_until = 0.0
        self._report_cache_date: str | None = None
        self._energy_site: str | None = None
        self._energy_site_until = 0.0
        self._site_energy: tuple[str, float] | None = None
        self._site_energy_key: tuple[str, str] | None = None
        self._site_energy_until = 0.0

    def set_settings_written_callback(
        self, callback: Callable[[], None] | None
    ) -> None:
        """Register a non-blocking UI refresh notification after PATCH."""
        self._settings_written_callback = callback

    async def async_validate_login(self) -> None:
        """Validate access to the configured AlphaESS system."""
        # Keep the proven compact request for login validation. G2T is read from
        # the full system document after setup; adding an unknown component here
        # could make otherwise valid portals reject the setup request.
        await self._async_get(
            f"/internal/v1/ess/{self._system_serial}",
            params={"components": "basic,g1T"},
            step="system check",
        )

    async def async_get_live_status(self, wallbox_serial: str) -> dict[str, Any]:
        """Read live G2T values without fetching settings or charging reports.

        A brief shared cache avoids duplicate GETs when a full refresh happens
        at the same moment as a five-second live refresh.
        """
        async with self._live_status_lock:
            if (
                self._live_status_cached_serial == wallbox_serial
                and self._live_status_cache is not None
                and time.monotonic() - self._live_status_cached_at < 3
            ):
                if history := getattr(self, "history", None):
                    history.record("bridge", event="cache_hit", step="wallbox status")
                return copy.deepcopy(self._live_status_cache)
            status = await self._async_get(
                f"/internal/v1/ev-charger/{wallbox_serial}/real-status",
                step="wallbox status",
            )
            self._live_status_cache = copy.deepcopy(status)
            self._live_status_cached_serial = wallbox_serial
            self._live_status_cached_at = time.monotonic()
            return status

    async def async_get_wallbox_data(self) -> dict[str, Any]:
        """Read wallbox configuration, live state and the latest charge report."""
        system = await self._async_get(
            f"/internal/v1/ess/{self._system_serial}",
            params={"components": "basic,g1T"},
            step="system check",
        )
        try:
            configuration = await self._async_get(
                f"/internal/v1/ess/{self._system_serial}",
                step="wallbox configuration",
            )
            configuration_read_ok = isinstance(configuration, (dict, list))
        except PortalConnectionError:
            configuration = {}
            configuration_read_ok = False

        wallbox_serial = (
            self._wallbox_serial
            or self._find_wallbox_serial(configuration)
            or self._find_wallbox_serial(system)
        )
        if history := getattr(self, "history", None):
            history.add_identifier(wallbox_serial)
        wallbox_status = self._find_wallbox_data(system, wallbox_serial)
        wallbox_status_source = "system"

        generation, _ = self._settings_from_wallbox(
            self._find_wallbox_data(configuration, wallbox_serial)
        )
        if wallbox_serial and wallbox_serial not in self._live_status_unavailable_serials:
            try:
                wallbox_status = await self.async_get_live_status(wallbox_serial)
                wallbox_status_source = "real_status"
            except PortalConnectionError as err:
                # G1T may not implement real-status at all; preserve system
                # fallback for both initial and later full refreshes.
                if err.status == 404 and generation == "g1T":
                    self._live_status_unavailable_serials.add(wallbox_serial)
                elif err.status != 409:
                    raise

        latest_report: dict[str, Any] = {}
        today_report_energy: float | None = None
        if wallbox_serial:
            try:
                report_items = await self.async_get_charge_report_items(wallbox_serial)
                latest_report = report_items[0] if report_items else {}
                today_report_energy = self._today_energy_from_report(report_items)
            except PortalConnectionError:
                # Reporting is supplemental and must not make the wallbox itself
                # unavailable when the report endpoint has a temporary problem.
                latest_report = self._report_cache
                if self._report_items_cache:
                    today_report_energy = self._today_energy_from_report(self._report_items_cache)

        site_daily_energy = (
            await self._async_get_site_daily_energy(wallbox_serial)
            if wallbox_serial and generation == "g1T" else None
        )
        return {
            "system": system,
            "configuration": configuration,
            "configuration_read_ok": configuration_read_ok,
            "wallbox_serial": wallbox_serial,
            "wallbox_status": wallbox_status,
            "wallbox_status_source": wallbox_status_source,
            "latest_report": latest_report,
            "today_report_energy": today_report_energy,
            "site_daily_energy": site_daily_energy,
        }

    async def _async_find_energy_site(self, wallbox_serial: str) -> str | None:
        """Match the configured inverter and its wallbox to one single-wallbox site."""
        sites = await self._async_get(
            "/internal/v1/sites", params={"snTypes": "residential,commercial"},
            step="energy site list", supplemental=True,
        )
        if not isinstance(sites, list):
            return None
        history = self.history
        if history:
            history.record("bridge", event="energy_site_list", site_count=len(sites))
        matches = set()
        for index, site in enumerate(sites, start=1):
            site_id = site.get("id") if isinstance(site, dict) else None
            if not isinstance(site_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", site_id):
                continue
            devices = await self._async_get(
                f"/internal/v1/sites/{site_id}/devices",
                step="energy site devices", supplemental=True,
            )
            if not isinstance(devices, dict):
                continue
            systems = devices.get("ess")
            others = devices.get("others", [])
            if not isinstance(systems, list) or not isinstance(others, list):
                continue
            wallboxes = set()
            for device in others:
                if isinstance(device, dict) and device.get("type") == "EvCharger":
                    serial = device.get("sysSn")
                    wallboxes.add(serial if isinstance(serial, str) else None)
            matched_inverter = False
            for system in systems:
                if not isinstance(system, dict):
                    continue
                chargers = system.get("evChargers", [])
                if not isinstance(chargers, list):
                    wallboxes.add(None)
                    continue
                serials = {
                    charger.get("sysSn") if isinstance(charger, dict)
                    and isinstance(charger.get("sysSn"), str) else None
                    for charger in chargers
                }
                wallboxes.update(serials)
                if system.get("sysSn") == self._system_serial and wallbox_serial in serials:
                    matched_inverter = True
            eligible = matched_inverter and wallboxes == {wallbox_serial}
            if history:
                history.record(
                    "bridge", event="energy_site_devices", candidate=index,
                    inverter_and_wallbox_match=matched_inverter, wallbox_count=len(wallboxes),
                    eligible=eligible,
                )
            if eligible:
                matches.add(site_id)
        if history:
            history.record("bridge", event="energy_site_match", match_count=len(matches))
        return next(iter(matches)) if len(matches) == 1 else None

    async def _async_get_site_daily_energy(self, wallbox_serial: str) -> tuple[str, float] | None:
        """Read the portal's daily kWh, with a separate five-minute cache."""
        day = dt_util.now().date().isoformat()
        key = (wallbox_serial, day)
        if self._site_energy_key == key and time.monotonic() < self._site_energy_until:
            return self._site_energy
        if self._site_energy_key is not None and self._site_energy_key[0] != wallbox_serial:
            self._energy_site_until = 0.0
            self._site_energy = None
        self._site_energy_key = key
        if self._site_energy and self._site_energy[0] != day:
            self._site_energy = None
        self._site_energy_until = time.monotonic() + 300
        try:
            if time.monotonic() >= self._energy_site_until:
                site_id = await self._async_find_energy_site(wallbox_serial)
                if site_id != self._energy_site:
                    self._site_energy = None
                self._energy_site = site_id
                self._energy_site_until = time.monotonic() + 3600
            if self._energy_site is None:
                self._site_energy = None
                if self.history:
                    self.history.record("bridge", event="site_daily_energy", day=day,
                                        result="no_unique_site")
                return None
            response = await self._async_get(
                f"/internal/v1/sites/{self._energy_site}/energy",
                params={"startDate": day, "endDate": day, "dimension": "day"},
                step="site daily energy", supplemental=True,
            )
        except PortalConnectionError:
            if self.history:
                self.history.record("bridge", event="site_daily_energy", day=day,
                                    result="request_failed", cached_kwh=self._site_energy[1] if self._site_energy else None)
            return self._site_energy
        value = self._site_load_by_day(response, "evCharge").get(day)
        consumption = self._site_consumption_by_day(response).get(day)
        result = self._site_energy_result(value, consumption)
        self._site_energy = (day, value) if result == "accepted" and value is not None else None
        if self.history:
            self.history.record(
                "bridge", event="site_daily_energy", day=day,
                result=result, kwh=value, consumption_kwh=consumption,
            )
        return self._site_energy

    @staticmethod
    def _site_kwh(raw: Any) -> float | None:
        if isinstance(raw, dict):
            raw = raw.get("parsedValue")
        if type(raw) not in (int, float):
            return None
        try:
            value = float(raw)
        except OverflowError:
            return None
        return value if isfinite(value) and value >= 0 else None

    @classmethod
    def _site_load_by_day(cls, response: Any, source: str) -> dict[str, float]:
        """Decode a portal load series aligned with the dates in the response."""
        flows = response.get(source) if isinstance(response, dict) else None
        values = flows.get("load") if isinstance(flows, dict) else None
        dates = response.get("ts") if isinstance(response, dict) else None
        if not isinstance(dates, list) or not isinstance(values, list) or len(dates) != len(values):
            return {}
        if not all(isinstance(day, str) for day in dates) or len(set(dates)) != len(dates):
            return {}
        return {
            day: value for day, raw in zip(dates, values, strict=True)
            if (value := cls._site_kwh(raw)) is not None
        }

    @classmethod
    def _site_consumption_by_day(cls, response: Any) -> dict[str, float]:
        if not isinstance(response, dict):
            return {}
        dates = response.get("ts")
        summary = response.get("summary")
        if (isinstance(dates, list) and len(dates) == 1 and isinstance(dates[0], str)
                and isinstance(summary, dict)
                and (value := cls._site_kwh(summary.get("consumption"))) is not None):
            return {dates[0]: value}
        solar, battery, grid = (
            cls._site_load_by_day(response, source) for source in ("selfGeneration", "battery", "grid")
        )
        return {
            day: round(total, 3) for day in solar.keys() & battery.keys() & grid.keys()
            if isfinite(total := solar[day] + battery[day] + grid[day])
        }

    @staticmethod
    def _site_energy_result(value: float | None, consumption: float | None) -> str:
        if value is None:
            return "invalid_or_missing"
        if consumption is None:
            return "consumption_missing"
        # Allow small rounding differences between the portal's energy series.
        if value - consumption > max(0.1, consumption * 0.01):
            return "implausible"
        return "accepted"

    async def async_get_site_energy_diagnostics(self, wallbox_serial: str) -> dict[str, Any]:
        """Sample the last seven calendar days on demand for the diagnostic ZIP."""
        today = dt_util.now().date()
        days = [(today - timedelta(days=offset)).isoformat() for offset in range(6, -1, -1)]
        result = {"source": "evCharge.load", "start_date": days[0], "end_date": days[-1]}
        try:
            async with asyncio.timeout(8):
                site_id = await self._async_find_energy_site(wallbox_serial)
                if site_id is None:
                    return {**result, "site_match": False, "result": "no_unique_site"}
                result["site_match"] = True
                response = await self._async_get(
                    f"/internal/v1/sites/{site_id}/energy",
                    params={"startDate": days[0], "endDate": days[-1], "dimension": "day"},
                    step="site energy seven days", supplemental=True,
                )
        except (TimeoutError, AuthenticationError, PortalConnectionError) as err:
            return {**result, "result": "request_failed", "http_status": getattr(err, "status", None)}
        readings = self._site_load_by_day(response, "evCharge")
        consumption = self._site_consumption_by_day(response)
        days_with_values = sum(day in readings for day in days)
        return {
            **result,
            "result": "received" if days_with_values else "invalid_or_missing",
            "days": [
                {"date": day, "kwh": readings.get(day), "consumption_kwh": consumption.get(day),
                 "result": self._site_energy_result(readings.get(day), consumption.get(day))}
                for day in days
            ],
        }

    async def async_get_charge_report_items(self, wallbox_serial: str) -> list[dict[str, Any]]:
        """Return recent charging sessions, cached to reduce portal traffic."""
        today = dt_util.now().date().isoformat()
        if (
            self._report_cache_date == today
            and time.monotonic() < self._report_cache_until
        ):
            if history := getattr(self, "history", None):
                history.record("bridge", event="cache_hit", step="charge report")
            return self._report_items_cache

        # pageSize=10 is known to be accepted by the G2T portal.  Continue
        # paging only while a full page still contains sessions from today.
        # This keeps normal traffic at one request but does not truncate busy
        # days with more than ten sessions.
        items: list[dict[str, Any]] = []
        page_num = 1
        while page_num <= 20:
            report = await self._async_get(
                "/internal/v1/ev-charger/report",
                params={
                    "pageNum": page_num,
                    "pageSize": 10,
                    "startTime": "",
                    "endTime": "",
                    "sysSn": self._system_serial,
                    "chargingPileSn": wallbox_serial,
                },
                step="charge report",
            )
            raw_items = report.get("list") if isinstance(report, dict) else None
            page_items = (
                [item for item in raw_items if isinstance(item, dict)]
                if isinstance(raw_items, list)
                else []
            )
            items.extend(page_items)
            if len(page_items) < 10:
                break
            if any(
                not isinstance(item.get("beginDate"), str)
                or not item["beginDate"].startswith(today)
                for item in page_items
            ):
                break
            page_num += 1
        self._report_items_cache = items
        self._report_cache = items[0] if items else {}
        self._report_cache_until = time.monotonic() + 300
        self._report_cache_date = today
        return items

    async def async_get_latest_charge_report(self, wallbox_serial: str) -> dict[str, Any]:
        """Return the newest charging session, cached to reduce portal traffic."""
        items = await self.async_get_charge_report_items(wallbox_serial)
        return items[0] if items else {}

    @staticmethod
    def _today_energy_from_report(items: list[dict[str, Any]]) -> float:
        """Sum completed report sessions whose start date is today."""
        today = dt_util.now().date().isoformat()
        total = 0.0
        for item in items:
            begin = item.get("beginDate")
            if not isinstance(begin, str) or not begin.startswith(today):
                continue
            value = item.get("chargingCapacity")
            try:
                total += float(value)
            except (TypeError, ValueError):
                continue
        return round(total, 3)

    async def async_control_wallbox(self, control: str) -> None:
        """Send a guarded start or stop request to the wallbox."""
        if control not in {"START", "STOP"}:
            raise ValueError("Nicht unterstützter Wallbox-Befehl")
        history = getattr(self, "history", None)
        if history:
            history.record("control", event="requested", control=control)
        wallbox_serial = self._wallbox_serial
        if not wallbox_serial:
            raise PortalConnectionError(step="wallbox control")

        # Live testing on the G2T confirmed that START/STOP is only acted on
        # when the charging strategy is Manual (chargeStrategy = 0).  Other
        # strategies own the charging decision and can silently ignore the
        # event even though the request itself is accepted.  Keep G1T behavior
        # unchanged and guard only the G2T path.
        configuration = await self._async_get(
            f"/internal/v1/ess/{self._system_serial}",
            step="wallbox control settings",
        )
        wallbox = self._find_wallbox_data(configuration, wallbox_serial)
        generation, settings = self._settings_from_wallbox(wallbox)
        if generation == "g2T" and settings is not None:
            if settings.get("chargeStrategy") != 0:
                if history:
                    history.record("control", event="blocked", control=control, reason="manual strategy required")
                raise ValueError(
                    "Laden starten/stoppen ist nur bei Ladeeinstellung Manuell möglich"
                )

        status_data = await self._async_get(
            f"/internal/v1/ev-charger/{wallbox_serial}/real-status",
            step="wallbox control status",
        )
        status = status_data.get("status") if isinstance(status_data, dict) else None
        allowed = (
            {"PendingStart", "ChargingStopped", "CharingStopped"}
            if control == "START"
            else {"Charging", "WaitingForChargingPile"}
        )
        if status not in allowed:
            if history:
                history.record("control", event="blocked", control=control, reason="wallbox status", status=status)
            raise PortalConnectionError(step="wallbox control blocked")
        await self._async_authenticated_post(
            f"/internal/v1/ev-charger/{wallbox_serial}/events",
            {"control": control},
            step="wallbox control",
        )

    @_serialize_settings_write
    async def async_update_wallbox_settings(
        self,
        *,
        charge_mode: int | None = None,
        charge_current: int | None = None,
        charge_strategy: int | None = None,
        obc_phase: int | None = None,
        smart_mode: bool | None = None,
        household_current: int | None = None,
        installer_control_allowed: bool | None = None,
        gun_line_self_lock_enabled: bool | None = None,
    ) -> None:
        """Update G1T/G2T settings while retaining the complete portal document."""
        configuration = await self._async_get(
            f"/internal/v1/ess/{self._system_serial}", step="wallbox settings"
        )
        payload = copy.deepcopy(configuration)
        wallbox = self._find_wallbox_data(payload, self._wallbox_serial)
        generation, settings = self._settings_from_wallbox(wallbox)
        if settings is None:
            raise PortalConnectionError(step="wallbox settings")

        if charge_mode is not None:
            allowed_modes = {1, 2, 3, 4}
            if charge_mode not in allowed_modes:
                raise ValueError("Nicht unterstützter Lademodus")
            if generation == "g1T" and (
                type(settings.get("chargeMode")) is not int
                or settings["chargeMode"] not in {0, 1, 2, 3, 4}
            ):
                raise ValueError("G1T Lademodus ist im Portal nicht bestätigt")
            if generation == "g2T" and settings.get("smartMode") is True and charge_mode == 4:
                raise ValueError("Smart Mode benötigt Langsamladung, Schonladung oder Schnellladung")
            settings["chargeMode"] = charge_mode

        if charge_current is not None:
            if not 6 <= charge_current <= 16:
                raise ValueError("Der Ladestrom muss zwischen 6 und 16 A liegen")
            if generation == "g1T" and (
                type(settings.get("chargeCurrent")) not in (int, float)
                or not 6 <= settings["chargeCurrent"] <= 16
                or settings["chargeCurrent"] != int(settings["chargeCurrent"])
            ):
                raise ValueError("G1T Ladestrom ist im Portal nicht bestätigt")
            settings["chargeCurrent"] = charge_current

        if charge_strategy is not None:
            if (
                generation not in {"g1T", "g2T"}
                or charge_strategy not in {0, 1, 2}
                or not strategy_supported(generation, settings)
            ):
                raise ValueError("Ladeeinstellung ist für dieses Portal-Schema nicht bestätigt")
            if charge_strategy == 1 and settings.get("smartMode") is True:
                raise ValueError(
                    "Smart Mode vor Wechsel auf Zeitgesteuertes Aufladen deaktivieren"
                )
            settings["chargeStrategy"] = charge_strategy

        if obc_phase is not None:
            if generation != "g2T" or obc_phase not in {1, 2, 3}:
                raise ValueError("Nicht unterstützte OBC-Phasenwahl")
            if settings.get("smartMode") is True and obc_phase != 3:
                raise ValueError("Smart Mode vor Änderung auf 1- oder 2-phasiges Laden deaktivieren")
            settings["obcPhase"] = obc_phase

        if smart_mode is not None:
            if generation != "g2T":
                raise ValueError("Smart Mode ist nur bei G2T-Wallboxen verfügbar")
            if smart_mode:
                # The G2T rejects Smart Mode while chargeStrategy = 1
                # (Zeitgesteuertes Aufladen), even if the active time period
                # itself uses an ECO-capable mode.
                if settings.get("chargeStrategy") == 1:
                    raise ValueError(
                        "Smart Mode ist mit Zeitgesteuertem Aufladen nicht verfügbar"
                    )
                if settings.get("obcPhase") != 3:
                    raise ValueError("Für Smart Mode muss die OBC-Phasenwahl auf 3-phasig stehen")
                if settings.get("chargeMode") not in {1, 2, 3}:
                    raise ValueError("Smart Mode benötigt Langsamladung, Schonladung oder Schnellladung")
            settings["smartMode"] = smart_mode

        if household_current is not None:
            if not 25 <= household_current <= 1000:
                raise ValueError("Die Hausstrom-Einstellung muss zwischen 25 und 1000 A liegen")
            # Unlike chargeMode/obcPhase/etc., houseHoldCurrent lives directly
            # on the wallbox object, not inside the G1T/G2T settings object.
            wallbox["houseHoldCurrent"] = household_current

        if installer_control_allowed is not None:
            # This flag is returned directly on the wallbox object. It is
            # editable in the AlphaESS app although the current web UI does
            # not expose a control for it.
            wallbox["allowInstallersControl"] = bool(installer_control_allowed)

        if gun_line_self_lock_enabled is not None:
            if generation != "g2T":
                raise ValueError("Kabel-Selbstverriegelung ist nur bei G2T-Wallboxen verfügbar")
            if settings.get("isSupportGunLineSelfLock") is not True:
                raise ValueError("Diese Wallbox unterstützt keine Kabel-Selbstverriegelung")
            settings["gunLineSelfLockEnable"] = bool(gun_line_self_lock_enabled)

        # Avoid an unnecessary remote write if the requested configuration
        # already matches the freshly fetched portal document.
        if payload == configuration:
            return
        await self._async_authenticated_patch(
            f"/internal/v1/ess/{self._system_serial}", payload, step="wallbox settings"
        )

    @_serialize_settings_write
    async def async_update_time_period(
        self,
        index: int,
        *,
        enabled: bool | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        charge_mode: int | None = None,
        charge_current: int | None = None,
    ) -> None:
        """Update a confirmed G1T/G2T time period without adding unknown fields."""
        if index not in {0, 1, 2}:
            raise ValueError("Ungültiger Zeitrahmen: erlaubt sind Zeitrahmen 1 bis 3")
        configuration = await self._async_get(
            f"/internal/v1/ess/{self._system_serial}", step="time period settings"
        )
        payload = copy.deepcopy(configuration)
        wallbox = self._find_wallbox_data(payload, self._wallbox_serial)
        generation, settings = self._settings_from_wallbox(wallbox)
        if generation not in {"g1T", "g2T"} or settings is None:
            raise ValueError("Zeitrahmen werden von dieser Wallbox nicht unterstützt")
        periods = settings.get("timePeriods")
        if (
            not isinstance(periods, list)
            or len(periods) <= index
            or (generation == "g2T" and len(periods) < 3)
            or not isinstance(periods[index], dict)
        ):
            raise PortalConnectionError(step="time period settings")
        period = periods[index]
        if generation == "g1T" and not schedule_supported(generation, settings):
            raise ValueError("G1T Zeitrahmen: Portal-Datenstruktur nicht vollständig bestätigt")
        if generation == "g1T":
            # UI similarity does not prove that the G1T accepts G2T PATCH
            # fields. Restrict test writes to fields already returned by the
            # G1T portal, and require an existing matching timing schema.
            if not all(
                isinstance(period.get(key), str) for key in ("startTime", "endTime")
            ):
                raise ValueError("G1T Zeitrahmen hat keine kompatible Zeitstruktur")
            for key, requested in (
                ("isEnable", enabled),
                ("startTime", start_time),
                ("endTime", end_time),
                ("chargeMode", charge_mode),
                ("chargeCurrent", charge_current),
            ):
                if requested is not None and key not in period:
                    raise ValueError(f"G1T Zeitrahmen unterstützt {key} nicht")

        if enabled is not None:
            period["isEnable"] = bool(enabled)
        if start_time is not None:
            self._validate_hhmm(start_time)
            period["startTime"] = start_time
        if end_time is not None:
            self._validate_hhmm(end_time)
            period["endTime"] = end_time
        if charge_mode is not None:
            if charge_mode not in {1, 2, 3, 4}:
                raise ValueError("Nicht unterstützter Lademodus im Zeitrahmen")
            period["chargeMode"] = charge_mode
        if charge_current is not None:
            if not 6 <= charge_current <= 16:
                raise ValueError("Der Ladestrom muss zwischen 6 und 16 A liegen")
            period["chargeCurrent"] = charge_current

        if payload == configuration:
            return
        await self._async_authenticated_patch(
            f"/internal/v1/ess/{self._system_serial}", payload, step="time period settings"
        )

    @staticmethod
    def _validate_hhmm(value: str) -> None:
        # Verified on G2T SMILE-G3-EVCT11/S (2026-10-10):
        # minute-precise PATCH 08:07–09:23 returned HTTP 204 and was
        # read back in both AlphaESS app and Home Assistant.
        # Reject malformed/out-of-range times and never round.
        if not isinstance(value, str) or not re.fullmatch(
            r"(?:[01]\d|2[0-3]):[0-5]\d", value
        ):
            raise ValueError(
                "Ungültige Uhrzeit: Bitte HH:MM zwischen 00:00 und 23:59 "
                "ohne Sekunden eingeben."
            )

    @staticmethod
    def _settings_from_wallbox(wallbox: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
        if isinstance(wallbox.get("g2T"), dict):
            return "g2T", wallbox["g2T"]
        if isinstance(wallbox.get("g1T"), dict):
            return "g1T", wallbox["g1T"]
        return None, None

    @staticmethod
    def wallbox_generation(data: dict[str, Any] | None) -> str | None:
        """Return the detected wallbox generation from coordinator data."""
        if not isinstance(data, dict):
            return None
        wallbox_serial = data.get("wallbox_serial")
        if not isinstance(wallbox_serial, str):
            return None
        for source_key in ("configuration", "system"):
            source = data.get(source_key)
            if not isinstance(source, (dict, list)):
                continue
            wallbox = AlphaESSPortalApi._find_wallbox_data(source, wallbox_serial)
            generation, _settings = AlphaESSPortalApi._settings_from_wallbox(wallbox)
            if generation:
                return generation
        return None

    @staticmethod
    def _find_wallbox_serial(value: Any) -> str | None:
        """Find an AlphaESS wallbox serial number in a portal response."""
        if isinstance(value, str) and re.fullmatch(r"ALP\d{6,}", value):
            return value
        if isinstance(value, dict):
            for item in value.values():
                serial = AlphaESSPortalApi._find_wallbox_serial(item)
                if serial:
                    return serial
        if isinstance(value, list):
            for item in value:
                serial = AlphaESSPortalApi._find_wallbox_serial(item)
                if serial:
                    return serial
        return None

    @staticmethod
    def _find_wallbox_data(value: Any, serial: str | None) -> dict[str, Any]:
        """Return the closest system object containing the wallbox serial."""
        if not serial:
            return {}
        if isinstance(value, dict):
            if any(item == serial for item in value.values()):
                return value
            for item in value.values():
                found = AlphaESSPortalApi._find_wallbox_data(item, serial)
                if found:
                    return found
        if isinstance(value, list):
            for item in value:
                found = AlphaESSPortalApi._find_wallbox_data(item, serial)
                if found:
                    return found
        return {}

    async def _async_token(self) -> str:
        # Full polling, fast polling and commands share one login. After a
        # rejection, queued calls must not submit the same credentials again.
        async with self._token_lock:
            if self._authentication_error is not None:
                raise self._authentication_error
            try:
                return await self._async_create_token()
            except AuthenticationError as err:
                self._authentication_error = err
                self._token = None
                self._refresh_token = None
                raise

    def _reject_authentication(self, step: str, status: int) -> AuthenticationError:
        """Pause this API instance until credentials are explicitly replaced."""
        self._authentication_error = AuthenticationError(step, status=status)
        self._token = None
        self._refresh_token = None
        return self._authentication_error

    async def _async_create_token(self) -> str:
        if self._token and time.monotonic() < self._expires_at:
            return self._token

        if self._refresh_token:
            payload = await self._async_post(
                f"{self._api_url}/users-center/sessions/refresh",
                {"refreshToken": self._refresh_token},
            )
        else:
            await self._async_select_region()
            payload = await self._async_post(
                f"{self._api_url}/users-center/sessions",
                {
                    "email": self._username.strip(),
                    "password": self._encrypt_password(),
                    "type": "password",
                },
            )

        session = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        token = session.get("token") or session.get("accessToken")
        refresh_token = session.get("refreshToken")
        if not token:
            raise AuthenticationError
        token_type = session.get("tokenType", "Bearer")
        self._token = token if token.startswith(f"{token_type} ") else f"{token_type} {token}"
        self._refresh_token = refresh_token if isinstance(refresh_token, str) else None
        self._expires_at = time.monotonic() + max(60, int(session.get("expiresIn", 300)) - 30)
        return self._token

    async def _async_select_region(self) -> None:
        """Resolve the regional API endpoint the customer portal uses."""
        try:
            async with self._session.get(
                f"{API_URL}/users-center/users/region",
                params={"usernameOrEmail": self._username.strip()},
                headers=PORTAL_HEADERS,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                if response.status in (400, 401, 403, 409, 429):
                    raise self._reject_authentication("region lookup", response.status)
                if response.status != 200:
                    raise PortalConnectionError(response.status, "region lookup")
                region = await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise PortalConnectionError from err

        endpoint = region.get("endPoint") if isinstance(region, dict) else None
        if isinstance(endpoint, str) and endpoint.startswith("https://"):
            self._api_url = endpoint.rstrip("/")

    def _encrypt_password(self) -> str:
        """Apply the AES-CBC password transformation used by the portal UI."""
        account = self._username.strip().encode()
        key = hashlib.sha256(account).digest()
        iv = hashlib.md5(account, usedforsecurity=False).digest()
        padder = PKCS7(algorithms.AES.block_size).padder()
        padded = padder.update(self._password.strip().encode()) + padder.finalize()
        encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        ciphertext = encryptor.update(padded) + encryptor.finalize()
        return base64.b64encode(ciphertext).decode()

    async def _async_post(self, url: str, data: dict[str, Any]) -> dict[str, Any]:
        try:
            async with self._session.post(
                url,
                json=data,
                headers=PORTAL_HEADERS,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                # A login conflict or rate limit must not cause more password
                # attempts. 409 elsewhere (e.g. G1T live status) is unrelated.
                if response.status in (400, 401, 403, 409, 429):
                    raise self._reject_authentication("login", response.status)
                if response.status not in (200, 201):
                    raise PortalConnectionError(response.status, "login")
                return await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise PortalConnectionError from err

    @staticmethod
    async def _history_response_body(response) -> dict[str, Any]:
        """Read optional JSON for diagnostics without changing HTTP handling."""
        if response.status in (401, 403, 204):
            return {}
        try:
            return {"response": await response.json(content_type=None)}
        except (ValueError, aiohttp.ClientError, asyncio.TimeoutError):
            return {"response_body": "not available as JSON"}

    async def _async_authenticated_post(self, path: str, data: dict[str, Any], *, step: str) -> None:
        history = getattr(self, "history", None)
        started = time.monotonic()
        event = {"method": "POST", "endpoint": path, "step": step, "request": data}
        try:
            await self._async_token()
        except (AuthenticationError, PortalConnectionError) as err:
            if history:
                history.record("control", **event, error=type(err).__name__,
                               stage=err.step, http_status=err.status)
            raise
        try:
            async with self._session.post(
                f"{self._api_url}{path}",
                json=data,
                headers={**PORTAL_HEADERS, "Authorization": self._token},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                if history and history.enabled:
                    history.record("control", **event, http_status=response.status,
                                   duration_ms=round((time.monotonic() - started) * 1000),
                                   **await self._history_response_body(response))
                if response.status in (401, 403):
                    raise self._reject_authentication(step, response.status)
                if response.status not in (200, 201, 204):
                    raise PortalConnectionError(response.status, step)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            if history:
                history.record("control", **event, error=type(err).__name__,
                               duration_ms=round((time.monotonic() - started) * 1000))
            raise PortalConnectionError from err

    async def _async_authenticated_patch(self, path: str, data: dict[str, Any], *, step: str) -> None:
        history = getattr(self, "history", None)
        started = time.monotonic()
        event = {"method": "PATCH", "endpoint": path, "step": step, "request": data}
        try:
            await self._async_token()
        except (AuthenticationError, PortalConnectionError) as err:
            if history:
                history.record("control", **event, error=type(err).__name__,
                               stage=err.step, http_status=err.status)
            raise
        feedback = getattr(self, 'settings_feedback', None)
        ticket = None
        if feedback is not None:
            targets = settings_targets(getattr(self, '_settings_request_context', None),
                                       self._find_wallbox_data(data, self._wallbox_serial))
            ticket = feedback.begin(targets)
        try:
            async with self._session.patch(
                f"{self._api_url}{path}",
                json=data,
                headers={**PORTAL_HEADERS, "Authorization": self._token},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                if history and history.enabled:
                    history.record("control", **event, http_status=response.status,
                                   duration_ms=round((time.monotonic() - started) * 1000),
                                   **await self._history_response_body(response))
                if response.status in (401, 403):
                    if feedback is not None:
                        feedback.failed(ticket, rejected=True)
                    raise self._reject_authentication(step, response.status)
                if response.status not in (200, 201, 204):
                    if feedback is not None:
                        feedback.failed(ticket, rejected=400 <= response.status < 500)
                    raise PortalConnectionError(response.status, step)
                if feedback is not None:
                    feedback.accepted(ticket)
                if self._settings_written_callback is not None:
                    # The portal accepted the write, but the physical wallbox
                    # may take another 20–30 seconds to apply the setting.
                    # Schedule a read-back without delaying this API call.
                    try:
                        self._settings_written_callback()
                    except Exception:
                        # The PATCH succeeded; a notification failure must not
                        # falsely report a failed write to Home Assistant.
                        _LOGGER.exception("Unable to schedule AlphaESS settings read-back")
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            if history:
                history.record("control", **event, error=type(err).__name__,
                               duration_ms=round((time.monotonic() - started) * 1000))
            if feedback is not None:
                feedback.failed(ticket)
            raise PortalConnectionError from err
        except BaseException:
            if feedback is not None:
                feedback.failed(ticket)
            raise

    async def _async_get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        step: str,
        supplemental: bool = False,
    ) -> Any:
        history = getattr(self, "history", None)
        started = time.monotonic()
        event = {"method": "GET", "step": step, "request": params}
        if not supplemental:
            event["endpoint"] = path
        try:
            await self._async_token()
        except (AuthenticationError, PortalConnectionError) as err:
            if history:
                history.record("api", **event, error=type(err).__name__,
                               stage=err.step, http_status=err.status)
            raise
        try:
            async with self._session.get(
                f"{self._api_url}{path}",
                params=params,
                headers={**PORTAL_HEADERS, "Authorization": self._token},
                timeout=aiohttp.ClientTimeout(total=5 if supplemental else 20),
            ) as response:
                if history and history.enabled and response.status != 200:
                    history.record("api", **event, http_status=response.status,
                                   duration_ms=round((time.monotonic() - started) * 1000),
                                   **({} if supplemental else await self._history_response_body(response)))
                if response.status in (401, 403) and not supplemental:
                    raise self._reject_authentication(step, response.status)
                if response.status != 200:
                    raise PortalConnectionError(response.status, step)
                try:
                    payload = await response.json()
                except (ValueError, aiohttp.ContentTypeError) as err:
                    if history:
                        history.record("api", **event, http_status=response.status, error="invalid JSON")
                    if supplemental:
                        raise PortalConnectionError(response.status, step) from err
                    raise
                if history:
                    history.record("api", **event, http_status=response.status,
                                   duration_ms=round((time.monotonic() - started) * 1000),
                                   **({} if supplemental else {"response": payload}))
                return payload
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            if history:
                history.record("api", **event, error=type(err).__name__,
                               duration_ms=round((time.monotonic() - started) * 1000))
            raise PortalConnectionError from err
