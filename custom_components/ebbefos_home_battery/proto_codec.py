"""Protobuf / gRPC-Web encoding and decoding for the Ebbefos energy platform API."""

from __future__ import annotations

import struct

from .models import (
    AddressId,
    BaconBattery,
    BatteryMeta,
    BatteryStatus,
    Battery,
    DashboardData,
    EnergyFlow,
    EnergyTotals,
    GetCurrentXiteActualsResponse,
    GetXiteBatteriesStatusResponse,
    GetXitesResponse,
    GRANULARITY_HOURLY,
    MoneyFlow,
    Xite,
    XiteActual,
    XiteMeta,
    XiteMinute,
)

# ---------------------------------------------------------------------------
# Low-level varint and streaming reader
# ---------------------------------------------------------------------------


def _encode_varint(value: int) -> bytes:
    """Encode an unsigned integer as a protobuf varint."""
    buf = []
    while value > 0x7F:
        buf.append((value & 0x7F) | 0x80)
        value >>= 7
    buf.append(value & 0x7F)
    return bytes(buf)


def _decode_varint(data: bytes, pos: int) -> tuple[int, int]:
    """Decode a varint from *data* at *pos*. Returns (value, new_pos)."""
    result = 0
    shift = 0
    while pos < len(data):
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7
    msg = "Truncated varint"
    raise ValueError(msg)


class _ProtoReader:
    """Minimal streaming protobuf reader."""

    def __init__(self, data: bytes, end: int | None = None) -> None:
        self._data = data
        self._pos = 0
        self._end = end if end is not None else len(data)

    @property
    def has_data(self) -> bool:
        return self._pos < self._end

    def read_tag(self) -> tuple[int, int]:
        tag = self._read_varint_raw()
        return tag >> 3, tag & 0x7

    def _read_varint_raw(self) -> int:
        val, self._pos = _decode_varint(self._data, self._pos)
        return val

    def read_varint(self) -> int:
        return self._read_varint_raw()

    def read_double(self) -> float:
        val = struct.unpack_from("<d", self._data, self._pos)[0]
        self._pos += 8
        return val

    def read_bytes(self) -> bytes:
        length = self._read_varint_raw()
        data = self._data[self._pos : self._pos + length]
        self._pos += length
        return data

    def skip_field(self, wire_type: int) -> None:
        if wire_type == 0:
            self._read_varint_raw()
        elif wire_type == 1:
            self._pos += 8
        elif wire_type == 2:
            length = self._read_varint_raw()
            self._pos += length
        elif wire_type == 5:
            self._pos += 4


# ---------------------------------------------------------------------------
# gRPC-Web framing
# ---------------------------------------------------------------------------


def grpc_web_frame(proto_bytes: bytes) -> bytes:
    """Wrap proto bytes in a gRPC-Web data frame (no compression)."""
    return b"\x00" + struct.pack(">I", len(proto_bytes)) + proto_bytes


def grpc_web_unframe(data: bytes) -> bytes:
    """Extract the first data frame's proto bytes from a gRPC-Web response."""
    pos = 0
    while pos + 5 <= len(data):
        frame_type = data[pos]
        length = struct.unpack(">I", data[pos + 1 : pos + 5])[0]
        pos += 5
        if frame_type == 0x00:  # data frame
            return data[pos : pos + length]
        pos += length  # skip trailers (0x80) etc.
    return b""


# ---------------------------------------------------------------------------
# Request encoders
# ---------------------------------------------------------------------------


def encode_get_xites_request() -> bytes:
    """Encode GetXitesRequest (empty message)."""
    return b""


def encode_dashboard_request(xite_id: int) -> bytes:
    """Encode Dashboard request (field 1: xiteId varint)."""
    return b"\x08" + _encode_varint(xite_id)


def encode_get_xite_statistics_request(
    xite_id: int, year: int, month: int, day: int
) -> bytes:
    """Encode GetXiteStatisticsRequest for a single day (period from=to=given date)."""
    date_buf = b"\x08" + _encode_varint(year)
    date_buf += b"\x10" + _encode_varint(month)
    date_buf += b"\x18" + _encode_varint(day)
    period_buf = b"\x0a" + _encode_varint(len(date_buf)) + date_buf
    period_buf += b"\x12" + _encode_varint(len(date_buf)) + date_buf
    buf = b"\x08" + _encode_varint(xite_id)
    buf += b"\x12" + _encode_varint(len(period_buf)) + period_buf
    return buf


