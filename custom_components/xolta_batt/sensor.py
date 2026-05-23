from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.entity import DeviceInfo
import logging

from datetime import timedelta

from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.const import PERCENTAGE
from .const import DOMAIN, DASHBOARD_UPDATE_INTERVAL_SEC, ENERGY_UPDATE_INTERVAL_SEC

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Add sensors for passed config_entry in HA."""
    xoltaApi = hass.data[DOMAIN][config_entry.entry_id]

    async def async_update_dashboard():
        try:
            return await xoltaApi.get_data(get_dashboard=True, get_energy=False)
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")

    async def async_update_energy():
        try:
            return await xoltaApi.get_data(get_dashboard=False, get_energy=True)
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")

    dashboard_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="XOLTA Dashboard",
        update_method=async_update_dashboard,
        update_interval=timedelta(seconds=DASHBOARD_UPDATE_INTERVAL_SEC),
    )

    energy_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="XOLTA Energy",
        update_method=async_update_energy,
        update_interval=timedelta(seconds=ENERGY_UPDATE_INTERVAL_SEC),
    )

    await dashboard_coordinator.async_config_entry_first_refresh()
    await energy_coordinator.async_config_entry_first_refresh()

    for xite in dashboard_coordinator.data["xites"].xites:
        async_add_entities(
            [
                XoltaDashboardSensor(
                    dashboard_coordinator,
                    xite,
                    "Battery power flow",
                    SensorDeviceClass.POWER,
                    UnitOfPower.KILO_WATT,
                    "mdi:battery-charging-100",
                    "battery_kw",
                    SensorStateClass.MEASUREMENT,
                ),
                XoltaDashboardSensor(
                    dashboard_coordinator,
                    xite,
                    "PV power",
                    SensorDeviceClass.POWER,
                    UnitOfPower.KILO_WATT,
                    "mdi:solar-power",
                    "solar_kw",
                    SensorStateClass.MEASUREMENT,
                ),
                XoltaDashboardSensor(
                    dashboard_coordinator,
                    xite,
                    "Power consumption",
                    SensorDeviceClass.POWER,
                    UnitOfPower.KILO_WATT,
                    "mdi:home-lightning-bolt",
                    "consumption_kw",
                    SensorStateClass.MEASUREMENT,
                ),
                XoltaDashboardSensor(
                    dashboard_coordinator,
                    xite,
                    "Battery charge level",
                    SensorDeviceClass.BATTERY,
                    PERCENTAGE,
                    None,
                    "battery_soc_pct",
                    None,
                ),
                XoltaDashboardSensor(
                    dashboard_coordinator,
                    xite,
                    "Grid power flow",
                    SensorDeviceClass.POWER,
                    UnitOfPower.KILO_WATT,
                    "mdi:transmission-tower",
                    "grid_kw",
                    SensorStateClass.MEASUREMENT,
                ),
                XoltaEnergySensor(
                    energy_coordinator,
                    xite,
                    "Grid energy imported",
                    "mdi:transmission-tower-export",
                    "grid_import",
                ),
                XoltaEnergySensor(
                    energy_coordinator,
                    xite,
                    "Grid energy exported",
                    "mdi:transmission-tower-import",
                    "grid_export",
                ),
                XoltaEnergySensor(
                    energy_coordinator,
                    xite,
                    "Battery energy charged",
                    "mdi:battery-arrow-up",
                    "battery_charged",
                ),
                XoltaEnergySensor(
                    energy_coordinator,
                    xite,
                    "Battery energy discharged",
                    "mdi:battery-arrow-down",
                    "battery_discharged",
                ),
                XoltaEnergySensor(
                    energy_coordinator,
                    xite,
                    "PV energy",
                    "mdi:solar-power",
                    "pv",
                ),
                XoltaEnergySensor(
                    energy_coordinator,
                    xite,
                    "Energy consumption",
                    "mdi:home-lightning-bolt",
                    "consumption",
                ),
            ]
        )


def _build_device_info(xite) -> DeviceInfo:
    """Build a DeviceInfo from an Xite object (called once per sensor at setup)."""
    battery = xite.batteries[0] if xite.batteries else None
    name = (
        xite.metadata.name if xite.metadata and xite.metadata.name else None
    ) or f"Battery {xite.xite_id}"
    area = xite.metadata.address if xite.metadata and xite.metadata.address else None
    return DeviceInfo(
        identifiers={(DOMAIN, xite.xite_id)},
        name=name,
        manufacturer="Ebbefos",
        model=battery.brand if battery and battery.brand else "Battery",
        suggested_area=area,
    )


class XoltaDashboardSensor(CoordinatorEntity, SensorEntity):
    def __init__(
        self,
        coordinator,
        xite,
        sensor_type,
        device_class,
        units,
        icon,
        data_key,
        state_class,
    ):
        super().__init__(coordinator)
        self._xite_id = xite.xite_id
        self._data_key = data_key
        self._attr_name = sensor_type
        self._attr_unique_id = f"{xite.xite_id}-{sensor_type}"
        self._attr_icon = icon
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = units
        self._attr_state_class = state_class
        self._attr_device_info = _build_device_info(xite)

    @property
    def native_value(self):
        dashboard = self.coordinator.data["dashboard"].get(self._xite_id)
        if dashboard is None:
            return None
        return getattr(dashboard, self._data_key)


class XoltaEnergySensor(CoordinatorEntity, SensorEntity):
    """Sensor for today's cumulative energy totals from GetCurrentXiteActuals."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator, xite, sensor_type, icon, data_key):
        super().__init__(coordinator)
        self._xite_id = xite.xite_id
        self._data_key = data_key
        self._attr_name = sensor_type
        self._attr_unique_id = f"{xite.xite_id}-energy-{sensor_type}"
        self._attr_icon = icon
        self._attr_device_info = _build_device_info(xite)

    @property
    def native_value(self):
        energy = self.coordinator.data["energy"].get(self._xite_id)
        if energy is None:
            return None
        return getattr(energy, self._data_key)
