"""Xolta API helpers and transport implementation."""

import asyncio
import logging
import struct
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING

import aiohttp
from homeassistant import exceptions

from .const import (
    XOLTA_OIDC_CLIENT_ID,
    XOLTA_OIDC_SCOPE,
    XOLTA_OIDC_TOKEN_ENDPOINT,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_ApiBaseURL = "https://api.xapp.ebbefos.dk"
_AppVersion = "1.2.8"
_RequestTimeout = aiohttp.ClientTimeout(total=20)
_AuthErrorMessage = "Bearer token expired or invalid"


@dataclass(slots=True)
class AuthState:
    """Persisted authorization state for the Xolta API."""

    access_token: str
    refresh_token: str | None = None
    token_expires_at: int | None = None


TokenUpdateCallback = Callable[[str, str | None, int | None], Awaitable[None]]


async def refresh_authorization_tokens(
    webclient: aiohttp.ClientSession,
    refresh_token: str,
) -> dict:
    """Refresh an access token using a refresh token."""
    body = aiohttp.FormData()
    body.add_field("grant_type", "refresh_token")
    body.add_field("client_id", XOLTA_OIDC_CLIENT_ID)
    body.add_field("refresh_token", refresh_token)
    body.add_field("scope", XOLTA_OIDC_SCOPE)

    async with webclient.post(
        XOLTA_OIDC_TOKEN_ENDPOINT,
        data=body,
        headers={"accept": "application/json"},
        timeout=_RequestTimeout,
    ) as response:
        response.raise_for_status()
        return await response.json()


# ---------------------------------------------------------------------------
# Protobuf / gRPC-Web helpers
# ---------------------------------------------------------------------------


def _encode_varint(value: int) -> bytes:
    """Encode an unsigned integer as a protobuf varint."""
    buf = []
    while value > 0x7F:
        buf.append((value & 0x7F) | 0x80)
        value >>= 7
    buf.append(value & 0x7F)
    return bytes(buf)


def _decode_varint(data: bytes, pos: int) -> tuple:
    """Decode a varint from data at pos. Returns (value, new_pos)."""
    result = 0
    shift = 0
    while pos < len(data):
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7
    raise ValueError("Truncated varint")


class _ProtoReader:
    """Minimal streaming protobuf reader."""

    def __init__(self, data: bytes, end: int | None = None) -> None:
        """Initialize the protobuf reader."""
        self._data = data
        self._pos = 0
        self._end = end if end is not None else len(data)

    @property
    def has_data(self) -> bool:
        return self._pos < self._end

    def read_tag(self) -> tuple:
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


def _grpc_web_frame(proto_bytes: bytes) -> bytes:
    """Wrap proto bytes in a gRPC-Web data frame (no compression)."""
    return b"\x00" + struct.pack(">I", len(proto_bytes)) + proto_bytes


def _grpc_web_unframe(data: bytes) -> bytes:
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


# ---------------------------------------------------------------------------
# Dataclasses for GetCurrentXiteActuals / GetHistoricXiteActuals responses
# ---------------------------------------------------------------------------


@dataclass
class XiteMinute:
    """Represents a point in time (local calendar time) for an xite actual."""

    year: int = 0
    month: int = 0
    day: int = 0
    hour: int = 0
    minute: int = 0


@dataclass
class EnergyFlow:
    """Directional energy flows within an xite actual (kWh)."""

    solar_to_battery_kwh: float = 0.0
    solar_to_grid_kwh: float = 0.0
    solar_to_consumption_kwh: float = 0.0
    battery_to_grid_kwh: float = 0.0
    battery_to_consumption_kwh: float = 0.0
    grid_to_battery_kwh: float = 0.0
    grid_to_consumption_kwh: float = 0.0


@dataclass
class MoneyFlow:
    """Directional money flows within an xite actual (currency units)."""

    solar_to_consumption_savings: float = 0.0
    battery_to_consumption_savings: float = 0.0
    solar_to_grid_earnings: float = 0.0
    battery_to_grid_earnings: float = 0.0
    grid_to_consumption_expense: float = 0.0
    grid_to_battery_expense: float = 0.0


@dataclass
class XiteActual:
    """A single data point from GetCurrentXiteActuals / GetHistoricXiteActuals."""

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


# Granularity enum values (xeam.common.Granularity from date.proto)
GRANULARITY_UNSPECIFIED = 0
GRANULARITY_QUARTER_HOURLY = 1
GRANULARITY_HOURLY = 2


def _encode_get_xites_request() -> bytes:
    return b""  # GetXitesRequest is empty


def _encode_get_xite_statistics_request(
    xite_id: int, year: int, month: int, day: int
) -> bytes:
    """Encode GetXiteStatisticsRequest for a single day (period from=to=given date)."""
    # XiteDate: field 1=year (varint), 2=month (varint), 3=day (varint)
    date_buf = b"\x08" + _encode_varint(year)
    date_buf += b"\x10" + _encode_varint(month)
    date_buf += b"\x18" + _encode_varint(day)
    # XitePeriod: field 1=from (message), 2=to (message)
    period_buf = b"\x0a" + _encode_varint(len(date_buf)) + date_buf
    period_buf += b"\x12" + _encode_varint(len(date_buf)) + date_buf
    # GetXiteStatisticsRequest: field 1=xiteId (varint), 2=period (message)
    buf = b"\x08" + _encode_varint(xite_id)
    buf += b"\x12" + _encode_varint(len(period_buf)) + period_buf
    return buf


def _encode_dashboard_request(xite_id: int) -> bytes:
    # Field 1 (xiteId), wire type 0 (varint), tag = 0x08
    return b"\x08" + _encode_varint(xite_id)


# ---------------------------------------------------------------------------
# Response decoders
# ---------------------------------------------------------------------------


def _decode_get_xite_statistics_response(data: bytes) -> dict:
    """Decode GetXiteStatisticsResponse into today's energy totals (kWh)."""
    r = _ProtoReader(data)
    result = {
        "pv": 0.0,
        "battery_charged": 0.0,
        "battery_discharged": 0.0,
        "grid_export": 0.0,
        "grid_import": 0.0,
        "consumption": 0.0,
    }
    while r.has_data:
        field, wt = r.read_tag()
        if wt == 1:  # wire type 1 = 64-bit (double)
            value = r.read_double()
            if field == 4:
                result["pv"] = value  # solarProductionKwh
            elif field == 5:
                result["battery_charged"] = value  # batteryChargedKwh
            elif field == 6:
                result["grid_export"] = value  # gridExportKwh
            elif field == 8:
                result["battery_discharged"] = value  # batteryConsumptionKwh
            elif field == 10:
                result["consumption"] = value  # totalConsumptionKwh
            elif field == 12:
                result["grid_import"] = value  # gridImportKwh
        elif wt == 2:
            r.read_bytes()  # skip embedded messages
        else:
            r.skip_field(wt)
    return result


def _decode_get_xites_response(data: bytes) -> list:
    """Return list of xiteIds (int) from GetXitesResponse."""
    xite_ids = []
    r = _ProtoReader(data)
    while r.has_data:
        field, wt = r.read_tag()
        if field == 1 and wt == 2:  # xites (repeated Xite message)
            xite_bytes = r.read_bytes()
            xr = _ProtoReader(xite_bytes)
            while xr.has_data:
                f, w = xr.read_tag()
                if f == 1 and w == 0:  # xiteId (int64 varint)
                    xite_ids.append(xr.read_varint())
                else:
                    xr.skip_field(w)
        else:
            r.skip_field(wt)
    return xite_ids


def _encode_get_current_xite_actuals_request(
    xite_id: int, granularity: int = GRANULARITY_HOURLY
) -> bytes:
    """Encode GetCurrentXiteActualsRequest (field 1: xiteId varint, field 2: granularity varint)."""
    buf = b"\x08" + _encode_varint(xite_id)
    if granularity != 0:
        buf += b"\x10" + _encode_varint(granularity)
    return buf


def _decode_xite_minute(data: bytes) -> XiteMinute:
    """Decode a XiteMinute message."""
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


_MONEY_FLOW_DOUBLE_FIELDS: dict[int, str] = {
    1: "solar_to_consumption_savings",
    2: "battery_to_consumption_savings",
    3: "solar_to_grid_earnings",
    4: "battery_to_grid_earnings",
    5: "grid_to_consumption_expense",
    6: "grid_to_battery_expense",
}


def _decode_money_flow(data: bytes) -> MoneyFlow:
    """Decode a MoneyFlow message (all fields are wire-type-1 doubles)."""
    r = _ProtoReader(data)
    mf = MoneyFlow()
    while r.has_data:
        field, wt = r.read_tag()
        if wt == 1:
            val = r.read_double()
            attr = _MONEY_FLOW_DOUBLE_FIELDS.get(field)
            if attr is not None:
                setattr(mf, attr, val)
        else:
            r.skip_field(wt)
    return mf


def _decode_energy_flow(data: bytes) -> EnergyFlow:
    """Decode an EnergyFlow message (all fields are wire-type-1 doubles)."""
    r = _ProtoReader(data)
    ef = EnergyFlow()
    while r.has_data:
        field, wt = r.read_tag()
        if wt == 1:
            val = r.read_double()
            if field == 1:
                ef.solar_to_battery_kwh = val
            elif field == 2:
                ef.solar_to_grid_kwh = val
            elif field == 3:
                ef.solar_to_consumption_kwh = val
            elif field == 4:
                ef.battery_to_grid_kwh = val
            elif field == 5:
                ef.battery_to_consumption_kwh = val
            elif field == 6:
                ef.grid_to_battery_kwh = val
            elif field == 7:
                ef.grid_to_consumption_kwh = val
        else:
            r.skip_field(wt)
    return ef


_XITE_ACTUAL_DOUBLE_FIELDS: dict[int, str] = {
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
    """Decode a single XiteActual message."""
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
            val = r.read_double()
            attr = _XITE_ACTUAL_DOUBLE_FIELDS.get(field)
            if attr is not None:
                setattr(a, attr, val)
        else:
            r.skip_field(wt)
    return a


def _sum_xite_actuals(actuals: list[XiteActual]) -> dict:
    """Sum per-interval XiteActual records into daily energy totals (kWh)."""
    result = {
        "pv": 0.0,
        "battery_charged": 0.0,
        "battery_discharged": 0.0,
        "grid_export": 0.0,
        "grid_import": 0.0,
        "consumption": 0.0,
    }
    for a in actuals:
        result["pv"] += a.solar_production_kwh
        result["grid_import"] += a.grid_import_kwh
        result["grid_export"] += a.grid_export_kwh
        result["consumption"] += a.consumption_kwh
        if a.energy_flow is not None:
            ef = a.energy_flow
            result["battery_charged"] += (
                ef.solar_to_battery_kwh + ef.grid_to_battery_kwh
            )
            result["battery_discharged"] += (
                ef.battery_to_grid_kwh + ef.battery_to_consumption_kwh
            )
    return result


def _decode_get_current_xite_actuals_response(
    data: bytes,
) -> GetCurrentXiteActualsResponse:
    """Decode GetCurrentXiteActualsResponse → list of XiteActual dataclasses."""
    r = _ProtoReader(data)
    actuals: list[XiteActual] = []
    while r.has_data:
        field, wt = r.read_tag()
        if field == 1 and wt == 2:
            actuals.append(_decode_xite_actual(r.read_bytes()))
        else:
            r.skip_field(wt)
    return GetCurrentXiteActualsResponse(actuals=actuals)


def _decode_battery_telemetry(data: bytes) -> dict:
    r = _ProtoReader(data)
    result = {"soc": 0.0, "kw": 0.0}
    while r.has_data:
        field, wt = r.read_tag()
        if field == 1 and wt == 1:  # stateOfCharge (double, 0..1)
            result["soc"] = r.read_double()
        elif field == 2 and wt == 1:  # chargingKw → negative convention
            result["kw"] = -r.read_double()
        elif field == 3 and wt == 1:  # dischargingKw → positive convention
            result["kw"] = r.read_double()
        elif field == 4 and wt == 2:  # idle (empty message)
            r.read_bytes()
        else:
            r.skip_field(wt)
    return result


def _decode_grid_telemetry(data: bytes) -> dict:
    r = _ProtoReader(data)
    result = {"kw": 0.0}
    while r.has_data:
        field, wt = r.read_tag()
        if field == 1 and wt == 1:  # importingKw → positive
            result["kw"] = r.read_double()
        elif field == 2 and wt == 1:  # exportingKw → negative
            result["kw"] = -r.read_double()
        else:
            r.skip_field(wt)
    return result


def _decode_solar_telemetry(data: bytes) -> dict:
    r = _ProtoReader(data)
    result = {"kw": 0.0}
    while r.has_data:
        field, wt = r.read_tag()
        if field == 1 and wt == 1:  # productionKw
            result["kw"] = r.read_double()
        else:
            r.skip_field(wt)
    return result


def _decode_dashboard_response(data: bytes) -> dict:
    r = _ProtoReader(data)
    result = {
        "battery_kw": 0.0,
        "battery_soc_pct": 0.0,
        "solar_kw": 0.0,
        "grid_kw": 0.0,
        "consumption_kw": 0.0,
        "buy_price_kwh": 0.0,
        "sell_price_kwh": 0.0,
        "air_temperature": 0.0,
    }
    while r.has_data:
        field, wt = r.read_tag()
        if field == 1 and wt == 2:  # battery (message)
            bat = _decode_battery_telemetry(r.read_bytes())
            result["battery_kw"] = bat["kw"]
            result["battery_soc_pct"] = round(bat["soc"] * 100, 1)
        elif field == 2 and wt == 2:  # grid (message)
            result["grid_kw"] = _decode_grid_telemetry(r.read_bytes())["kw"]
        elif field == 3 and wt == 2:  # solar (message)
            result["solar_kw"] = _decode_solar_telemetry(r.read_bytes())["kw"]
        elif field == 4 and wt == 1:  # consumptionKw (double)
            result["consumption_kw"] = r.read_double()
        elif field == 5 and wt == 1:  # buyPricePerKwh
            result["buy_price_kwh"] = r.read_double()
        elif field == 6 and wt == 1:  # sellPricePerKwh
            result["sell_price_kwh"] = r.read_double()
        elif field == 7 and wt == 1:  # airTemperature
            result["air_temperature"] = r.read_double()
        elif field == 8 and wt == 0:  # weatherSymbol (discard)
            r.read_varint()
        else:
            r.skip_field(wt)
    return result


class XoltaApi:
    """Interface to the Xolta/Ebbefos gRPC-Web API."""

    def __init__(
        self,
        hass: HomeAssistant,
        webclient: aiohttp.ClientSession,
        auth_state: AuthState | None = None,
        async_update_tokens: TokenUpdateCallback | None = None,
    ) -> None:
        """Initialize the API client and optional token refresh state."""
        self._hass = hass
        self._webclient = webclient
        self._bearer_token = auth_state.access_token if auth_state else ""
        self._refresh_token = auth_state.refresh_token if auth_state else None
        self._token_expires_at = auth_state.token_expires_at if auth_state else None
        self._async_update_tokens = async_update_tokens
        self._token_refresh_lock = asyncio.Lock()
        self._data = {"xites": None, "dashboard": {}, "energy": {}}

    async def _persist_tokens(self) -> None:
        """Persist newly refreshed tokens if a callback was provided."""
        if self._async_update_tokens is None:
            return

        await self._async_update_tokens(
            self._bearer_token,
            self._refresh_token,
            self._token_expires_at,
        )

    async def _refresh_bearer_token(self, force: bool = False) -> None:
        """Refresh the access token. Safe to call concurrently.

        Uses a lock to prevent concurrent refreshes from racing on a rotating
        refresh token.  When ``force`` is False (proactive refresh), a re-check
        under the lock skips the network call if another coroutine already
        refreshed while this one was waiting.
        """
        async with self._token_refresh_lock:
            if not self._refresh_token:
                raise exceptions.ConfigEntryAuthFailed(_AuthErrorMessage)

            # Re-check under lock: skip if a concurrent call already refreshed.
            if (
                not force
                and self._token_expires_at
                and time.time() < self._token_expires_at - 60
            ):
                return

            token_data = await refresh_authorization_tokens(
                self._webclient,
                self._refresh_token,
            )

            self._bearer_token = token_data["access_token"]
            self._refresh_token = token_data.get("refresh_token", self._refresh_token)

            expires_in = token_data.get("expires_in")
            if expires_in is not None:
                self._token_expires_at = int(time.time()) + int(expires_in)

            await self._persist_tokens()

    async def _ensure_valid_bearer_token(self) -> None:
        """Refresh the token before it expires when possible."""
        if self._refresh_token is None or self._token_expires_at is None:
            return

        if time.time() >= self._token_expires_at - 60:
            await self._refresh_bearer_token()

    @property
    def auth_state(self) -> AuthState:
        """Return the current in-memory authorization state."""
        return AuthState(
            access_token=self._bearer_token,
            refresh_token=self._refresh_token,
            token_expires_at=self._token_expires_at,
        )

    def _headers(self) -> dict:
        return {
            "authorization": f"Bearer {self._bearer_token}",
            "content-type": "application/grpc-web+proto",
            "x-grpc-web": "1",
            "x-app-client": "web",
            "x-app-version": _AppVersion,
            "accept": "application/grpc-web+proto",
        }

    async def _grpc_post(
        self, method: str, proto_bytes: bytes, service: str = "xeam.xapp.Xapp"
    ) -> bytes:
        """POST a gRPC-Web request and return the decoded proto response bytes."""
        url = f"{_ApiBaseURL}/{service}/{method}"
        body = _grpc_web_frame(proto_bytes)
        for attempt in range(2):
            await self._ensure_valid_bearer_token()

            async with self._webclient.post(
                url,
                data=body,
                headers=self._headers(),
                timeout=_RequestTimeout,
            ) as response:
                if response.status == HTTPStatus.UNAUTHORIZED and attempt == 0:
                    await self._refresh_bearer_token(force=True)
                    continue

                response.raise_for_status()
                raw = await response.read()
                return _grpc_web_unframe(raw)

        raise exceptions.ConfigEntryAuthFailed(_AuthErrorMessage)

    async def test_authentication(self) -> bool:
        """Test connectivity by fetching the list of xites."""
        proto = await self._grpc_post("GetXites", _encode_get_xites_request())
        xite_ids = _decode_get_xites_response(proto)
        return len(xite_ids) > 0

    async def get_current_xite_actuals(
        self,
        xite_id: int,
        granularity: int = GRANULARITY_HOURLY,
    ) -> GetCurrentXiteActualsResponse:
        """Fetch current actuals for a single xite (for ad-hoc testing / inspection).

        ``granularity``: GRANULARITY_UNSPECIFIED (0), GRANULARITY_QUARTER_HOURLY (1),
        GRANULARITY_HOURLY (2).
        """
        proto = await self._grpc_post(
            "GetCurrentXiteActuals",
            _encode_get_current_xite_actuals_request(xite_id, granularity),
            service="xeam.atlas.Atlas",
        )
        return _decode_get_current_xite_actuals_response(proto)

    async def get_data(
        self, get_dashboard: bool = True, get_energy: bool = True
    ) -> dict:
        """Fetch dashboard data for all xites."""
        try:
            if self._data["xites"] is None:
                proto = await self._grpc_post("GetXites", _encode_get_xites_request())
                self._data["xites"] = _decode_get_xites_response(proto)
                _LOGGER.debug("Discovered xiteIds: %s", self._data["xites"])

            for xite_id in self._data["xites"]:
                if get_dashboard:
                    proto = await self._grpc_post(
                        "Dashboard", _encode_dashboard_request(xite_id)
                    )
                    self._data["dashboard"][xite_id] = _decode_dashboard_response(proto)
                    _LOGGER.debug(
                        "Dashboard for xite %s: %s",
                        xite_id,
                        self._data["dashboard"][xite_id],
                    )

                if get_energy:
                    response = await self.get_current_xite_actuals(xite_id)
                    self._data["energy"][xite_id] = _sum_xite_actuals(response.actuals)
                    _LOGGER.debug(
                        "Energy (current actuals) for xite %s: %s",
                        xite_id,
                        self._data["energy"][xite_id],
                    )

            return self._data

        except aiohttp.ClientResponseError as err:
            if err.status == HTTPStatus.UNAUTHORIZED:
                raise exceptions.ConfigEntryAuthFailed(_AuthErrorMessage) from err
            _LOGGER.exception("HTTP error fetching data from Xolta API")
            raise
        except Exception as exception:
            _LOGGER.exception("Unable to fetch data from Xolta API")
            raise