def encode_get_current_xite_actuals_request(
    xite_id: int, granularity: int = GRANULARITY_HOURLY
) -> bytes:
    """Encode GetCurrentXiteActualsRequest (field 1: xiteId, field 2: granularity)."""
    buf = b"\x08" + _encode_varint(xite_id)
    if granularity != 0:
        buf += b"\x10" + _encode_varint(granularity)
    return buf


# ---------------------------------------------------------------------------
# Internal sub-message decoders
# ---------------------------------------------------------------------------


def _decode_battery_telemetry(data: bytes) -> tuple[float, float]:
    """Return (battery_kw, soc_0_to_1) from a BatteryTelemetry message."""
    r = _ProtoReader(data)
    soc = 0.0
    kw = 0.0
    while r.has_data:
        field, wt = r.read_tag()
        if field == 1 and wt == 1:  # stateOfCharge (0..1)
            soc = r.read_double()
        elif field == 2 and wt == 1:  # chargingKw → negative convention
            kw = -r.read_double()
        elif field == 3 and wt == 1:  # dischargingKw → positive convention
            kw = r.read_double()
        elif field == 4 and wt == 2:  # idle (empty message)
            r.read_bytes()
        else:
            r.skip_field(wt)
    return kw, soc


def _decode_grid_telemetry(data: bytes) -> float:
    """Return grid_kw from GridTelemetry (positive=import, negative=export)."""
    r = _ProtoReader(data)
    kw = 0.0
    while r.has_data:
        field, wt = r.read_tag()
        if field == 1 and wt == 1:  # importingKw
            kw = r.read_double()
        elif field == 2 and wt == 1:  # exportingKw → negative
            kw = -r.read_double()
        else:
            r.skip_field(wt)
    return kw


def _decode_solar_telemetry(data: bytes) -> float:
    """Return productionKw from SolarTelemetry."""
    r = _ProtoReader(data)
    kw = 0.0
    while r.has_data:
        field, wt = r.read_tag()
        if field == 1 and wt == 1:
            kw = r.read_double()
        else:
            r.skip_field(wt)
    return kw


def _decode_xite_minute(data: bytes) -> XiteMinute:
    r = _ProtoReader(data)
    m = XiteMinute()
    while r.has_data:
        field, wt = r.read_tag()
        if wt == 0:
            val = r.read_varint()
            if field == 1:
                m.year = val
            elif field == 2:
                m.month = val
            elif field == 3:
                m.day = val
            elif field == 4:
                m.hour = val
            elif field == 5:
                m.minute = val
        else:
            r.skip_field(wt)
    return m


_ENERGY_FLOW_FIELDS: dict[int, str] = {
    1: "solar_to_battery_kwh",
    2: "solar_to_grid_kwh",
    3: "solar_to_consumption_kwh",
    4: "battery_to_grid_kwh",
    5: "battery_to_consumption_kwh",
    6: "grid_to_battery_kwh",
    7: "grid_to_consumption_kwh",
}


def _decode_energy_flow(data: bytes) -> EnergyFlow:
    r = _ProtoReader(data)
    ef = EnergyFlow()
    while r.has_data:
        field, wt = r.read_tag()
        if wt == 1:
            attr = _ENERGY_FLOW_FIELDS.get(field)
            if attr is not None:
                setattr(ef, attr, r.read_double())
            else:
                r.skip_field(wt)
        else:
            r.skip_field(wt)
    return ef


_MONEY_FLOW_FIELDS: dict[int, str] = {
    1: "solar_to_consumption_savings",
    2: "battery_to_consumption_savings",
    3: "solar_to_grid_earnings",
    4: "battery_to_grid_earnings",
    5: "grid_to_consumption_expense",
    6: "grid_to_battery_expense",
}


def _decode_money_flow(data: bytes) -> MoneyFlow:
    r = _ProtoReader(data)
    mf = MoneyFlow()
    while r.has_data:
        field, wt = r.read_tag()
        if wt == 1:
            attr = _MONEY_FLOW_FIELDS.get(field)
            if attr is not None:
                setattr(mf, attr, r.read_double())
            else:
                r.skip_field(wt)
        else:
            r.skip_field(wt)
    return mf


