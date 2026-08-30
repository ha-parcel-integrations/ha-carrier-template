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

from .payloads import active_sample

EMAIL = "user@example.test"
PASSWORD = "hunter2"


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
    session.post = MagicMock(return_value=ctx)
    return session


def _client(session: MagicMock) -> ExampleCarrierApiClient:
    return ExampleCarrierApiClient(EMAIL, PASSWORD, session)


# ---------------------------------------------------------------------------
# login — the auth/outage split is the important part
# ---------------------------------------------------------------------------


async def test_login_returns_account_info():
    session = _session_returning(200, {"accountId": "abc"})
    assert await _client(session).async_login() == {"accountId": "abc"}
    assert session.post.call_args[1]["json"]["email"] == EMAIL


@pytest.mark.parametrize("status", [401, 403])
async def test_login_raises_auth_error_on_rejected_credentials(status):
    with pytest.raises(ExampleCarrierAuthError):
        await _client(_session_returning(status, {})).async_login()


@pytest.mark.parametrize("status", [500, 502, 429])
async def test_login_raises_api_error_on_outage(status):
    """A 5xx must not look like bad credentials, or users get pushed into a
    reauth flow they cannot complete."""
    with pytest.raises(ExampleCarrierApiError) as err:
        await _client(_session_returning(status, {})).async_login()
    assert not isinstance(err.value, ExampleCarrierAuthError)


async def test_login_raises_on_unparseable_body():
    with pytest.raises(ExampleCarrierApiError):
        await _client(_session_returning(200, "not json")).async_login()


async def test_login_raises_on_non_object_body():
    with pytest.raises(ExampleCarrierApiError):
        await _client(_session_returning(200, ["nope"])).async_login()


async def test_login_propagates_network_error():
    session = MagicMock()
    session.post = MagicMock(side_effect=aiohttp.ClientError("boom"))
    with pytest.raises(aiohttp.ClientError):
        await _client(session).async_login()


# ---------------------------------------------------------------------------
# parcel list
# ---------------------------------------------------------------------------


async def test_get_parcels_returns_list():
    session = _session_returning(200, {"parcels": [active_sample()]})
    parcels = await _client(session).async_get_parcels()
    assert len(parcels) == 1
    assert parcels[0]["trackingNumber"] == active_sample()["trackingNumber"]


async def test_get_parcels_accepts_a_bare_list():
    session = _session_returning(200, [active_sample()])
    assert len(await _client(session).async_get_parcels()) == 1


async def test_get_parcels_skips_non_dict_entries():
    session = _session_returning(200, {"parcels": [active_sample(), "junk"]})
    assert len(await _client(session).async_get_parcels()) == 1


async def test_get_parcels_raises_auth_error_on_expired_session():
    with pytest.raises(ExampleCarrierAuthError):
        await _client(_session_returning(401, {})).async_get_parcels()


async def test_get_parcels_raises_on_error_status():
    with pytest.raises(ExampleCarrierApiError):
        await _client(_session_returning(503, {})).async_get_parcels()


async def test_get_parcels_raises_on_unparseable_body():
    with pytest.raises(ExampleCarrierApiError):
        await _client(_session_returning(200, "not json")).async_get_parcels()


async def test_get_parcels_raises_without_a_list():
    with pytest.raises(ExampleCarrierApiError):
        await _client(_session_returning(200, {"parcels": "nope"})).async_get_parcels()
