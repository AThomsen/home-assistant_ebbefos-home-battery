from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import cast

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import DOMAIN, DASHBOARD_UPDATE_INTERVAL_SEC, ENERGY_UPDATE_INTERVAL_SEC
from .models import (
    ENERGY_MODE_MAXIMIZE_SAVINGS,
    ENERGY_MODE_NONE,
    ENERGY_MODE_REMOTE_CONTROL,
    ENERGY_MODE_SELF_RELIANCE,
    XiteEnergyMode,
)

_LOGGER = logging.getLogger(__name__)

_BATTERY_STATE_NAME = {
    0: "Unspecified",
    1: "Running",
    2: "Initializing",
    3: "Error",
    4: "Maintenance",
    5: "Sleep",
}

_ENERGY_MODE_STR = {
    ENERGY_MODE_NONE: "none",
    ENERGY_MODE_MAXIMIZE_SAVINGS: "maximize_savings",
    ENERGY_MODE_SELF_RELIANCE: "self_reliance",
    ENERGY_MODE_REMOTE_CONTROL: "remote_control",
}

_ENERGY_MODE_DISPLAY_TEXT: dict[str, str] = {
    "none": "None",
    "maximize_savings": "Optimize Energy Economy",
    "self_reliance": "Solar Battery",
    "remote_control": "Remote control",
    "pause": "Battery paused",
    "recalibrate": "Battery calibrating",
}

