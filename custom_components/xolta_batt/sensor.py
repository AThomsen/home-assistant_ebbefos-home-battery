from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.exceptions import ConfigEntryAuthFailed
import logging

from datetime import timedelta

from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.const import (
    PERCENTAGE
)
from .const import DOMAIN, UPDATE_INTERVAL_SEC

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Add sensors for passed config_entry in HA."""
    xoltaApi = hass.data[DOMAIN][config_entry.entry_id]

    # _LOGGER.debug("config_entry %s", config_entry.data)
    update_interval = timedelta(seconds=UPDATE_INTERVAL_SEC)

    async def async_update_data():
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        try:
            # Note: asyncio.TimeoutError and aiohttp.ClientError are already
            # handled by the data update coordinator.
            # async with async_timeout.timeout(10):
            result = await xoltaApi.get_data()
            return result

        except ConfigEntryAuthFailed as err:
            raise

        except Exception as err:
            # logging.exception("Something awful happened!")
            raise UpdateFailed(f"Error communicating with API: {err}")

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        # Name of the data. For logging purposes.
        name="XOLTA API",
        update_method=async_update_data,
        # Polling interval. Will only be polled if there are subscribers.
        update_interval=update_interval,
    )

    #
    # Fetch initial data so we have data when entities subscribe
    #
    # If the refresh fails, async_config_entry_first_refresh will
    # raise ConfigEntryNotReady and setup will try again later
    #
    # If you do not want to retry setup on failure, use
    # coordinator.async_refresh() instead
    #
    await coordinator.async_config_entry_first_refresh()

    for site in coordinator.data["sites"]:
        siteId = site["siteId"]
        async_add_entities(
            [
                XoltaSensor(
                    coordinator,
                    siteId,
                    "Battery power flow",
                    SensorDeviceClass.POWER,
                    UnitOfPower.KILO_WATT,
                    "mdi:battery-charging-100",
                    # negative means charging, positive means discharging
                    "inverterActivePowerAggAvg",
                    SensorStateClass.MEASUREMENT,
                ),
                XoltaSensor(
                    coordinator,
                    siteId,
                    "PV power",
                    SensorDeviceClass.POWER,
                    UnitOfPower.KILO_WATT,
                    "mdi:solar-power",
                    "meterPvActivePowerAggAvg",
                    SensorStateClass.MEASUREMENT,
                ),
                XoltaSensor(
                    coordinator,
                    siteId,
                    "Power consumption",
                    SensorDeviceClass.POWER,
                    UnitOfPower.KILO_WATT,
                    "mdi:home-lightning-bolt",
                    "consumption",
                    SensorStateClass.MEASUREMENT,
                ),
                XoltaSensor(
                    coordinator,
                    siteId,
                    "Battery charge level",
                    SensorDeviceClass.BATTERY,
                    PERCENTAGE,
                    None,
                    "bmsSocRawArrayCloudTrimmedAggAvg",
                ),
                XoltaSensor(
                    coordinator,
                    siteId,
                    "Grid power flow",
                    SensorDeviceClass.POWER,
                    UnitOfPower.KILO_WATT,
                    "mdi:transmission-tower",
                    # negative means sell, positive means buy
                    "meterGridActivePowerAggAvg",
                    SensorStateClass.MEASUREMENT,
                ),
                # Energy sensors:
                XoltaEnergySensor(
                    coordinator,
                    siteId,
                    "Grid energy imported",
                    "mdi:transmission-tower-export", # yes, this is correct
                    "grid_imported",
                ),
                XoltaEnergySensor(
                    coordinator,
                    siteId,
                    "Grid energy exported",
                    "mdi:transmission-tower-import", # yes, this is correct
                    "grid_exported",
                ),
                XoltaEnergySensor(
                    coordinator,
                    siteId,
                    "Battery energy charged",
                    "mdi:battery-arrow-up",
                    "battery_charged",
                ),
                XoltaEnergySensor(
                    coordinator,
                    siteId,
                    "Battery energy discharged",
                    "mdi:battery-arrow-down",
                    "battery_discharged",
                ),
                XoltaEnergySensor(
                    coordinator,
                    siteId,
                    "PV energy",
                    "mdi:solar-power",
                    "pv",
                ),
                XoltaEnergySensor(
                    coordinator,
                    siteId,
                    "Energy consumption",
                    "mdi:home-lightning-bolt",
                    "consumption",
                ),
            ]
        )


class XoltaBaseSensor(CoordinatorEntity, SensorEntity):
    def __init__(
        self, coordinator, site_id, sensor_type, icon
    ):
        super().__init__(coordinator)
        self._site_id = site_id
        self._sensor_type = sensor_type
        self._attr_name = sensor_type
        self._attr_icon = icon

    @property
    def device_info(self):
        return {
            "identifiers": {
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, self._site_id)
            },
            "name": f"Battery {self._site_id}",
            "manufacturer": "Xolta",
            "model": "Battery",
            # "sw_version": self.extra_state_attributes.get("firmwareversion", "unknown"),
            # "via_device": (DOMAIN, self.api.bridgeid),
        }


class XoltaSensor(XoltaBaseSensor):
    def __init__(
        self,
        coordinator,
        site_id,
        sensor_type,
        device_class,
        units,
        icon,
        data_property,
        state_class=None,
    ):
        super().__init__(coordinator, site_id, sensor_type, icon)
        self._attr_unique_id = f"{self._site_id}-{self._sensor_type}"
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = units
        self._attr_state_class = state_class
        self._data_property = data_property
        _LOGGER.debug("Creating XoltaBatterySensor with id %s", self._site_id)

    @property
    def native_value(self):
        data = self.coordinator.data["sensors"][self._site_id]
        return data[self._data_property] if data["state"] == "Running" else 0

    # For backwards compatibility
    @property
    def extra_state_attributes(self):
        """Return the state attributes of the monitored installation."""
        data = self.coordinator.data["sensors"][self._site_id]
        attributes = {}
        attributes["statusText"] = data["state"]
        return attributes


class XoltaEnergySensor(XoltaBaseSensor):

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator, site_id, sensor_type, icon, data_property):
        super().__init__(coordinator, site_id, sensor_type, icon)
        self._attr_unique_id = f"{self._site_id}-energy-{self._sensor_type}"
        self._data_property = data_property

    @property
    def native_value(self) -> float:
        data = self.coordinator.data["energy"][self._site_id]
        return data[self._data_property]
