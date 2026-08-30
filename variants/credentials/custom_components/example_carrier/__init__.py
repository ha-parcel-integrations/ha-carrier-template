"""Example Carrier parcel tracker custom component for Home Assistant."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    ExampleCarrierApiClient,
    ExampleCarrierApiError,
    ExampleCarrierAuthError,
)
from .const import PLATFORMS
from .coordinator import ExampleCarrierCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass
class ExampleCarrierData:
    """Runtime data attached to an Example Carrier config entry."""

    client: ExampleCarrierApiClient
    coordinator: ExampleCarrierCoordinator
    account: dict[str, Any]
    session: aiohttp.ClientSession


type ExampleCarrierConfigEntry = ConfigEntry[ExampleCarrierData]


async def async_setup_entry(
    hass: HomeAssistant, entry: ExampleCarrierConfigEntry
) -> bool:
    """Set up Example Carrier from a config entry."""
    # Each config entry needs its own cookie jar, or two accounts overwrite
    # each other's auth cookies in the shared session. The connector is reused
    # (connector_owner=False) so this stays cheap.
    session = aiohttp.ClientSession(
        connector=async_get_clientsession(hass).connector,
        connector_owner=False,
        cookie_jar=aiohttp.CookieJar(),
    )
    client = ExampleCarrierApiClient(
        entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD], session
    )

    try:
        account = await client.async_login()
    except ExampleCarrierAuthError as err:
        # Credentials rejected — start reauth instead of retrying a password
        # that will never work again.
        await session.close()
        raise ConfigEntryAuthFailed("Example Carrier authentication failed") from err
    except (ExampleCarrierApiError, aiohttp.ClientError) as err:
        # Non-auth failure (typically a 5xx outage) — retry with backoff.
        await session.close()
        raise ConfigEntryNotReady("Example Carrier login failed") from err

    coordinator = ExampleCarrierCoordinator(hass, client, entry)

    try:
        # Fetch initial data here, before forwarding to platforms. Raising
        # ConfigEntryNotReady from a forwarded platform is too late for HA to
        # catch cleanly (it logs a warning and half-sets-up the entry); doing
        # the first refresh here lets a transient failure fail the whole entry
        # so HA retries it with backoff.
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        # Without this, every setup retry leaks a session.
        await session.close()
        raise

    entry.runtime_data = ExampleCarrierData(
        client=client, coordinator=coordinator, account=account, session=session
    )

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await session.close()
        raise

    # No entry.add_update_listener: the options flow calls
    # async_schedule_reload itself. Combining an update listener with a
    # reload-on-update flow is deprecated and becomes an error in HA 2026.12+.
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ExampleCarrierConfigEntry
) -> bool:
    """Unload an Example Carrier config entry."""
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.session.close()
        return True
    return False