_ENERGY_MODE_ICON: dict[str, str] = {
    "none": "mdi:flash-auto",
    "maximize_savings": "mdi:piggy-bank",
    "self_reliance": "mdi:solar-power-variant",
    "remote_control": "mdi:remote",
    "charge": "mdi:battery-arrow-up",
    "discharge": "mdi:battery-arrow-down",
    "pause": "mdi:pause-circle",
    "recalibrate": "mdi:sync",
}


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Add sensors for passed config_entry in HA."""
    ebbefosApi = hass.data[DOMAIN][config_entry.entry_id]

    async def async_update_dashboard():
        try:
            return await ebbefosApi.get_data(get_dashboard=True, get_energy=False)
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")

    async def async_update_energy():
        try:
            return await ebbefosApi.get_data(get_dashboard=False, get_energy=True)
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")

    dashboard_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="Ebbefos Dashboard",
        update_method=async_update_dashboard,
        update_interval=timedelta(seconds=DASHBOARD_UPDATE_INTERVAL_SEC),
    )

    energy_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="Ebbefos Energy",
        update_method=async_update_energy,
        update_interval=timedelta(seconds=ENERGY_UPDATE_INTERVAL_SEC),
    )

    await dashboard_coordinator.async_config_entry_first_refresh()
    await energy_coordinator.async_config_entry_first_refresh()

    for xite in dashboard_coordinator.data["xites"].xites:
        async_add_entities(
            [
                EbbefosDashboardSensor(
                    dashboard_coordinator,
                    xite,
                    "battery_power_flow",
                    SensorDeviceClass.POWER,
                    UnitOfPower.KILO_WATT,
                    "mdi:battery-charging-100",
                    "battery_kw",
                    SensorStateClass.MEASUREMENT,
                ),
                EbbefosDashboardSensor(
                    dashboard_coordinator,
                    xite,
                    "pv_power",
                    SensorDeviceClass.POWER,
                    UnitOfPower.KILO_WATT,
                    "mdi:solar-power",
                    "solar_kw",
                    SensorStateClass.MEASUREMENT,
                ),
                EbbefosDashboardSensor(
                    dashboard_coordinator,
                    xite,
                    "power_consumption",
                    SensorDeviceClass.POWER,
                    UnitOfPower.KILO_WATT,
                    "mdi:home-lightning-bolt",
                    "consumption_kw",
                    SensorStateClass.MEASUREMENT,
                ),
                EbbefosDashboardSensor(
                    dashboard_coordinator,
                    xite,
                    "battery_soc",
                    None,
                    PERCENTAGE,
                    "mdi:home-battery",
                    "battery_soc_pct",
                    None,
                ),
                EbbefosDashboardSensor(
                    dashboard_coordinator,
                    xite,
                    "grid_power_flow",
                    SensorDeviceClass.POWER,
                    UnitOfPower.KILO_WATT,
                    "mdi:transmission-tower",
                    "grid_kw",
                    SensorStateClass.MEASUREMENT,
                ),
                EbbefosXiteEnergyModeSensor(dashboard_coordinator, xite),
                EbbefosEnergySensor(
                    energy_coordinator,
                    xite,
                    "grid_energy_imported_today",
                    "mdi:transmission-tower-export",
                    "grid_import",
                ),
                EbbefosEnergySensor(
                    energy_coordinator,
                    xite,
                    "grid_energy_exported_today",
                    "mdi:transmission-tower-import",
                    "grid_export",
                ),
                EbbefosEnergySensor(
                    energy_coordinator,
                    xite,
                    "battery_energy_charged_today",
                    "mdi:battery-arrow-up",
                    "battery_charged",
                ),
                EbbefosEnergySensor(
                    energy_coordinator,
                    xite,
                    "battery_energy_discharged_today",
                    "mdi:battery-arrow-down",
                    "battery_discharged",
                ),
                EbbefosEnergySensor(
                    energy_coordinator,
                    xite,
                    "pv_energy_today",
                    "mdi:solar-power",
                    "pv",
                ),
                EbbefosEnergySensor(
                    energy_coordinator,
                    xite,
                    "energy_consumption_today",
                    "mdi:home-lightning-bolt",
                    "consumption",
                ),
                EbbefosDailyCostSensor(
                    energy_coordinator,
                    xite,
                    "cost_today",
                    "mdi:cash-minus",
                    "cost",
                ),
                EbbefosDailyCostSensor(
                    energy_coordinator,
                    xite,
                    "earnings_today",
                    "mdi:cash-plus",
                    "earnings",
                ),
                EbbefosDailyCostSensor(
                    energy_coordinator,
                    xite,
                    "savings_today",
                    "mdi:piggy-bank",
                    "savings",
                ),
                EbbefosDailyCostSensor(
                    energy_coordinator,
                    xite,
                    "total_savings_today",
                    "mdi:piggy-bank-outline",
                    "total_savings",
                ),
                EbbefosDailyCostSensor(
                    energy_coordinator,
                    xite,
                    "cost_without_solar_and_battery_today",
                    "mdi:cash-remove",
                    "without_solar_and_battery_cost",
                ),
                EbbefosDailyCostSensor(
                    energy_coordinator,
                    xite,
                    "cost_without_battery_today",
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
                    [EbbefosBatterySensor(dashboard_coordinator, xite, bid, bat_name)]
                )


def _build_device_info(xite) -> DeviceInfo:
    """Build a DeviceInfo from an Xite object (called once per sensor at setup)."""
    name = (
        xite.metadata.name if xite.metadata and xite.metadata.name else None
    ) or f"Battery {xite.xite_id}"
    area = xite.metadata.address if xite.metadata and xite.metadata.address else None

    model = "Site with: "
    if xite.batteries:
        model += ", ".join(f"{b.brand} {b.name}" for b in xite.batteries)
    else:
        model += "No battery info"

    return DeviceInfo(
        identifiers={(DOMAIN, xite.xite_id)},
        name=name,
        manufacturer="Ebbefos Energy A/S",
        model=model,
        suggested_area=area,
    )


class EbbefosBatterySensor(CoordinatorEntity, SensorEntity):
    """One sensor per physical battery — operational status as value, details as attributes."""

    _attr_has_entity_name = True
    _attr_translation_key = "battery_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
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


class EbbefosDashboardSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        xite,
        translation_key,
        device_class,
        units,
        icon,
        data_key,
        state_class,
    ):
        super().__init__(coordinator)
        self._xite_id = xite.xite_id
        self._data_key = data_key
        self._attr_translation_key = translation_key
        self._attr_unique_id = f"{xite.xite_id}-{translation_key}"
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


class EbbefosEnergySensor(CoordinatorEntity, SensorEntity):
    """Sensor for today's cumulative energy totals from GetCurrentXiteActuals."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator, xite, translation_key, icon, data_key):
        super().__init__(coordinator)
        self._xite_id = xite.xite_id
        self._data_key = data_key
        self._attr_translation_key = translation_key
        self._attr_unique_id = f"{xite.xite_id}-energy-{translation_key}"
        self._attr_icon = icon
        self._attr_device_info = _build_device_info(xite)

    @property
    def native_value(self):
        energy = self.coordinator.data["energy"].get(self._xite_id)
        if energy is None:
            return None
        return getattr(energy, self._data_key)


