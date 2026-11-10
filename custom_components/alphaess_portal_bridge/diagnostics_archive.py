"""Authenticated diagnostic ZIP downloads."""
from __future__ import annotations

from datetime import datetime
import logging
import time
from zoneinfo import ZoneInfo

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.components.http.const import KEY_HASS_USER

from .const import DIAGNOSTICS_ARCHIVE_PATH, DIAGNOSTICS_DOWNLOAD_PATH, DOMAIN
from .diagnostics import async_get_config_entry_diagnostics

_LOGGER = logging.getLogger(__name__)


class DiagnosticsArchiveView(HomeAssistantView):
    """Download an archive from an explicitly released, loaded Bridge entry."""

    url = DIAGNOSTICS_ARCHIVE_PATH + "/{entry_id}"
    name = f"api:{DOMAIN}:diagnostics-archive"
    requires_auth = True
    requires_grant = True

    def __init__(self, hass):
        self.hass = hass
        self._active: set[str] = set()

    async def get(self, request, entry_id: str):
        if not request[KEY_HASS_USER].is_admin:
            raise web.HTTPForbidden()
        entry = self.hass.config_entries.async_get_entry(entry_id)
        coordinator = self.hass.data.get(DOMAIN, {}).get(entry_id)
        if entry is None or coordinator is None:
            raise web.HTTPNotFound()
        if entry_id in self._active:
            raise web.HTTPConflict(text="Ein Diagnose-Export läuft bereits.")
        grant = None
        if self.requires_grant:
            grant = coordinator._advanced_diagnostics_until
            if grant <= time.monotonic():
                raise web.HTTPForbidden(text="Erweiterte API-Diagnose erneut freigeben.")
            coordinator._advanced_diagnostics_until = 0.0

        self._active.add(entry_id)
        try:
            return await self._download(request, entry, coordinator)
        except web.HTTPServiceUnavailable:
            if grant is not None and coordinator._advanced_diagnostics_until == 0.0 and grant > time.monotonic():
                coordinator._advanced_diagnostics_until = grant
            raise
        finally:
            self._active.remove(entry_id)

    async def _download(self, request, entry, coordinator):
        stamp = datetime.now(ZoneInfo(self.hass.config.time_zone)).strftime("%Y-%m-%d_%H-%M-%S")
        try:
            summary = await async_get_config_entry_diagnostics(
                self.hass, entry, include_archive_link=False
            )
            summary["home_assistant_version"] = self.hass.config.as_dict().get("version")
            summary["time_zone"] = self.hass.config.time_zone
            data = coordinator.data or {}
            wallbox = coordinator.api._find_wallbox_data(
                data.get("configuration") or {}, data.get("wallbox_serial")
            )
            summary["wallbox"] = {
                key: wallbox.get(key) for key in ("model", "softwareVersion", "hardwareVersion")
            }
            archive = await coordinator.api.history.async_export(summary, {
                "system": data.get("system"),
                "configuration": data.get("configuration"),
                "live_status": data.get("wallbox_status"),
                "latest_charge_report": data.get("latest_report"),
            })
        except Exception:
            _LOGGER.warning("Could not prepare the AlphaESS diagnostics archive")
            raise web.HTTPServiceUnavailable() from None

        response = web.StreamResponse(headers={
            "Content-Type": "application/zip",
            "Content-Disposition": f'attachment; filename="alphaess-wallbox-diagnose_{stamp}.zip"',
            "Cache-Control": "no-store",
        })
        try:
            await response.prepare(request)
            while chunk := await self.hass.async_add_executor_job(archive.read, 128 * 1024):
                await response.write(chunk)
            await response.write_eof()
        finally:
            await self.hass.async_add_executor_job(archive.close)
        return response


class DiagnosticsDownloadView(DiagnosticsArchiveView):
    """Dashboard downloads are authorized by the current HA administrator."""

    url = DIAGNOSTICS_DOWNLOAD_PATH + "/{entry_id}"
    name = f"api:{DOMAIN}:diagnostics-download"
    requires_grant = False
