"""Config flow for xolta integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigFlow
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import aiohttp_client

from .const import (
    CONF_BEARER_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_TOKEN_EXPIRES_AT,
    DOMAIN,
    XOLTA_CONFIG_SCHEMA,
)
from .xolta_api import AuthState, XoltaApi


class XoltaBatteryFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a Xolta Battery config flow (refresh token required)."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow state."""
        self._bearer_token = None
        self._refresh_token = None
        self._token_expires_at = None

    def _entry_data(self) -> dict:
        """Build config entry data from the current auth state."""
        data = {CONF_BEARER_TOKEN: self._bearer_token}
        if self._refresh_token:
            data[CONF_REFRESH_TOKEN] = self._refresh_token
        if self._token_expires_at is not None:
            data[CONF_TOKEN_EXPIRES_AT] = self._token_expires_at
        return data

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

    async def _check_setup(self, *, force_refresh: bool = False):
        """Check the setup of the flow."""
        errors = {}

        token_expires_at = self._token_expires_at
        if force_refresh and self._refresh_token and token_expires_at is None:
            # Force a refresh round-trip during initial setup so we persist expiry.
            token_expires_at = 0

        access_token = self._bearer_token or ""

        api = XoltaApi(
            self.hass,
            aiohttp_client.async_create_clientsession(self.hass),
            AuthState(
                access_token=access_token,
                refresh_token=self._refresh_token,
                token_expires_at=token_expires_at,
            ),
        )

        try:
            authenticated = await api.test_authentication()
            if authenticated:
                auth_state = api.auth_state
                self._bearer_token = auth_state.access_token
                self._refresh_token = auth_state.refresh_token
                self._token_expires_at = auth_state.token_expires_at
                return None
            errors["base"] = "invalid_auth"
        except ConfigEntryAuthFailed as ex:
            errors["base"] = str(ex.args)
        except Exception as ex:
            errors["base"] = str(ex.args)
        return errors

    async def async_step_user(self, user_input=None):
        """Handle a flow initiated by the user."""
        if user_input is None:
            return await self._show_setup_form()

        self._bearer_token = None
        self._refresh_token = None
        self._token_expires_at = None

        refresh_token = user_input.get(CONF_REFRESH_TOKEN)

        if refresh_token:
            self._refresh_token = refresh_token.strip()

        if not self._refresh_token:
            return await self._show_setup_form({"base": "invalid_auth"})

        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        errors = await self._check_setup(force_refresh=True)
        if errors is not None:
            return await self._show_setup_form(errors)
        return self._async_create_entry()

    async def async_step_reauth(self, user_input=None):
        """Handle configuration by re-auth."""
        if user_input is None:
            return await self._show_reauth_form()

        self._bearer_token = None
        self._refresh_token = None
        self._token_expires_at = None

        refresh_token = user_input.get(CONF_REFRESH_TOKEN)

        if refresh_token:
            self._refresh_token = refresh_token.strip()

        if not self._refresh_token:
            return await self._show_reauth_form({"base": "invalid_auth"})

        await self.async_set_unique_id(DOMAIN)

        errors = await self._check_setup()
        if errors is not None:
            return await self._show_reauth_form(errors)

        entry_id = self.context.get("entry_id")
        if entry_id is None:
            return self.async_abort(reason="unknown")

        entry = self.hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            return self.async_abort(reason="unknown")

        self.hass.config_entries.async_update_entry(entry, data=self._entry_data())
        return self.async_abort(reason="reauth_successful")

    def _async_create_entry(self):
        """Handle create entry."""
        return self.async_create_entry(title="Xolta Battery", data=self._entry_data())
