"""Data transfer objects for the Xolta/Ebbefos API."""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Granularity enum (xeam.common.Granularity from date.proto)
# ---------------------------------------------------------------------------

GRANULARITY_UNSPECIFIED = 0
GRANULARITY_QUARTER_HOURLY = 1
GRANULARITY_HOURLY = 2

# ---------------------------------------------------------------------------
# EntityConnectionStatus enum (xeam.bacon.EntityConnectionStatus)
# ---------------------------------------------------------------------------

CONNECTION_STATUS_UNSPECIFIED = 0
CONNECTION_STATUS_ONLINE = 1
CONNECTION_STATUS_OFFLINE = 2

# ---------------------------------------------------------------------------
# BatteryState enum (xeam.bacon.BatteryState)
# ---------------------------------------------------------------------------

BATTERY_STATE_UNSPECIFIED = 0
BATTERY_STATE_RUNNING = 1
BATTERY_STATE_INITIALIZING = 2
BATTERY_STATE_ERROR = 3
BATTERY_STATE_MAINTENANCE = 4
BATTERY_STATE_SLEEP = 5

# ---------------------------------------------------------------------------
# Sub-message types
# ---------------------------------------------------------------------------


@dataclass
class XiteMinute:
    """A point in time (local calendar) for an xite data record."""

    year: int = 0
    month: int = 0
    day: int = 0
    hour: int = 0
    minute: int = 0


@dataclass
class EnergyFlow:
    """Directional energy flows between components (kWh)."""

    solar_to_battery_kwh: float = 0.0
    solar_to_grid_kwh: float = 0.0
    solar_to_consumption_kwh: float = 0.0
    battery_to_grid_kwh: float = 0.0
    battery_to_consumption_kwh: float = 0.0
    grid_to_battery_kwh: float = 0.0
    grid_to_consumption_kwh: float = 0.0


@dataclass
class MoneyFlow:
    """Directional money flows between components (currency units)."""

    solar_to_consumption_savings: float = 0.0
    battery_to_consumption_savings: float = 0.0
    solar_to_grid_earnings: float = 0.0
    battery_to_grid_earnings: float = 0.0
    grid_to_consumption_expense: float = 0.0
    grid_to_battery_expense: float = 0.0


# ---------------------------------------------------------------------------
# XiteActual and response wrappers
# ---------------------------------------------------------------------------


@dataclass
class XiteActual:
    """A single data record from GetCurrentXiteActuals / GetHistoricXiteActuals."""

    time: XiteMinute | None = None
    solar_production_kwh: float = 0.0
    battery_soc: float = 0.0
    consumption_kwh: float = 0.0
    grid_import_kwh: float = 0.0
    grid_export_kwh: float = 0.0
    without_solar_and_battery_cost: float = 0.0
    without_battery_cost: float = 0.0
    cost: float = 0.0
    earnings: float = 0.0
    savings: float = 0.0
    total_savings: float = 0.0
    energy_flow: EnergyFlow | None = None
    money_flow: MoneyFlow | None = None


@dataclass
class GetCurrentXiteActualsResponse:
    """Decoded response from GetCurrentXiteActuals."""

    actuals: list[XiteActual]


@dataclass
class GetHistoricXiteActualsResponse:
    """Decoded response from GetHistoricXiteActuals."""

    actuals: list[XiteActual]
    totals: XiteActual | None = None


# ---------------------------------------------------------------------------
# GetXites response model
# ---------------------------------------------------------------------------


@dataclass
class XiteMeta:
    """Display metadata for an xite."""

    name: str = ""
    address: str = ""


@dataclass
class AddressId:
    """Address identifier for an xite (currently Danish DAR address ID)."""

    dk_dar: str = ""


@dataclass
class Battery:
    """A battery device attached to an xite."""

    battery_id: int = 0
    name: str = ""
    key: str = ""
    brand: str = ""


@dataclass
class Xite:
    """A single xite (site) returned by GetXites."""

    xite_id: int = 0
    metadata: XiteMeta | None = None
    address_id: AddressId | None = None
    country_code: str = ""
    batteries: list[Battery] | None = None
    is_deletable: bool = False

    def __post_init__(self) -> None:
        if self.batteries is None:
            self.batteries = []


@dataclass
class GetXitesResponse:
    """Decoded response from GetXites."""

    xites: list[Xite]


# ---------------------------------------------------------------------------
# Real-time dashboard and daily energy totals
# ---------------------------------------------------------------------------


@dataclass
class DashboardData:
    """Real-time telemetry snapshot for a single xite."""

    battery_kw: float = 0.0
    battery_soc_pct: float = 0.0
    solar_kw: float = 0.0
    grid_kw: float = 0.0
    consumption_kw: float = 0.0
    buy_price_kwh: float = 0.0
    sell_price_kwh: float = 0.0
    air_temperature: float = 0.0


@dataclass
class EnergyTotals:
    """Daily cumulative energy and cost totals for a single xite."""

    pv: float = 0.0
    battery_charged: float = 0.0
    battery_discharged: float = 0.0
    grid_export: float = 0.0
    grid_import: float = 0.0
    consumption: float = 0.0
    cost: float = 0.0
    earnings: float = 0.0
    savings: float = 0.0
    total_savings: float = 0.0
    without_solar_and_battery_cost: float = 0.0
    without_battery_cost: float = 0.0


# ---------------------------------------------------------------------------
# GetXiteBatteriesStatus response model (xeam.bacon.Bacon)
# ---------------------------------------------------------------------------


@dataclass
class BatteryMeta:
    """Metadata about a bacon battery's external integration."""

    external_source: int = 0  # BatteryExternalSource enum
    external_key: str = ""
    product_name: str = ""


@dataclass
class BaconBattery:
    """A battery entity from the bacon service (xeam.bacon.Battery)."""

    battery_id: int = 0
    capacity_kwh: float = 0.0
    usable_capacity_kwh: float = 0.0
    inverter_max_kw: float = 0.0
    available_commands: list[int] | None = None  # list of BatteryCommandType
    battery_meta: BatteryMeta | None = None

    def __post_init__(self) -> None:
        if self.available_commands is None:
            self.available_commands = []


@dataclass
class BatteryStatus:
    """Status snapshot of a single battery from GetXiteBatteriesStatus."""

    battery: BaconBattery | None = None
    soc: float = 0.0  # 0..1
    connection_status: int = CONNECTION_STATUS_UNSPECIFIED
    connection_status_timestamp: float | None = None  # unix seconds (UTC)
    latest_telemetry_timestamp: float | None = None
    calibration_required_since_timestamp: float | None = None
    last_calibration_at_timestamp: float | None = None
    state: int = BATTERY_STATE_UNSPECIFIED
    state_timestamp: float | None = None


@dataclass
class GetXiteBatteriesStatusResponse:
    """Decoded response from GetXiteBatteriesStatus."""

    batteries: list[BatteryStatus]
