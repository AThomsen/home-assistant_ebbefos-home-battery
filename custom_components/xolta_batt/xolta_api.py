"""Xolta API client and authentication helpers."""

from __future__ import annotations

import asyncio
import logging
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
from .models import (
    GRANULARITY_HOURLY,
    GetCurrentXiteActualsResponse,
    GetXiteBatteriesStatusResponse,
    GetXitesResponse,
)
from .proto_codec import (
    decode_dashboard_response,
    decode_get_current_xite_actuals_response,
    decode_get_xite_batteries_status_response,
    decode_get_xites_response,
    encode_dashboard_request,
    encode_get_current_xite_actuals_request,
    encode_get_xite_batteries_status_request,
    encode_get_xites_request,
    grpc_web_frame,
    grpc_web_unframe,
    sum_xite_actuals,
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
        body = grpc_web_frame(proto_bytes)
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
                return grpc_web_unframe(raw)

        raise exceptions.ConfigEntryAuthFailed(_AuthErrorMessage)

    async def test_authentication(self) -> bool:
        """Test connectivity by fetching the list of xites."""
        proto = await self._grpc_post("GetXites", encode_get_xites_request())
        return len(decode_get_xites_response(proto).xites) > 0

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
            encode_get_current_xite_actuals_request(xite_id, granularity),
            service="xeam.atlas.Atlas",
        )
        return decode_get_current_xite_actuals_response(proto)

    async def get_xite_batteries_status(
        self, xite_id: int
    ) -> GetXiteBatteriesStatusResponse:
        """Fetch the battery status for all batteries in a given xite."""
        proto = await self._grpc_post(
            "GetXiteBatteriesStatus",
            encode_get_xite_batteries_status_request(xite_id),
            service="xeam.bacon.Bacon",
        )
        return decode_get_xite_batteries_status_response(proto)

    async def get_data(
        self, get_dashboard: bool = True, get_energy: bool = True
    ) -> dict:
        """Fetch dashboard data for all xites."""
        try:
            if self._data["xites"] is None:
                proto = await self._grpc_post("GetXites", encode_get_xites_request())
                self._data["xites"] = decode_get_xites_response(proto)
                _LOGGER.debug("Discovered xites: %s", self._data["xites"])

            for xite in self._data["xites"].xites:
                xite_id = xite.xite_id
                if get_dashboard:
                    proto = await self._grpc_post(
                        "Dashboard", encode_dashboard_request(xite_id)
                    )
                    self._data["dashboard"][xite_id] = decode_dashboard_response(proto)
                    _LOGGER.debug(
                        "Dashboard for xite %s: %s",
                        xite_id,
                        self._data["dashboard"][xite_id],
                    )

                if get_energy:
                    response = await self.get_current_xite_actuals(xite_id)
                    self._data["energy"][xite_id] = sum_xite_actuals(response.actuals)
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
        except Exception:
            _LOGGER.exception("Unable to fetch data from Xolta API")
            raise
