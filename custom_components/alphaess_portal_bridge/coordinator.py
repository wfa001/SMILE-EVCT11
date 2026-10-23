"""Data coordinator for AlphaESS Wallbox Bridge."""
# ---------------------------------------------------------------------------
# Community-Build fuer https://www.storion4you.de/
# G2T-Erweiterung fuer SMILE-G3-EVCT11/S: Kavino
# Basierend auf dem Ausgangsprojekt wfa001/SMILE-EVCT11.
# Details und Attribution: siehe NOTICE.md im Paket.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AlphaESSPortalApi, AuthenticationError, PortalConnectionError
from .const import (
    CONF_AUTHENTICATION_PAUSED,
    DEFAULT_UPDATE_INTERVAL_SECONDS,
    DOMAIN,
    UPDATE_INTERVAL_OPTIONS,
)

_LOGGER = logging.getLogger(__name__)
_POST_WRITE_READBACK_SECONDS = 3
_G2T_LIVE_INTERVAL_SECONDS = 5
_G2T_LIVE_MAX_BACKOFF_SECONDS = 120


class AlphaESSWallboxCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch the current wallbox state from the AlphaESS customer portal."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: AlphaESSPortalApi,
        update_interval_seconds: int = DEFAULT_UPDATE_INTERVAL_SECONDS,
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=(
                    update_interval_seconds
                    if update_interval_seconds in UPDATE_INTERVAL_OPTIONS
                    else DEFAULT_UPDATE_INTERVAL_SECONDS
                )
            ),
        )
        self.api = api
        self._cancel_followup_refresh: Callable[[], None] | None = None
        self._stopped = False
        self._live_refresh_cancel: Callable[[], None] | None = None
        self._live_refresh_errors = 0
        self._live_status_supported: bool | None = None
        self._live_last_duration_ms: int | None = None
        self._full_last_duration_ms: int | None = None
        self._live_success_count = 0
        self._live_failure_count = 0
        self._full_success_count = 0
        self._full_failure_count = 0
        self._live_last_http_status: int | None = None
        self._last_live_success: datetime | None = None
        self._last_full_success: datetime | None = None
        self._last_api_error: str | None = None
        self._advanced_diagnostics_until: float = 0.0
        self._full_consecutive_errors = 0
        self._live_revision = 0
        self._latest_live_status: dict[str, Any] | None = None
        self.api.set_settings_written_callback(self._schedule_followup_refresh)

    @property
    def api_connection_status(self) -> str:
        """Connection to the AlphaESS portal, not the physical wallbox."""
        now = datetime.now(timezone.utc)
        full_age = ((now - self._last_full_success).total_seconds()
                    if self._last_full_success else float("inf"))
        live_age = ((now - self._last_live_success).total_seconds()
                    if self._last_live_success else float("inf"))
        full_limit = max(90, 3 * self.update_interval.total_seconds())
        live_expected = self._live_status_supported is True
        full_ok = full_age <= full_limit
        live_ok = live_expected and live_age <= 25
        if not full_ok and not live_ok:
            return "Getrennt"
        if (not full_ok or self._full_consecutive_errors
                or self._live_refresh_errors
                or (live_expected and not live_ok)):
            return "Gestört"
        return "Verbunden"

    def start_live_polling(self) -> None:
        """Start a separate read-only five-second cycle for both generations."""
        if self._stopped or self._live_refresh_cancel is not None:
            return
        if AlphaESSPortalApi.wallbox_generation(self.data) not in ("g1T", "g2T"):
            return
        if self._live_status_supported is False:
            return
        if (self.data or {}).get("wallbox_serial") in self.api._live_status_unavailable_serials:
            self._live_status_supported = False
            return
        if not (self.data or {}).get("wallbox_serial"):
            return
        self._schedule_live_refresh(_G2T_LIVE_INTERVAL_SECONDS)

    def _schedule_live_refresh(self, interval: int) -> None:
        if not self._stopped:
            self._live_refresh_cancel = async_call_later(
                self.hass, interval, self._async_live_refresh
            )

    async def _async_live_refresh(self, _now: Any) -> None:
        """Notify existing live sensor entities without resetting 30s polling.

        async_set_updated_data() would reschedule the regular coordinator poll;
        notify listeners explicitly so configuration and reports remain on
        their own slower cycle.
        """
        self._live_refresh_cancel = None
        if self._stopped:
            return
        delay = _G2T_LIVE_INTERVAL_SECONDS
        started = time.monotonic()
        try:
            serial = (self.data or {}).get("wallbox_serial")
            if not serial:
                return
            status = await self.api.async_get_live_status(serial)
            generation = AlphaESSPortalApi.wallbox_generation(self.data)
            if generation == "g2T" and not isinstance(status, dict):
                # Invalid JSON shapes are a read failure, not proof of an
                # RS485 interruption and not an unsupported G2T endpoint.
                raise PortalConnectionError(step="wallbox status payload")
            # Some older G1T devices may expose no usable live endpoint.
            # G2T may legitimately return only counters/lock state (or {})
            # during a communication outage. Publish that reply and keep
            # polling so stale charging values clear and reconnection is seen.
            if generation != "g2T" and (not isinstance(status, dict) or not any(
                key in status for key in ("status", "chargingStatus", "state", "power", "chargingPower", "currentPower", "realPower")
            )):
                self._live_status_supported = False
                _LOGGER.warning("AlphaESS live-status payload unsupported; using regular refresh only")
                return
            self._live_status_supported = True
            self._live_success_count += 1
            self._last_live_success = datetime.now(timezone.utc)
            self._live_last_http_status = None
            if not self._stopped:
                self._latest_live_status = status
                self._live_revision += 1
                self.data = {
                    **(self.data or {}),
                    "wallbox_status": status,
                    "wallbox_status_source": "real_status",
                }
                self._live_refresh_errors = 0
                self.async_update_listeners()
        except AuthenticationError as err:
            self._live_failure_count += 1
            self.async_set_update_error(self._authentication_failed(err))
            if self.config_entry:
                self.config_entry.async_start_reauth(self.hass)
            return
        except PortalConnectionError as err:
            self._live_failure_count += 1
            status_code = getattr(err, "status", None)
            self._live_last_http_status = status_code if type(status_code) is int and 100 <= status_code <= 599 else None
            # HTTP 404/409 on G1T commonly means this endpoint is unavailable.
            # Do not hammer an unsupported API route every few seconds.
            if AlphaESSPortalApi.wallbox_generation(self.data) == "g1T" and getattr(err, "status", None) in (404, 409):
                self._live_status_supported = False
                if getattr(err, "status", None) == 404:
                    self.api._live_status_unavailable_serials.add(serial)
                _LOGGER.warning("G1T fast live-status unavailable; using regular refresh only")
                return
            self._live_refresh_errors += 1
            self._last_api_error = f"Live-Status: {err.step} (HTTP {getattr(err, 'status', None)})"
            if not self._stopped:
                self.async_update_listeners()
            if getattr(err, "status", None) in (401, 403, 429):
                delay = _G2T_LIVE_MAX_BACKOFF_SECONDS
            else:
                delay = min(
                    _G2T_LIVE_MAX_BACKOFF_SECONDS,
                    _G2T_LIVE_INTERVAL_SECONDS * (2 ** min(self._live_refresh_errors, 5)),
                )
            _LOGGER.warning(
                "AlphaESS fast live-status update failed during %s (status %s); retry in %ss",
                err.step, getattr(err, "status", "auth"), delay,
            )
        finally:
            self._live_last_duration_ms = min(round((time.monotonic() - started) * 1000), 600000)
            if not self._stopped and self._live_status_supported is not False:
                self._schedule_live_refresh(delay)

    def stop_live_polling(self) -> None:
        """Stop fast polling on integration unload."""
        if self._live_refresh_cancel is not None:
            self._live_refresh_cancel()
            self._live_refresh_cancel = None

    def _authentication_failed(self, err: AuthenticationError) -> ConfigEntryAuthFailed:
        """Stop both extra polling timers and request explicit reauthentication."""
        self.stop_followup_refresh()
        self.stop_live_polling()
        if self.config_entry and not self.config_entry.data.get(CONF_AUTHENTICATION_PAUSED):
            # Keep the pause over reloads/restarts. Otherwise the old password
            # would be submitted again as soon as a new API instance is made.
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, CONF_AUTHENTICATION_PAUSED: True},
            )
        self._last_api_error = f"Authentication: {err.step} (HTTP {err.status})"
        return ConfigEntryAuthFailed(
            "AlphaESS sign-in rejected; automatic attempts stopped. "
            "Wait for any portal lockout to expire, then update your credentials."
        )

    def _schedule_followup_refresh(self) -> None:
        """Read back accepted settings after portal propagation, without waiting.

        Multiple rapid PATCH responses reset a single timer, so an update burst
        triggers only one additional refresh. This is a portal read-back, not
        confirmation of a physical current or phase change.
        """
        if self._stopped:
            return
        if self._cancel_followup_refresh is not None:
            self._cancel_followup_refresh()
        self._cancel_followup_refresh = async_call_later(
            self.hass, _POST_WRITE_READBACK_SECONDS, self._async_followup_refresh
        )

    async def _async_followup_refresh(self, _now: Any) -> None:
        self._cancel_followup_refresh = None
        if not self._stopped:
            await self.async_request_refresh()

    def stop_followup_refresh(self) -> None:
        """Prevent scheduled API traffic after the config entry is unloaded."""
        self._stopped = True
        self.api.set_settings_written_callback(None)
        if self._cancel_followup_refresh is not None:
            self._cancel_followup_refresh()
            self._cancel_followup_refresh = None

    async def _async_update_data(self) -> dict[str, Any]:
        revision = self._live_revision
        started = time.monotonic()
        try:
            refreshed = await self.api.async_get_wallbox_data()
            # A completed fast poll during the slower configuration fetch wins.
            if self._live_revision != revision and self._latest_live_status is not None:
                refreshed = {
                    **refreshed,
                    "wallbox_status": self._latest_live_status,
                    "wallbox_status_source": "real_status",
                }
            self._full_success_count += 1
            self._last_full_success = datetime.now(timezone.utc)
            self._full_consecutive_errors = 0
            return refreshed
        except AuthenticationError as err:
            self._full_failure_count += 1
            self._full_consecutive_errors += 1
            raise self._authentication_failed(err) from err
        except PortalConnectionError as err:
            self._full_failure_count += 1
            self._full_consecutive_errors += 1
            self._last_api_error = f"Konfiguration: {err.step} (HTTP {getattr(err, 'status', None)})"
            _LOGGER.warning(
                "AlphaESS wallbox refresh failed during %s with status %s",
                err.step,
                getattr(err, "status", "authorization"),
            )
            raise UpdateFailed(f"AlphaESS wallbox refresh failed during {err.step}") from err
        finally:
            self._full_last_duration_ms = min(round((time.monotonic() - started) * 1000), 600000)
