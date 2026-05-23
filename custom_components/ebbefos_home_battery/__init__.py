from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client

from .const import (
    CONF_BEARER_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_TOKEN_EXPIRES_AT,
    DOMAIN,
)
from .ebbefos_api import AuthState, EbbefosApi

PLATFORMS = ["sensor"]


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Ebbefos Home Battery platform component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Ebbefos Home Battery platform from a config entry."""

    async def async_update_tokens(access_token, refresh_token, token_expires_at):
        data = dict(entry.data)
        data[CONF_BEARER_TOKEN] = access_token

        if refresh_token:
            data[CONF_REFRESH_TOKEN] = refresh_token
        else:
            data.pop(CONF_REFRESH_TOKEN, None)

        if token_expires_at is not None:
            data[CONF_TOKEN_EXPIRES_AT] = token_expires_at
        else:
            data.pop(CONF_TOKEN_EXPIRES_AT, None)

        hass.config_entries.async_update_entry(entry, data=data)

    api = EbbefosApi(
        hass,
        aiohttp_client.async_create_clientsession(hass),
        AuthState(
            access_token=entry.data[CONF_BEARER_TOKEN],
            refresh_token=entry.data.get(CONF_REFRESH_TOKEN),
            token_expires_at=entry.data.get(CONF_TOKEN_EXPIRES_AT),
        ),
        async_update_tokens,
    )

    hass.data[DOMAIN][entry.entry_id] = api

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