_XITE_ACTUAL_FIELDS: dict[int, str] = {
    2: "solar_production_kwh",
    3: "battery_soc",
    4: "consumption_kwh",
    5: "grid_import_kwh",
    6: "grid_export_kwh",
    7: "without_solar_and_battery_cost",
    8: "without_battery_cost",
    9: "cost",
    10: "earnings",
    11: "savings",
    12: "total_savings",
}


def _decode_xite_actual(data: bytes) -> XiteActual:
    r = _ProtoReader(data)
    a = XiteActual()
    while r.has_data:
        field, wt = r.read_tag()
        if wt == 2:
            blob = r.read_bytes()
            if field == 1:
                a.time = _decode_xite_minute(blob)
            elif field == 13:  # noqa: PLR2004
                a.energy_flow = _decode_energy_flow(blob)
            elif field == 14:  # noqa: PLR2004
                a.money_flow = _decode_money_flow(blob)
        elif wt == 1:
            attr = _XITE_ACTUAL_FIELDS.get(field)
            if attr is not None:
                setattr(a, attr, r.read_double())
            else:
                r.skip_field(wt)
        else:
            r.skip_field(wt)
    return a


# ---------------------------------------------------------------------------
# Top-level response decoders
# ---------------------------------------------------------------------------


def _decode_xite_meta(data: bytes) -> XiteMeta:
    """Decode a XiteMeta sub-message."""
    r = _ProtoReader(data)
    m = XiteMeta()
    while r.has_data:
        field, wt = r.read_tag()
        if field == 1 and wt == 2:
            m.name = r.read_bytes().decode("utf-8", errors="replace")
        elif field == 2 and wt == 2:
            m.address = r.read_bytes().decode("utf-8", errors="replace")
        else:
            r.skip_field(wt)
    return m


def _decode_address_id(data: bytes) -> AddressId:
    """Decode an AddressId sub-message."""
    r = _ProtoReader(data)
    a = AddressId()
    while r.has_data:
        field, wt = r.read_tag()
        if field == 1 and wt == 2:  # dkDar string
            a.dk_dar = r.read_bytes().decode("utf-8", errors="replace")
        else:
            r.skip_field(wt)
    return a


def _decode_battery(data: bytes) -> Battery:
    """Decode a Battery sub-message."""
    r = _ProtoReader(data)
    b = Battery()
    while r.has_data:
        field, wt = r.read_tag()
        if field == 1 and wt == 0:
            b.battery_id = r.read_varint()
        elif field == 2 and wt == 2:
            b.name = r.read_bytes().decode("utf-8", errors="replace")
        elif field == 3 and wt == 2:
            b.key = r.read_bytes().decode("utf-8", errors="replace")
        elif field == 4 and wt == 2:
            b.brand = r.read_bytes().decode("utf-8", errors="replace")
        else:
            r.skip_field(wt)
    return b


def _decode_device(data: bytes) -> Battery | None:
    """Decode a Device sub-message; return the Battery if present, else None."""
    r = _ProtoReader(data)
    battery: Battery | None = None
    while r.has_data:
        field, wt = r.read_tag()
        if field == 1 and wt == 2:  # oneof battery
            battery = _decode_battery(r.read_bytes())
        else:
            r.skip_field(wt)
    return battery


def _decode_xite(data: bytes) -> Xite:
    """Decode an Xite sub-message."""
    r = _ProtoReader(data)
    x = Xite()
    while r.has_data:
        field, wt = r.read_tag()
        if field == 1 and wt == 0:  # xiteId (int64 varint)
            x.xite_id = r.read_varint()
        elif field == 2 and wt == 2:  # metadata (XiteMeta)
            x.metadata = _decode_xite_meta(r.read_bytes())
        elif field == 4 and wt == 2:  # addressId (AddressId)
            x.address_id = _decode_address_id(r.read_bytes())
        elif field == 5 and wt == 2:  # countryCode (string)
            x.country_code = r.read_bytes().decode("utf-8", errors="replace")
        elif field == 6 and wt == 2:  # devices (repeated Device)
            bat = _decode_device(r.read_bytes())
            if bat is not None:
                x.batteries.append(bat)
        elif field == 7 and wt == 0:  # isDeletable (bool)
            x.is_deletable = bool(r.read_varint())
        else:
            r.skip_field(wt)  # skip metadata (field 2) and addressId (field 4)
    return x


