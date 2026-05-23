from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.entity import DeviceInfo
import logging

from datetime import datetime, timezone, timedelta

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

_BATTERY_STATE_NAME = {
    0: "Unspecified",
    1: "Running",
    2: "Initializing",
    3: "Error",
    4: "Maintenance",
    5: "Sleep",
}
_CONNECTION_STATUS_NAME = {0: "Unspecified", 1: "Online", 2: "Offline"}


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
                XoltaDailyCostSensor(
                    energy_coordinator,
                    xite,
                    "Cost",
                    "mdi:cash-minus",
                    "cost",
                ),
                XoltaDailyCostSensor(
                    energy_coordinator,
                    xite,
                    "Earnings",
                    "mdi:cash-plus",
                    "earnings",
                ),
                XoltaDailyCostSensor(
                    energy_coordinator,
                    xite,
                    "Savings",
                    "mdi:piggy-bank",
                    "savings",
                ),
                XoltaDailyCostSensor(
                    energy_coordinator,
                    xite,
                    "Total savings",
                    "mdi:piggy-bank-outline",
                    "total_savings",
                ),
                XoltaDailyCostSensor(
                    energy_coordinator,
                    xite,
                    "Cost without solar and battery",
                    "mdi:cash-remove",
                    "without_solar_and_battery_cost",
                ),
                XoltaDailyCostSensor(
                    energy_coordinator,
                    xite,
                    "Cost without battery",
                    "mdi:cash-remove",
                    "without_battery_cost",
                ),
            ]
        )

        battery_status_response = dashboard_coordinator.data["battery_status"].get(
            xite.xite_id
        )
        if battery_status_response:
            for bs in battery_status_response.batteries:
                if bs.battery is None:
                    continue
                bid = bs.battery.battery_id
                bat_name = bs.battery.battery_meta.external_key
                async_add_entities(
                    [XoltaBatterySensor(dashboard_coordinator, xite, bid, bat_name)]
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


class XoltaBatterySensor(CoordinatorEntity, SensorEntity):
    """One sensor per physical battery — operational status as value, details as attributes."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [
        "Unspecified",
        "Offline",
        "Running",
        "Initializing",
        "Error",
        "Maintenance",
        "Sleep",
    ]

    def __init__(self, coordinator, xite, battery_id: int, battery_name: str) -> None:
        super().__init__(coordinator)
        self._xite_id = xite.xite_id
        self._battery_id = battery_id
        self._attr_name = battery_name
        self._attr_unique_id = f"{xite.xite_id}-battery-{battery_id}"
        self._attr_icon = "mdi:home-battery"
        self._attr_device_info = _build_device_info(xite)

    def _find_status(self):
        response = self.coordinator.data["battery_status"].get(self._xite_id)
        if response is None:
            return None
        return next(
            (
                bs
                for bs in response.batteries
                if bs.battery and bs.battery.battery_id == self._battery_id
            ),
            None,
        )

    @property
    def native_value(self):
        bs = self._find_status()
        if bs is None:
            return None
        if bs.connection_status == 2:  # OFFLINE
            return "Offline"
        if bs.connection_status == 0:  # UNSPECIFIED
            return "Unspecified"
        return _BATTERY_STATE_NAME.get(bs.state, "Unspecified")

    @property
    def extra_state_attributes(self):
        bs = self._find_status()
        if bs is None:
            return {}
        attrs = {
            "soc_pct": round(bs.soc * 100, 1),
        }
        if bs.battery:
            if bs.battery.battery_meta:
                attrs["model"] = bs.battery.battery_meta.product_name
            attrs["capacity_kwh"] = bs.battery.capacity_kwh
            attrs["usable_capacity_kwh"] = bs.battery.usable_capacity_kwh
            attrs["inverter_max_kw"] = bs.battery.inverter_max_kw
        if bs.latest_telemetry_timestamp is not None:
            attrs["latest_telemetry"] = datetime.fromtimestamp(
                bs.latest_telemetry_timestamp, tz=timezone.utc
            ).isoformat()
        if bs.state_timestamp is not None:
            attrs["state_since"] = datetime.fromtimestamp(
                bs.state_timestamp, tz=timezone.utc
            ).isoformat()
        return attrs


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


class XoltaDailyCostSensor(CoordinatorEntity, SensorEntity):
    """Sensor for today's cumulative cost/savings totals from GetCurrentXiteActuals."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "DKK"
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, xite, sensor_type, icon, data_key):
        super().__init__(coordinator)
        self._xite_id = xite.xite_id
        self._data_key = data_key
        self._attr_name = sensor_type
        self._attr_unique_id = f"{xite.xite_id}-cost-{sensor_type}"
        self._attr_icon = icon
        self._attr_device_info = _build_device_info(xite)

    @property
    def native_value(self):
        energy = self.coordinator.data["energy"].get(self._xite_id)
        if energy is None:
            return None
        return getattr(energy, self._data_key)


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
