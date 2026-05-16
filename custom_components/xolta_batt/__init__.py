from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client

from .const import DOMAIN, CONF_BEARER_TOKEN
from .xolta_api import XoltaApi

PLATFORMS = ["sensor"]


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Xolta Solar Battery component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up xolta_batt from a config entry."""
    api = XoltaApi(
        hass,
        aiohttp_client.async_create_clientsession(hass),
        entry.data[CONF_BEARER_TOKEN],
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
