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
        self.api.set_settings_written_callback(self._schedule_followup_refresh)

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
        try:
            return await self.api.async_get_wallbox_data()
        except (AuthenticationError, PortalConnectionError) as err:
            _LOGGER.warning(
                "AlphaESS wallbox refresh failed during %s with status %s",
                err.step,
                getattr(err, "status", "authorization"),
            )
            raise UpdateFailed(f"AlphaESS wallbox refresh failed during {err.step}") from err
