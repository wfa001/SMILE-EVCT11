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
from functools import wraps
import hashlib
import logging
import re
import time
from typing import Any

import aiohttp
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import (
    API_URL,
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

    def __init__(self, step: str = "login") -> None:
        self.step = step
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
            return await method(self, *args, **kwargs)

    return wrapped


class AlphaESSPortalApi:
    """Keep an AlphaESS customer-portal session in memory."""

    def __init__(self, hass: HomeAssistant, config: dict[str, Any]) -> None:
        self._session = async_get_clientsession(hass)
        self._settings_write_lock = asyncio.Lock()
        self._charge_current_request_id = 0
        self._settings_written_callback: Callable[[], None] | None = None
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
        except PortalConnectionError:
            configuration = {}

        wallbox_serial = (
            self._wallbox_serial
            or self._find_wallbox_serial(configuration)
            or self._find_wallbox_serial(system)
        )
        wallbox_status = self._find_wallbox_data(system, wallbox_serial)
        wallbox_status_source = "system"

        if wallbox_serial:
            try:
                wallbox_status = await self._async_get(
                    f"/internal/v1/ev-charger/{wallbox_serial}/real-status",
                    step="wallbox status",
                )
                wallbox_status_source = "real_status"
            except PortalConnectionError as err:
                # 409 is returned by some portal states when live status is not
                # available. Keep configuration/system data in that case.
                if err.status != 409:
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

        return {
            "system": system,
            "configuration": configuration,
            "wallbox_serial": wallbox_serial,
            "wallbox_status": wallbox_status,
            "wallbox_status_source": wallbox_status_source,
            "latest_report": latest_report,
            "today_report_energy": today_report_energy,
        }

    async def async_get_charge_report_items(self, wallbox_serial: str) -> list[dict[str, Any]]:
        """Return recent charging sessions, cached to reduce portal traffic."""
        today = dt_util.now().date().isoformat()
        if (
            self._report_cache_date == today
            and time.monotonic() < self._report_cache_until
        ):
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
            else {"Charging"}
        )
        if status not in allowed:
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
            allowed_modes = {1, 2, 3, 4} if generation == "g2T" else {0, 1, 2, 3, 4}
            if charge_mode not in allowed_modes:
                raise ValueError("Nicht unterstützter Lademodus")
            if generation == "g2T" and settings.get("smartMode") is True and charge_mode == 4:
                raise ValueError("Smart Mode benötigt Langsamladung, Schonladung oder Schnellladung")
            settings["chargeMode"] = charge_mode

        if charge_current is not None:
            if not 6 <= charge_current <= 16:
                raise ValueError("Der Ladestrom muss zwischen 6 und 16 A liegen")
            settings["chargeCurrent"] = charge_current

        if charge_strategy is not None:
            if generation != "g2T" or charge_strategy not in {0, 1, 2}:
                raise ValueError("Nicht unterstützte Ladeeinstellung")
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
        """Update one of the three G2T time periods."""
        if index not in {0, 1, 2}:
            raise ValueError("Ungültiger Zeitrahmen: erlaubt sind Zeitrahmen 1 bis 3")
        configuration = await self._async_get(
            f"/internal/v1/ess/{self._system_serial}", step="time period settings"
        )
        payload = copy.deepcopy(configuration)
        wallbox = self._find_wallbox_data(payload, self._wallbox_serial)
        generation, settings = self._settings_from_wallbox(wallbox)
        if generation != "g2T" or settings is None:
            raise ValueError("Zeitrahmen sind nur bei G2T-Wallboxen verfügbar")
        periods = settings.get("timePeriods")
        if not isinstance(periods, list) or len(periods) < 3 or not isinstance(periods[index], dict):
            raise PortalConnectionError(step="time period settings")
        period = periods[index]

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
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):(?:00|15|30|45)", value):
            raise ValueError("Zeiten sind nur im 15-Minuten-Raster erlaubt (HH:00, HH:15, HH:30 oder HH:45)")

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
                if response.status in (400, 401, 403):
                    raise AuthenticationError
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
                if response.status in (400, 401, 403):
                    raise AuthenticationError
                if response.status not in (200, 201):
                    raise PortalConnectionError(response.status, "login")
                return await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise PortalConnectionError from err

    async def _async_authenticated_post(self, path: str, data: dict[str, Any], *, step: str) -> None:
        await self._async_token()
        try:
            async with self._session.post(
                f"{self._api_url}{path}",
                json=data,
                headers={**PORTAL_HEADERS, "Authorization": self._token},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                if response.status in (401, 403):
                    raise AuthenticationError(step)
                if response.status not in (200, 201, 204):
                    raise PortalConnectionError(response.status, step)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise PortalConnectionError from err

    async def _async_authenticated_patch(self, path: str, data: dict[str, Any], *, step: str) -> None:
        await self._async_token()
        try:
            async with self._session.patch(
                f"{self._api_url}{path}",
                json=data,
                headers={**PORTAL_HEADERS, "Authorization": self._token},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                if response.status in (401, 403):
                    raise AuthenticationError(step)
                if response.status not in (200, 201, 204):
                    raise PortalConnectionError(response.status, step)
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
            raise PortalConnectionError from err

    async def _async_get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        step: str,
    ) -> dict[str, Any]:
        await self._async_token()
        try:
            async with self._session.get(
                f"{self._api_url}{path}",
                params=params,
                headers={**PORTAL_HEADERS, "Authorization": self._token},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                if response.status in (401, 403):
                    raise AuthenticationError(step)
                if response.status != 200:
                    raise PortalConnectionError(response.status, step)
                return await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise PortalConnectionError from err
