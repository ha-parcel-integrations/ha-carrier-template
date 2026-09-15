"""Tests for the Example Carrier API client."""
import json
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.example_carrier.api import (
    ExampleCarrierApiClient,
    ExampleCarrierApiError,
    ExampleCarrierAuthError,
)

CODE = "EXAMPLE123456"
API_KEY = "test-api-key"


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


async def test_validate_key_succeeds_on_200():
    client = ExampleCarrierApiClient(API_KEY, _session_returning(200, {}))
    await client.async_validate_key()  # does not raise


async def test_validate_key_succeeds_on_404():
    """A well-formed nonexistent code still proves the key works."""
    client = ExampleCarrierApiClient(API_KEY, _session_returning(404, {}))
    await client.async_validate_key()  # does not raise


async def test_validate_key_raises_auth_error_on_401():
    client = ExampleCarrierApiClient(API_KEY, _session_returning(401, {}))
    with pytest.raises(ExampleCarrierAuthError):
        await client.async_validate_key()


async def test_validate_key_raises_auth_error_on_403():
    client = ExampleCarrierApiClient(API_KEY, _session_returning(403, {}))
    with pytest.raises(ExampleCarrierAuthError):
        await client.async_validate_key()


async def test_validate_key_raises_api_error_on_outage():
    """A 5xx must not surface as invalid_auth -- it's an outage, not a bad key."""
    client = ExampleCarrierApiClient(API_KEY, _session_returning(500, {}))
    with pytest.raises(ExampleCarrierApiError) as err:
        await client.async_validate_key()
    assert not isinstance(err.value, ExampleCarrierAuthError)


async def test_get_parcel_returns_parcel_on_success():
    session = _session_returning(
        200, {"status": "ok", "parcel": {"trackingNumber": CODE}}
    )
    client = ExampleCarrierApiClient(API_KEY, session)

    parcel = await client.async_get_parcel(CODE)

    assert parcel["trackingNumber"] == CODE
    # the tracking code ends up in the URL
    assert CODE in session.get.call_args[0][0]
    # the key is sent as a bearer header, never as a query parameter
    assert API_KEY not in session.get.call_args[0][0]
    assert session.get.call_args.kwargs["headers"]["Authorization"] == f"Bearer {API_KEY}"


async def test_get_parcel_returns_none_when_not_found():
    """An unknown or not-yet-scanned code is a normal state, not an error."""
    client = ExampleCarrierApiClient(
        API_KEY, _session_returning(200, {"status": "error", "error": "not_found"})
    )
    assert await client.async_get_parcel("EXAMPLE000000") is None


async def test_get_parcel_returns_none_on_hollow_success():
    """A success envelope without a parcel is treated as unknown, not a crash."""
    client = ExampleCarrierApiClient(
        API_KEY, _session_returning(200, {"status": "ok", "parcel": None})
    )
    assert await client.async_get_parcel(CODE) is None


async def test_get_parcel_raises_auth_error_when_key_rejected():
    """A key rotated or revoked outside HA must be distinguishable from a 5xx."""
    client = ExampleCarrierApiClient(API_KEY, _session_returning(401, {}))
    with pytest.raises(ExampleCarrierAuthError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_raises_on_error_status():
    client = ExampleCarrierApiClient(API_KEY, _session_returning(500, {}))
    with pytest.raises(ExampleCarrierApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_raises_on_unparseable_body():
    client = ExampleCarrierApiClient(API_KEY, _session_returning(200, "not json"))
    with pytest.raises(ExampleCarrierApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_raises_on_non_object_body():
    client = ExampleCarrierApiClient(
        API_KEY, _session_returning(200, ["not", "a", "dict"])
    )
    with pytest.raises(ExampleCarrierApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_raises_on_unknown_error_envelope():
    client = ExampleCarrierApiClient(
        API_KEY, _session_returning(200, {"status": "error", "error": "rate_limited"})
    )
    with pytest.raises(ExampleCarrierApiError) as err:
        await client.async_get_parcel(CODE)
    assert "rate_limited" in str(err.value)


async def test_get_parcel_raises_on_error_envelope_without_detail():
    client = ExampleCarrierApiClient(API_KEY, _session_returning(200, {"status": "error"}))
    with pytest.raises(ExampleCarrierApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_propagates_network_error():
    """ClientError is left alone — DataUpdateCoordinator already wraps it."""
    session = MagicMock()
    session.get = MagicMock(side_effect=aiohttp.ClientError("boom"))
    client = ExampleCarrierApiClient(API_KEY, session)
    with pytest.raises(aiohttp.ClientError):
        await client.async_get_parcel(CODE)
