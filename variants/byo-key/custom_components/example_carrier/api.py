"""Example Carrier official tracking API client.

TODO(carrier): this whole module is carrier-specific — replace the request and
the response envelope handling with the real endpoint's behaviour. Keep the
*contract* the config flow and the coordinator rely on:

* ``async_validate_key`` raises :class:`ExampleCarrierAuthError` **only** when
  the key was rejected (401/403), and :class:`ExampleCarrierApiError` for
  every other non-success — a 5xx outage must never push users into a reauth
  flow they cannot complete,
* ``async_get_parcel`` returns the raw per-parcel dict on success,
* returns ``None`` when the carrier says the tracking code is unknown or not
  yet scanned (a normal, expected state — never an error),
* raises :class:`ExampleCarrierAuthError` when the key itself is rejected
  mid-poll (rotated or revoked outside Home Assistant) — distinct from a
  not-found code, and from every other :class:`ExampleCarrierApiError`, with
  ``status_code`` set on a non-2xx response and ``retry_after`` set when the
  carrier's own ``Retry-After`` header on a 429 could be parsed as seconds —
  the coordinator's backoff (Section 3 of the dynamic-polling plan) reads
  both,
* lets ``aiohttp.ClientError`` propagate untouched — ``DataUpdateCoordinator``
  already wraps those into ``UpdateFailed``.

Never log, cache in diagnostics, or otherwise surface the key itself — only
whether a call using it succeeded.
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import TRACKING_API_URL

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
    """Raised when Example Carrier rejects the API key.

    Distinct from :class:`ExampleCarrierApiError` on purpose: only this one may
    trigger Home Assistant's reauth flow — a key that stops working (rotated,
    revoked, quota-cancelled) needs a fresh one from the user, unlike a plain
    outage that should just be retried.
    """


class ExampleCarrierApiClient:
    """Client for the official Example Carrier developer tracking API.

    TODO(carrier): adjust the auth mechanics below to match the real API. Some
    official APIs take the key as a single header on every request (as
    modelled here); others are a two-legged OAuth client-credentials flow
    (POST the client_id/secret to a token endpoint, then use the returned
    bearer token) — if so, mint and cache the token here rather than in the
    coordinator or config flow, and re-mint it on a 401 before treating the
    key as rejected.
    """

    def __init__(self, api_key: str, session: aiohttp.ClientSession) -> None:
        """Initialise the client with the user's own API key and a session."""
        self._api_key = api_key
        self._session = session

    async def async_validate_key(self) -> None:
        """Perform the cheapest authenticated call to confirm the key works.

        Called once, from the config flow, before the entry is created — a
        rejected key must never reach ``async_setup_entry``. Raises
        :class:`ExampleCarrierAuthError` on 401/403 and
        :class:`ExampleCarrierApiError` on any other failure.

        TODO(carrier): point this at whatever the official API's cheapest
        authenticated call is (an account/quota endpoint, or a lookup against
        a documented test tracking number) — never spend a real tracking
        request just to validate the key if a cheaper one exists.
        """
        headers = {"Authorization": f"Bearer {self._api_key}"}
        url = TRACKING_API_URL.format(tracking_code="VALIDATE")
        async with self._session.get(url, headers=headers) as response:
            if response.status in (401, 403):
                raise ExampleCarrierAuthError(f"HTTP {response.status}")
            # A well-formed but nonexistent tracking code still proves the key
            # works — the endpoint gets far enough to say "not found".
            if response.status not in (200, 404):
                raise ExampleCarrierApiError(f"HTTP {response.status}")

    async def async_get_parcel(self, tracking_code: str) -> dict[str, Any] | None:
        """Fetch one parcel's tracking details.

        Returns the parcel dict for a known parcel, or ``None`` when the
        endpoint reports the code as unknown — which is also what a
        not-yet-scanned parcel gets. Raises :class:`ExampleCarrierAuthError` if
        the key itself is rejected; any other failure envelope or non-2xx
        status raises :class:`ExampleCarrierApiError`; network errors
        propagate as ``aiohttp.ClientError``.
        """
        url = TRACKING_API_URL.format(tracking_code=tracking_code)
        headers = {"Authorization": f"Bearer {self._api_key}"}
        async with self._session.get(url, headers=headers) as response:
            if response.status in (401, 403):
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

        if not isinstance(payload, dict):
            raise ExampleCarrierApiError("unexpected body (not a JSON object)")

        if payload.get("status") == "ok":
            parcel = payload.get("parcel")
            if not isinstance(parcel, dict):
                # A success envelope must carry a parcel; treat a hollow one as
                # unknown rather than crashing the whole poll.
                _LOGGER.warning(
                    "Example Carrier returned success without a parcel for %s",
                    tracking_code,
                )
                return None
            return parcel

        error = payload.get("error")
        if error == "not_found":
            return None
        raise ExampleCarrierApiError(str(error or "unknown error envelope"))
