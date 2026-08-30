"""Example Carrier account API client.

TODO(carrier): this whole module is carrier-specific — replace the requests and
the response handling with the real endpoints' behaviour. Keep the *contract*
setup and the coordinator rely on:

* ``async_login`` raises :class:`ExampleCarrierAuthError` **only** when the
  credentials were rejected (401/403), and :class:`ExampleCarrierApiError` for
  every other non-success — a 5xx outage must never push users into a reauth
  flow they cannot complete,
* ``async_get_parcels`` returns the account's parcels as a list of raw dicts,
* ``aiohttp.ClientError`` propagates untouched — ``DataUpdateCoordinator``
  already wraps it into ``UpdateFailed``.

The session is injected rather than created here, so the caller controls the
cookie jar (see ``__init__.py`` for why each entry needs its own).
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import LOGIN_URL, PARCELS_URL

_LOGGER = logging.getLogger(__name__)


class ExampleCarrierApiError(Exception):
    """Raised when an Example Carrier API call fails for a non-auth reason."""

    def __init__(
        self,
        detail: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        """Store the status code and the ``Retry-After`` header, if any."""
        super().__init__(f"Example Carrier API request failed: {detail}")
        self.detail = detail
        self.status_code = status_code
        self.retry_after = retry_after


class ExampleCarrierAuthError(ExampleCarrierApiError):
    """Raised when Example Carrier rejects the credentials.

    Distinct from :class:`ExampleCarrierApiError` on purpose: only this one may
    trigger Home Assistant's reauth flow.
    """


class ExampleCarrierApiClient:
    """Client for the Example Carrier consumer account API."""

    def __init__(
        self, email: str, password: str, session: aiohttp.ClientSession
    ) -> None:
        """Initialise the client with credentials and a session."""
        self._email = email
        self._password = password
        self._session = session

    async def async_login(self) -> dict[str, Any]:
        """Authenticate and return the account info.

        The session cookie set by this call authorises the later requests, so
        the caller's cookie jar is what keeps two accounts apart.
        """
        async with self._session.post(
            LOGIN_URL, json={"email": self._email, "password": self._password}
        ) as response:
            if response.status in (401, 403):
                raise ExampleCarrierAuthError(f"HTTP {response.status}")
            if response.status != 200:
                # Anything else (typically 5xx) is an outage, not bad
                # credentials — the caller retries with backoff.
                raise ExampleCarrierApiError(f"HTTP {response.status}")
            try:
                payload = await response.json(content_type=None)
            except ValueError as err:
                raise ExampleCarrierApiError(f"unparseable body ({err})") from err

        if not isinstance(payload, dict):
            raise ExampleCarrierApiError("unexpected body (not a JSON object)")
        return payload

    async def async_get_parcels(self) -> list[dict[str, Any]]:
        """Return the account's parcels as raw payload dicts."""
        async with self._session.get(PARCELS_URL) as response:
            if response.status in (401, 403):
                # The session expired mid-poll; the coordinator turns this into
                # a reauth via ConfigEntryAuthFailed.
                raise ExampleCarrierAuthError(f"HTTP {response.status}")
            if response.status == 429:
                retry_after_header = response.headers.get("Retry-After")
                try:
                    retry_after = float(retry_after_header) if retry_after_header else None
                except ValueError:
                    retry_after = None  # an HTTP-date, not seconds; let the caller's own backoff handle it
                raise ExampleCarrierApiError(
                    "HTTP 429", status_code=429, retry_after=retry_after
                )
            if response.status != 200:
                raise ExampleCarrierApiError(
                    f"HTTP {response.status}", status_code=response.status
                )
            try:
                payload = await response.json(content_type=None)
            except ValueError as err:
                raise ExampleCarrierApiError(f"unparseable body ({err})") from err

        parcels = payload.get("parcels") if isinstance(payload, dict) else payload
        if not isinstance(parcels, list):
            raise ExampleCarrierApiError("unexpected body (no parcel list)")
        return [parcel for parcel in parcels if isinstance(parcel, dict)]