class EbbefosDailyCostSensor(CoordinatorEntity, SensorEntity):
    """Sensor for today's cumulative cost/savings totals from GetCurrentXiteActuals."""

    _attr_has_entity_name = True
    # We can't use TOTAL_INCREASING here since some of these (cost without solar/battery)
    # can actually decrease during the day, but we still want the daily reset behavior.
    # We'll use last_reset to signal start of day when value resets.
    _attr_state_class = SensorStateClass.TOTAL
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "DKK"
    _attr_suggested_display_precision = 2
    # hide these initially since many users won't care about them
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, xite, translation_key, icon, data_key):
        super().__init__(coordinator)
        self._xite_id = xite.xite_id
        self._data_key = data_key
        self._attr_translation_key = translation_key
        self._attr_unique_id = f"{xite.xite_id}-cost-{translation_key}"
        self._attr_icon = icon
        self._attr_device_info = _build_device_info(xite)

    @property
    def last_reset(self):
        """Return the start of the day this data covers, derived from the API response."""
        energy = self.coordinator.data["energy"].get(self._xite_id)
        if energy is not None and energy.day_start is not None:
            return energy.day_start
        # Fallback: UTC midnight (should not normally be reached)
        return datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    @property
    def native_value(self):
        energy = self.coordinator.data["energy"].get(self._xite_id)
        if energy is None:
            return None
        return getattr(energy, self._data_key)


class EbbefosXiteEnergyModeSensor(CoordinatorEntity, SensorEntity):
    """Sensor for the current energy mode / battery override command for an xite."""

    _attr_has_entity_name = True
    _attr_translation_key = "energy_mode"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [
        "none",
        "maximize_savings",
        "self_reliance",
        "remote_control",
        "charge",
        "discharge",
        "pause",
        "recalibrate",
    ]

    def __init__(self, coordinator, xite) -> None:
        super().__init__(coordinator)
        self._xite_id = xite.xite_id
        self._attr_unique_id = f"{xite.xite_id}-energy-mode"
        self._attr_device_info = _build_device_info(xite)

    def _get_mode(self) -> XiteEnergyMode | None:
        return cast(
            XiteEnergyMode | None,
            self.coordinator.data.get("energy_mode", {}).get(self._xite_id),
        )

    @property
    def native_value(self) -> str | None:
        mode = self._get_mode()
        if mode is None:
            return None
        if mode.battery and mode.battery.user_command:
            return mode.battery.user_command.command_type or "unknown"
        return _ENERGY_MODE_STR.get(mode.energy_mode, "unknown")

    @property
    def icon(self) -> str:
        return _ENERGY_MODE_ICON.get(self.native_value or "", "mdi:flash")

    @property
    def extra_state_attributes(self) -> dict:
        mode = self._get_mode()
        if mode is None:
            return {}

        attrib: dict = {
            "energy_mode": _ENERGY_MODE_STR.get(mode.energy_mode, "unknown")
        }

        if mode.battery and mode.battery.user_command:
            bat_act = mode.battery.user_command
            value = bat_act.command_type or "unknown"
            text = _ENERGY_MODE_DISPLAY_TEXT.get(value, value)
            match bat_act.command_type:
                case "discharge":
                    if bat_act.discharge_type == "fixed":
                        text = "Manual override - Discharging to {0}%".format(
                            int((bat_act.down_to_soc or 0) * 100)
                        )
                        attrib.update(
                            {
                                "discharge_type": bat_act.discharge_type,
                                "target_soc": bat_act.down_to_soc,
                            }
                        )
                case "charge":
                    if bat_act.charge_type == "fixed":
                        text = "Manual override - Charging to {0}%".format(
                            int((bat_act.up_to_soc or 0) * 100)
                        )
                        attrib.update(
                            {
                                "charge_type": bat_act.charge_type,
                                "target_soc": bat_act.up_to_soc,
                            }
                        )
        else:
            value = _ENERGY_MODE_STR.get(mode.energy_mode, "unknown")
            text = _ENERGY_MODE_DISPLAY_TEXT.get(value, value)

        attrib["text"] = text
        return attrib
