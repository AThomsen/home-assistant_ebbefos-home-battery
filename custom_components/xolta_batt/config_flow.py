"""Config flow for xolta integration."""
from __future__ import annotations

import logging
import voluptuous as vol
from homeassistant.config_entries import ConfigFlow
from homeassistant.helpers import aiohttp_client
from homeassistant.exceptions import ConfigEntryAuthFailed

from .const import DOMAIN, XOLTA_CONFIG_SCHEMA, CONF_BEARER_TOKEN
from .xolta_api import XoltaApi

_LOGGER = logging.getLogger(__name__)


class XoltaBatteryFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a Xolta Battery config flow."""

    VERSION = 1

    def __init__(self):
        """Initialize config flow."""
        self._bearer_token = None

    async def _show_setup_form(self, errors=None):
        """Show the setup form to the user."""
        return self.async_show_form(
            step_id="user",
            data_schema=XOLTA_CONFIG_SCHEMA,
            errors=errors or {},
        )

    async def _show_reauth_form(self, errors=None):
        """Show the reauth form to the user."""
        return self.async_show_form(
            step_id="reauth",
            data_schema=XOLTA_CONFIG_SCHEMA,
            errors=errors or {},
        )

    async def _check_setup(self):
        """Check the setup of the flow."""
        errors = {}

        api = XoltaApi(
            self.hass,
            aiohttp_client.async_create_clientsession(self.hass),
            self._bearer_token,
        )

        try:
            authenticated = await api.test_authentication()
            if authenticated:
                return None
            errors["base"] = "invalid_auth"
        except ConfigEntryAuthFailed as ex:
            errors[CONF_BEARER_TOKEN] = str(ex.args)
        except Exception as ex:
            errors[CONF_BEARER_TOKEN] = str(ex.args)
        return errors

    async def async_step_user(self, user_input=None):
        """Handle a flow initiated by the user."""
        if user_input is None:
            return await self._show_setup_form(user_input)

        self._bearer_token = user_input[CONF_BEARER_TOKEN]

        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        errors = await self._check_setup()
        if errors is not None:
            return await self._show_setup_form(errors)
        return self._async_create_entry()

    async def async_step_reauth(self, user_input):
        """Handle configuration by re-auth."""

        if user_input is not None:
            self._bearer_token = user_input[CONF_BEARER_TOKEN]

        await self.async_set_unique_id(DOMAIN)

        errors = await self._check_setup()
        if errors is not None:
            return await self._show_reauth_form(errors)

        entry = await self.async_set_unique_id(self.unique_id)
        self.hass.config_entries.async_update_entry(
            entry,
            data={CONF_BEARER_TOKEN: self._bearer_token},
        )
        return self.async_abort(reason="reauth_successful")

    def _async_create_entry(self):
        """Handle create entry."""
        return self.async_create_entry(
            title="Xolta Battery",
            data={CONF_BEARER_TOKEN: self._bearer_token},
        )