def decode_get_xites_response(data: bytes) -> GetXitesResponse:
    """Decode GetXitesResponse into a GetXitesResponse dataclass."""
    xites: list[Xite] = []
    r = _ProtoReader(data)
    while r.has_data:
        field, wt = r.read_tag()
        if field == 1 and wt == 2:
            xites.append(_decode_xite(r.read_bytes()))
        else:
            r.skip_field(wt)
    return GetXitesResponse(xites=xites)


def decode_dashboard_response(data: bytes) -> DashboardData:
    """Decode a Dashboard response into a DashboardData dataclass."""
    r = _ProtoReader(data)
    d = DashboardData()
    while r.has_data:
        field, wt = r.read_tag()
        if field == 1 and wt == 2:
            d.battery_kw, soc = _decode_battery_telemetry(r.read_bytes())
            d.battery_soc_pct = round(soc * 100, 1)
        elif field == 2 and wt == 2:
            d.grid_kw = _decode_grid_telemetry(r.read_bytes())
        elif field == 3 and wt == 2:
            d.solar_kw = _decode_solar_telemetry(r.read_bytes())
        elif field == 4 and wt == 1:
            d.consumption_kw = r.read_double()
        elif field == 5 and wt == 1:
            d.buy_price_kwh = r.read_double()
        elif field == 6 and wt == 1:
            d.sell_price_kwh = r.read_double()
        elif field == 7 and wt == 1:
            d.air_temperature = r.read_double()
        elif field == 8 and wt == 0:  # weatherSymbol (discard)
            r.read_varint()
        else:
            r.skip_field(wt)
    return d


def decode_get_xite_statistics_response(data: bytes) -> EnergyTotals:
    """Decode GetXiteStatisticsResponse into daily EnergyTotals (kWh)."""
    r = _ProtoReader(data)
    t = EnergyTotals()
    while r.has_data:
        field, wt = r.read_tag()
        if wt == 1:
            val = r.read_double()
            if field == 4:
                t.pv = val
            elif field == 5:
                t.battery_charged = val
            elif field == 6:
                t.grid_export = val
            elif field == 8:
                t.battery_discharged = val
            elif field == 10:
                t.consumption = val
            elif field == 12:
                t.grid_import = val
        elif wt == 2:
            r.read_bytes()
        else:
            r.skip_field(wt)
    return t


def decode_get_current_xite_actuals_response(
    data: bytes,
) -> GetCurrentXiteActualsResponse:
    """Decode GetCurrentXiteActualsResponse into a GetCurrentXiteActualsResponse dataclass."""
    r = _ProtoReader(data)
    actuals: list[XiteActual] = []
    while r.has_data:
        field, wt = r.read_tag()
        if field == 1 and wt == 2:
            actuals.append(_decode_xite_actual(r.read_bytes()))
        else:
            r.skip_field(wt)
    return GetCurrentXiteActualsResponse(actuals=actuals)


def sum_xite_actuals(actuals: list[XiteActual]) -> EnergyTotals:
    """Sum per-interval XiteActual records into daily EnergyTotals (kWh)."""
    t = EnergyTotals()
    for a in actuals:
        t.pv += a.solar_production_kwh
        t.grid_import += a.grid_import_kwh
        t.grid_export += a.grid_export_kwh
        t.consumption += a.consumption_kwh
        t.cost += a.cost
        t.earnings += a.earnings
        t.savings += a.savings
        t.total_savings += a.total_savings
        t.without_solar_and_battery_cost += a.without_solar_and_battery_cost
        t.without_battery_cost += a.without_battery_cost
        if a.energy_flow is not None:
            ef = a.energy_flow
            t.battery_charged += ef.solar_to_battery_kwh + ef.grid_to_battery_kwh
            t.battery_discharged += (
                ef.battery_to_grid_kwh + ef.battery_to_consumption_kwh
            )
    return t


# ---------------------------------------------------------------------------
# GetXiteBatteriesStatus (xeam.bacon.Bacon)
# ---------------------------------------------------------------------------


def encode_get_xite_batteries_status_request(xite_id: int) -> bytes:
    """Encode GetXiteBatteriesStatusRequest (field 1: xiteId int64 varint)."""
    return b"\x08" + _encode_varint(xite_id)


