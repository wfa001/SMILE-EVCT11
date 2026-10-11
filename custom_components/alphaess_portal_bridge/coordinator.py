"""Data coordinator for AlphaESS Wallbox Bridge."""
# ---------------------------------------------------------------------------
# Community-Build fuer https://www.storion4you.de/
# G2T-Erweiterung fuer SMILE-G3-EVCT11/S: Kavino
# Basierend auf dem Ausgangsprojekt wfa001/SMILE-EVCT11.
# Details und Attribution: siehe NOTICE.md im Paket.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AlphaESSPortalApi, AuthenticationError, PortalConnectionError
from .const import DEFAULT_UPDATE_INTERVAL_SECONDS, DOMAIN, UPDATE_INTERVAL_OPTIONS

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
        self._live_revision = 0
        self._latest_live_status: dict[str, Any] | None = None
        self.api.set_settings_written_callback(self._schedule_followup_refresh)

    def start_live_polling(self) -> None:
        """Start a separate read-only five-second G2T update cycle."""
        if self._stopped or self._live_refresh_cancel is not None:
            return
        if AlphaESSPortalApi.wallbox_generation(self.data) != "g2T":
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
        try:
            serial = (self.data or {}).get("wallbox_serial")
            if not serial:
                return
            status = await self.api.async_get_live_status(serial)
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
        except (AuthenticationError, PortalConnectionError) as err:
            self._live_refresh_errors += 1
            if isinstance(err, AuthenticationError) or getattr(err, "status", None) in (401, 403, 429):
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
            if not self._stopped:
                self._schedule_live_refresh(delay)

    def stop_live_polling(self) -> None:
        """Stop fast polling on integration unload."""
        if self._live_refresh_cancel is not None:
            self._live_refresh_cancel()
            self._live_refresh_cancel = None

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
        try:
            refreshed = await self.api.async_get_wallbox_data()
            # A completed fast poll during the slower configuration fetch wins.
            if self._live_revision != revision and self._latest_live_status is not None:
                refreshed = {
                    **refreshed,
                    "wallbox_status": self._latest_live_status,
                    "wallbox_status_source": "real_status",
                }
            return refreshed
        except (AuthenticationError, PortalConnectionError) as err:
            _LOGGER.warning(
                "AlphaESS wallbox refresh failed during %s with status %s",
                err.step,
                getattr(err, "status", "authorization"),
            )
            raise UpdateFailed(f"AlphaESS wallbox refresh failed during {err.step}") from err
