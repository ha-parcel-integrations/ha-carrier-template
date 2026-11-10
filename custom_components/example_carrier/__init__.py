"""Example Carrier parcel tracker custom component for Home Assistant."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ExampleCarrierApiClient
from .const import PLATFORMS
from .coordinator import ExampleCarrierCoordinator
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)


@dataclass
class ExampleCarrierData:
    """Runtime data attached to the Example Carrier config entry."""

    client: ExampleCarrierApiClient
    coordinator: ExampleCarrierCoordinator
    # The options as last applied, so an entry write that changed no option
    # is not mistaken for an options edit — see _async_options_updated.
    options: Mapping[str, object] = field(default_factory=dict)


type ExampleCarrierConfigEntry = ConfigEntry[ExampleCarrierData]


async def async_setup_entry(
    hass: HomeAssistant, entry: ExampleCarrierConfigEntry
) -> bool:
    """Set up Example Carrier from a config entry."""
    # No auth: Example Carrier tracking is public, so the HA-managed session is fine.
    client = ExampleCarrierApiClient(async_get_clientsession(hass))
    coordinator = ExampleCarrierCoordinator(hass, client, entry)

    # Fetch initial data here, before forwarding to platforms. Raising
    # ConfigEntryNotReady from a forwarded platform is too late for HA to catch
    # cleanly (it logs a warning and half-sets-up the entry); doing the first
    # refresh here lets a transient failure fail the whole entry so HA retries
    # it with backoff.
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = ExampleCarrierData(
        client=client, coordinator=coordinator, options=dict(entry.options)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Apply option changes (added/removed parcels, history) live via a
    # coordinator refresh — no reload — so per-parcel sensors appear and
    # disappear immediately. The update listener does NOT reload, so it does
    # not trip the config-entry-listener deprecation. This is also the resume
    # path after polling fully suspended (Section 2.1): adding a parcel back
    # triggers this refresh, which recomputes the tier and re-arms scheduling.
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    async_setup_services(hass)

    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: ExampleCarrierConfigEntry
) -> None:
    """Apply changed options by refreshing the coordinator.

    Home Assistant notifies an update listener on *every* ``async_update_entry``,
    not just an options edit, so the options are compared first. A carrier whose
    coordinator persists something onto the entry (a rotated token, a learned
    identifier) would otherwise poll on that write's cadence — and
    ``async_request_refresh`` goes straight past the "Enable polling for
    updates" system option, which only gates the *scheduled* refresh.
    """
    data = entry.runtime_data
    if entry.options == data.options:
        return
    data.options = dict(entry.options)
    await data.coordinator.async_request_refresh()


async def async_unload_entry(
    hass: HomeAssistant, entry: ExampleCarrierConfigEntry
) -> bool:
    """Unload the Example Carrier config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    # Single-instance integration (single_config_entry), so the services can
    # always go when the entry unloads.
    async_unload_services(hass)
    return True