def _decode_timestamp(data: bytes) -> float:
    """Decode a google.protobuf.Timestamp to a UTC unix timestamp (float seconds)."""
    r = _ProtoReader(data)
    seconds = 0
    nanos = 0
    while r.has_data:
        field, wt = r.read_tag()
        if field == 1 and wt == 0:
            seconds = r.read_varint()
        elif field == 2 and wt == 0:
            nanos = r.read_varint()
        else:
            r.skip_field(wt)
    return seconds + nanos / 1_000_000_000


def _decode_battery_meta(data: bytes) -> BatteryMeta:
    """Decode a xeam.bacon.BatteryMeta sub-message."""
    r = _ProtoReader(data)
    m = BatteryMeta()
    while r.has_data:
        field, wt = r.read_tag()
        if field == 1 and wt == 0:
            m.external_source = r.read_varint()
        elif field == 2 and wt == 2:
            m.external_key = r.read_bytes().decode("utf-8", errors="replace")
        elif field == 3 and wt == 2:
            m.product_name = r.read_bytes().decode("utf-8", errors="replace")
        else:
            r.skip_field(wt)
    return m


def _decode_bacon_battery(data: bytes) -> BaconBattery:
    """Decode a xeam.bacon.Battery sub-message."""
    r = _ProtoReader(data)
    b = BaconBattery()
    while r.has_data:
        field, wt = r.read_tag()
        if field == 1 and wt == 0:  # id (int64 varint)
            b.battery_id = r.read_varint()
        elif field == 2 and wt == 1:  # capacityKwh (double)
            b.capacity_kwh = r.read_double()
        elif field == 6 and wt == 1:  # usableCapacityKwh (double)
            b.usable_capacity_kwh = r.read_double()
        elif field == 3 and wt == 1:  # inverterMaxKw (double)
            b.inverter_max_kw = r.read_double()
        elif field == 4 and wt == 0:  # availableCommands (unpacked varint)
            b.available_commands.append(r.read_varint())
        elif field == 4 and wt == 2:  # availableCommands (packed)
            blob = r.read_bytes()
            pr = _ProtoReader(blob)
            while pr.has_data:
                b.available_commands.append(pr.read_varint())
        elif field == 5 and wt == 2:  # batteryMeta
            b.battery_meta = _decode_battery_meta(r.read_bytes())
        else:
            r.skip_field(wt)
    return b


def _decode_battery_status(data: bytes) -> BatteryStatus:
    """Decode a xeam.bacon.BatteryStatus sub-message."""
    r = _ProtoReader(data)
    s = BatteryStatus()
    while r.has_data:
        field, wt = r.read_tag()
        if field == 1 and wt == 2:  # battery
            s.battery = _decode_bacon_battery(r.read_bytes())
        elif field == 9 and wt == 1:  # soc (double)
            s.soc = r.read_double()
        elif field == 2 and wt == 0:  # connectionStatus (int32 varint)
            s.connection_status = r.read_varint()
        elif field == 3 and wt == 2:  # connectionStatusTimestamp
            s.connection_status_timestamp = _decode_timestamp(r.read_bytes())
        elif field == 4 and wt == 2:  # latestTelemetryTimestamp
            s.latest_telemetry_timestamp = _decode_timestamp(r.read_bytes())
        elif field == 5 and wt == 2:  # calibrationRequiredSinceTimestamp
            s.calibration_required_since_timestamp = _decode_timestamp(r.read_bytes())
        elif field == 6 and wt == 2:  # lastCalibrationAtTimestamp
            s.last_calibration_at_timestamp = _decode_timestamp(r.read_bytes())
        elif field == 7 and wt == 0:  # state (int32 varint)
            s.state = r.read_varint()
        elif field == 8 and wt == 2:  # stateTimestamp
            s.state_timestamp = _decode_timestamp(r.read_bytes())
        else:
            r.skip_field(wt)
    return s


def decode_get_xite_batteries_status_response(
    data: bytes,
) -> GetXiteBatteriesStatusResponse:
    """Decode GetXiteBatteriesStatusResponse into a typed dataclass."""
    r = _ProtoReader(data)
    batteries: list[BatteryStatus] = []
    while r.has_data:
        field, wt = r.read_tag()
        if field == 1 and wt == 2:
            batteries.append(_decode_battery_status(r.read_bytes()))
        else:
            r.skip_field(wt)
    return GetXiteBatteriesStatusResponse(batteries=batteries)
