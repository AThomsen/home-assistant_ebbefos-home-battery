import struct
import logging
import aiohttp
from homeassistant import exceptions
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_ApiBaseURL = "https://api.xapp.ebbefos.dk"
_AppVersion = "1.2.8"
_RequestTimeout = aiohttp.ClientTimeout(total=20)


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

    def __init__(self, data: bytes, end: int = None):
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
        val = struct.unpack_from('<d', self._data, self._pos)[0]
        self._pos += 8
        return val

    def read_bytes(self) -> bytes:
        length = self._read_varint_raw()
        data = self._data[self._pos:self._pos + length]
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
    return b'\x00' + struct.pack('>I', len(proto_bytes)) + proto_bytes


def _grpc_web_unframe(data: bytes) -> bytes:
    """Extract the first data frame's proto bytes from a gRPC-Web response."""
    pos = 0
    while pos + 5 <= len(data):
        frame_type = data[pos]
        length = struct.unpack('>I', data[pos + 1:pos + 5])[0]
        pos += 5
        if frame_type == 0x00:  # data frame
            return data[pos:pos + length]
        pos += length  # skip trailers (0x80) etc.
    return b''


# ---------------------------------------------------------------------------
# Request encoders
# ---------------------------------------------------------------------------

def _encode_get_xites_request() -> bytes:
    return b''  # GetXitesRequest is empty


def _encode_dashboard_request(xite_id: int) -> bytes:
    # Field 1 (xiteId), wire type 0 (varint), tag = 0x08
    return b'\x08' + _encode_varint(xite_id)


# ---------------------------------------------------------------------------
# Response decoders
# ---------------------------------------------------------------------------

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


def _decode_battery_telemetry(data: bytes) -> dict:
    r = _ProtoReader(data)
    result = {"soc": 0.0, "kw": 0.0}
    while r.has_data:
        field, wt = r.read_tag()
        if field == 1 and wt == 1:      # stateOfCharge (double, 0..1)
            result["soc"] = r.read_double()
        elif field == 2 and wt == 1:    # chargingKw → negative convention
            result["kw"] = -r.read_double()
        elif field == 3 and wt == 1:    # dischargingKw → positive convention
            result["kw"] = r.read_double()
        elif field == 4 and wt == 2:    # idle (empty message)
            r.read_bytes()
        else:
            r.skip_field(wt)
    return result


def _decode_grid_telemetry(data: bytes) -> dict:
    r = _ProtoReader(data)
    result = {"kw": 0.0}
    while r.has_data:
        field, wt = r.read_tag()
        if field == 1 and wt == 1:    # importingKw → positive
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
        if field == 1 and wt == 2:    # battery (message)
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
        bearer_token: str,
    ):
        self._hass = hass
        self._webclient = webclient
        self._bearer_token = bearer_token
        self._data = {"xites": None, "dashboard": {}}

    def _headers(self) -> dict:
        return {
            "authorization": f"Bearer {self._bearer_token}",
            "content-type": "application/grpc-web+proto",
            "x-grpc-web": "1",
            "x-app-client": "web",
            "x-app-version": _AppVersion,
            "accept": "application/grpc-web+proto",
        }

    async def _grpc_post(self, method: str, proto_bytes: bytes) -> bytes:
        """POST a gRPC-Web request and return the decoded proto response bytes."""
        url = f"{_ApiBaseURL}/xeam.xapp.Xapp/{method}"
        body = _grpc_web_frame(proto_bytes)
        async with self._webclient.post(
            url,
            data=body,
            headers=self._headers(),
            timeout=_RequestTimeout,
        ) as response:
            response.raise_for_status()
            raw = await response.read()
        return _grpc_web_unframe(raw)

    async def test_authentication(self) -> bool:
        """Test connectivity by fetching the list of xites."""
        proto = await self._grpc_post("GetXites", _encode_get_xites_request())
        xite_ids = _decode_get_xites_response(proto)
        return len(xite_ids) > 0

    async def get_data(self) -> dict:
        """Fetch dashboard data for all xites."""
        try:
            if self._data["xites"] is None:
                proto = await self._grpc_post("GetXites", _encode_get_xites_request())
                self._data["xites"] = _decode_get_xites_response(proto)
                _LOGGER.debug("Discovered xiteIds: %s", self._data["xites"])

            for xite_id in self._data["xites"]:
                proto = await self._grpc_post(
                    "Dashboard", _encode_dashboard_request(xite_id)
                )
                self._data["dashboard"][xite_id] = _decode_dashboard_response(proto)
                _LOGGER.debug(
                    "Dashboard for xite %s: %s", xite_id, self._data["dashboard"][xite_id]
                )

            return self._data

        except aiohttp.ClientResponseError as err:
            if err.status == 401:
                raise exceptions.ConfigEntryAuthFailed(
                    "Bearer token expired or invalid"
                ) from err
            _LOGGER.error("HTTP error fetching data from Xolta API: %s", err)
            raise
        except Exception as exception:
            _LOGGER.error("Unable to fetch data from Xolta API: %s", exception)
            raise

