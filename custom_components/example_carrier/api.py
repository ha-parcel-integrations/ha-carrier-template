"""Example Carrier public tracking API client.

TODO(carrier): this whole module is carrier-specific — replace the request and
the response envelope handling with the real endpoint's behaviour. Keep the
*contract* the coordinator relies on:

* ``async_get_parcel`` returns the raw per-parcel dict on success,
* returns ``None`` when the carrier says the tracking code is unknown or not
  yet scanned (a normal, expected state — never an error),
* raises :class:`ExampleCarrierApiError` for anything else, with
  ``status_code`` set on a non-2xx response and ``retry_after`` set when the
  carrier's own ``Retry-After`` header on a 429 could be parsed as seconds —
  the coordinator's backoff (Section 3 of the dynamic-polling plan) reads
  both,
* lets ``aiohttp.ClientError`` propagate untouched — ``DataUpdateCoordinator``
  already wraps those into ``UpdateFailed``.
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import TRACKING_API_URL

_LOGGER = logging.getLogger(__name__)


class ExampleCarrierApiError(Exception):
    """Raised when an Example Carrier API call returns an unexpected response."""

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


class ExampleCarrierApiClient:
    """Client for the public Example Carrier tracking endpoint.

    No authentication: the endpoint is keyed on the tracking code alone. It
    answers HTTP 200 with a JSON envelope::

        {"status": "ok",    "parcel": {...}}
        {"status": "error", "error": "not_found"}
    """

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialise the client with an aiohttp session."""
        self._session = session

    async def async_get_parcel(self, tracking_code: str) -> dict[str, Any] | None:
        """Fetch one parcel's tracking details.

        Returns the parcel dict for a known parcel, or ``None`` when the
        endpoint reports the code as unknown — which is also what a
        not-yet-scanned parcel gets. Any other failure envelope or non-2xx
        status raises :class:`ExampleCarrierApiError`; network errors propagate
        as ``aiohttp.ClientError``.
        """
        url = TRACKING_API_URL.format(tracking_code=tracking_code)
        async with self._session.get(url) as response:
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
                # content_type=None: consumer endpoints routinely serve JSON as
                # text/plain, and aiohttp would otherwise refuse to parse it.
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
