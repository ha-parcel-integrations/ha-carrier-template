"""Tests for the Example Carrier API client."""
import json
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.example_carrier.api import (
    ExampleCarrierApiClient,
    ExampleCarrierApiError,
)

CODE = "EXAMPLE123456"


def _session_returning(status: int, body: object = None) -> MagicMock:
    response = AsyncMock()
    response.status = status
    if isinstance(body, str):
        response.json = AsyncMock(side_effect=json.JSONDecodeError("x", body, 0))
    else:
        response.json = AsyncMock(return_value=body)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get = MagicMock(return_value=ctx)
    return session


async def test_get_parcel_returns_parcel_on_success():
    session = _session_returning(
        200, {"status": "ok", "parcel": {"trackingNumber": CODE}}
    )
    client = ExampleCarrierApiClient(session)

    parcel = await client.async_get_parcel(CODE)

    assert parcel["trackingNumber"] == CODE
    # the tracking code ends up in the URL
    assert CODE in session.get.call_args[0][0]


async def test_get_parcel_returns_none_when_not_found():
    """An unknown or not-yet-scanned code is a normal state, not an error."""
    client = ExampleCarrierApiClient(
        _session_returning(200, {"status": "error", "error": "not_found"})
    )
    assert await client.async_get_parcel("EXAMPLE000000") is None


async def test_get_parcel_returns_none_on_hollow_success():
    """A success envelope without a parcel is treated as unknown, not a crash."""
    client = ExampleCarrierApiClient(
        _session_returning(200, {"status": "ok", "parcel": None})
    )
    assert await client.async_get_parcel(CODE) is None


async def test_get_parcel_raises_on_error_status():
    client = ExampleCarrierApiClient(_session_returning(500, {}))
    with pytest.raises(ExampleCarrierApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_raises_on_unparseable_body():
    client = ExampleCarrierApiClient(_session_returning(200, "not json"))
    with pytest.raises(ExampleCarrierApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_raises_on_non_object_body():
    client = ExampleCarrierApiClient(_session_returning(200, ["not", "a", "dict"]))
    with pytest.raises(ExampleCarrierApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_raises_on_unknown_error_envelope():
    client = ExampleCarrierApiClient(
        _session_returning(200, {"status": "error", "error": "rate_limited"})
    )
    with pytest.raises(ExampleCarrierApiError) as err:
        await client.async_get_parcel(CODE)
    assert "rate_limited" in str(err.value)


async def test_get_parcel_raises_on_error_envelope_without_detail():
    client = ExampleCarrierApiClient(_session_returning(200, {"status": "error"}))
    with pytest.raises(ExampleCarrierApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_propagates_network_error():
    """ClientError is left alone — DataUpdateCoordinator already wraps it."""
    session = MagicMock()
    session.get = MagicMock(side_effect=aiohttp.ClientError("boom"))
    client = ExampleCarrierApiClient(session)
    with pytest.raises(aiohttp.ClientError):
        await client.async_get_parcel(CODE)
