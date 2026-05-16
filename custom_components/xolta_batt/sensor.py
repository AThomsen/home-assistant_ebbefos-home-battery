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
from homeassistant.const import UnitOfPower
from homeassistant.const import PERCENTAGE
from .const import DOMAIN, UPDATE_INTERVAL_SEC

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Add sensors for passed config_entry in HA."""
    xoltaApi = hass.data[DOMAIN][config_entry.entry_id]

    update_interval = timedelta(seconds=UPDATE_INTERVAL_SEC)

    async def async_update_data():
        try:
            return await xoltaApi.get_data()
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="XOLTA API",
        update_method=async_update_data,
        update_interval=update_interval,
    )

    await coordinator.async_config_entry_first_refresh()

    for xite_id in coordinator.data["xites"]:
        async_add_entities(
            [
                XoltaDashboardSensor(
                    coordinator,
                    xite_id,
                    "Battery power flow",
                    SensorDeviceClass.POWER,
                    UnitOfPower.KILO_WATT,
                    "mdi:battery-charging-100",
                    "battery_kw",
                    SensorStateClass.MEASUREMENT,
                ),
                XoltaDashboardSensor(
                    coordinator,
                    xite_id,
                    "PV power",
                    SensorDeviceClass.POWER,
                    UnitOfPower.KILO_WATT,
                    "mdi:solar-power",
                    "solar_kw",
                    SensorStateClass.MEASUREMENT,
                ),
                XoltaDashboardSensor(
                    coordinator,
                    xite_id,
                    "Power consumption",
                    SensorDeviceClass.POWER,
                    UnitOfPower.KILO_WATT,
                    "mdi:home-lightning-bolt",
                    "consumption_kw",
                    SensorStateClass.MEASUREMENT,
                ),
                XoltaDashboardSensor(
                    coordinator,
                    xite_id,
                    "Battery charge level",
                    SensorDeviceClass.BATTERY,
                    PERCENTAGE,
                    None,
                    "battery_soc_pct",
                    None,
                ),
                XoltaDashboardSensor(
                    coordinator,
                    xite_id,
                    "Grid power flow",
                    SensorDeviceClass.POWER,
                    UnitOfPower.KILO_WATT,
                    "mdi:transmission-tower",
                    "grid_kw",
                    SensorStateClass.MEASUREMENT,
                ),
            ]
        )


class XoltaDashboardSensor(CoordinatorEntity, SensorEntity):
    def __init__(
        self,
        coordinator,
        xite_id,
        sensor_type,
        device_class,
        units,
        icon,
        data_key,
        state_class,
    ):
        super().__init__(coordinator)
        self._xite_id = xite_id
        self._data_key = data_key
        self._attr_name = sensor_type
        self._attr_unique_id = f"{xite_id}-{sensor_type}"
        self._attr_icon = icon
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = units
        self._attr_state_class = state_class

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._xite_id)},
            "name": f"Battery {self._xite_id}",
            "manufacturer": "Xolta",
            "model": "Battery",
        }

    @property
    def native_value(self):
        dashboard = self.coordinator.data["dashboard"].get(self._xite_id)
        if dashboard is None:
            return None
        return dashboard.get(self._data_key)



