"""Config flow for AlphaESS Portal Bridge."""
# ---------------------------------------------------------------------------
# Community-Build fuer https://www.storion4you.de/
# G2T-Erweiterung fuer SMILE-G3-EVCT11/S: Kavino
# Basierend auf dem Ausgangsprojekt wfa001/SMILE-EVCT11.
# Details und Attribution: siehe NOTICE.md im Paket.
# ---------------------------------------------------------------------------
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .api import AlphaESSPortalApi, AuthenticationError, PortalConnectionError
from .const import (
    CONF_AUTHENTICATION_PAUSED,
    CONF_PASSWORD,
    CONF_SYSTEM_SERIAL,
    CONF_UPDATE_INTERVAL,
    CONF_USERNAME,
    CONF_WALLBOX_SERIAL,
    DEFAULT_G2T_UPDATE_INTERVAL_SECONDS,
    DEFAULT_UPDATE_INTERVAL_SECONDS,
    DOMAIN,
    UPDATE_INTERVAL_OPTIONS,
    UPDATE_INTERVAL_STEP_SECONDS,
)


class AlphaESSPortalBridgeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up the bridge through the current AlphaESS portal session API."""

    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> AlphaESSPortalBridgeOptionsFlow:
        """Return the editable integration options."""
        return AlphaESSPortalBridgeOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        description_placeholders: dict[str, str] | None = None
        if user_input is not None:
            user_input = dict(user_input)
            user_input[CONF_SYSTEM_SERIAL] = user_input[CONF_SYSTEM_SERIAL].strip().upper()
            if user_input.get(CONF_WALLBOX_SERIAL):
                user_input[CONF_WALLBOX_SERIAL] = user_input[CONF_WALLBOX_SERIAL].strip().upper()
            else:
                user_input.pop(CONF_WALLBOX_SERIAL, None)
            await self.async_set_unique_id(user_input[CONF_SYSTEM_SERIAL])
            self._abort_if_unique_id_configured()
            api = AlphaESSPortalApi(self.hass, user_input)
            try:
                await api.async_validate_login()
            except AuthenticationError as err:
                errors["base"] = (
                    "login_paused"
                    if err.status in (409, 429)
                    else "session_rejected"
                    if err.step == "session validation"
                    else "system_access_denied"
                    if err.step == "system check"
                    else "invalid_auth"
                )
            except PortalConnectionError as err:
                if err.status is None:
                    errors["base"] = "cannot_connect"
                else:
                    errors["base"] = "portal_status"
                    description_placeholders = {"step": err.step, "status": str(err.status)}
            else:
                return self.async_create_entry(
                    title=f"AlphaESS Wallbox {user_input[CONF_SYSTEM_SERIAL]}",
                    data=user_input,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_SYSTEM_SERIAL): str,
                vol.Optional(CONF_WALLBOX_SERIAL): str,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders=description_placeholders,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add or replace the wallbox serial on an existing connection."""
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            wallbox_serial = user_input[CONF_WALLBOX_SERIAL].strip().upper()
            self.hass.config_entries.async_update_entry(
                entry,
                data={**entry.data, CONF_WALLBOX_SERIAL: wallbox_serial},
                title=f"AlphaESS Wallbox {entry.data[CONF_SYSTEM_SERIAL]}",
            )
            await self.hass.config_entries.async_reload(entry.entry_id)
            return self.async_abort(reason="reconfigure_successful")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({vol.Required(CONF_WALLBOX_SERIAL): str}),
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Ask for credentials; opening the form never performs a login."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Validate once per submission, preserving the existing entry/entities."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        description_placeholders: dict[str, str] | None = None
        if user_input is not None:
            updates = {
                CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                CONF_PASSWORD: user_input[CONF_PASSWORD],
                CONF_AUTHENTICATION_PAUSED: False,
            }
            api = AlphaESSPortalApi(self.hass, {**entry.data, **updates})
            try:
                await api.async_validate_login()
            except AuthenticationError as err:
                errors["base"] = (
                    "login_paused" if err.status in (409, 429) else "invalid_auth"
                )
            except PortalConnectionError as err:
                if err.status is None:
                    errors["base"] = "cannot_connect"
                else:
                    errors["base"] = "portal_status"
                    description_placeholders = {"step": err.step, "status": str(err.status)}
            else:
                return self.async_update_reload_and_abort(entry, data_updates=updates)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=entry.data[CONF_USERNAME]): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
            description_placeholders=description_placeholders,
        )


def _default_update_interval(hass: Any, entry: config_entries.ConfigEntry) -> int:
    """Choose the model-specific default when no interval has been saved."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    generation = AlphaESSPortalApi.wallbox_generation(
        getattr(coordinator, "data", None)
    )
    return DEFAULT_UPDATE_INTERVAL_SECONDS


class AlphaESSPortalBridgeOptionsFlow(config_entries.OptionsFlowWithReload):
    """Configure the portal refresh interval without changing credentials."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self.config_entry.options.get(CONF_UPDATE_INTERVAL)
        if current_interval not in UPDATE_INTERVAL_OPTIONS:
            current_interval = _default_update_interval(self.hass, self.config_entry)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=current_interval,
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=min(UPDATE_INTERVAL_OPTIONS),
                            max=max(UPDATE_INTERVAL_OPTIONS),
                            step=UPDATE_INTERVAL_STEP_SECONDS,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )
