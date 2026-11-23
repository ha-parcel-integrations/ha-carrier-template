"""Tests for Example Carrier sensor property logic."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from custom_components.example_carrier.const import ParcelStatus
from custom_components.example_carrier.sensor import (
    ExampleCarrierAwaitingPickupSensor,
    ExampleCarrierDeliveredParcelsSensor,
    ExampleCarrierEnRouteToPickupPointSensor,
    ExampleCarrierIncomingParcelsSensor,
    ExampleCarrierLastUpdateSensor,
    ExampleCarrierNextDeliverySensor,
    ExampleCarrierParcelSensor,
)


def _entry(entry_id: str = "e1") -> MagicMock:
    entry = MagicMock()
    entry.entry_id = entry_id
    return entry


def _coordinator(data: list[dict], delivered: list[dict] | None = None) -> MagicMock:
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.delivered = delivered if delivered is not None else []
    return coordinator


def _parcel(
    barcode: str,
    status: ParcelStatus = ParcelStatus.IN_TRANSIT,
    pickup: bool = False,
    planned_from: str | None = None,
) -> dict:
    return {
        "carrier": "Example Carrier",
        "barcode": barcode,
        "sender": "Sender",
        "receiver": None,
        "status": status,
        "pickup": pickup,
        "planned_from": planned_from,
    }


def test_incoming_counts_and_lists():
    coordinator = _coordinator([_parcel("A"), _parcel("B")])
    sensor = ExampleCarrierIncomingParcelsSensor(
        coordinator, _entry(), lambda _: None, set()
    )
    assert sensor.native_value == 2
    assert len(sensor.extra_state_attributes["parcels"]) == 2


def test_parcel_sensor_status_and_attributes():
    parcel = _parcel("A", status=ParcelStatus.OUT_FOR_DELIVERY)
    sensor = ExampleCarrierParcelSensor(_coordinator([parcel]), _entry(), "A")
    assert sensor.native_value == ParcelStatus.OUT_FOR_DELIVERY
    assert sensor.extra_state_attributes["barcode"] == "A"


def test_parcel_sensor_missing_barcode():
    sensor = ExampleCarrierParcelSensor(_coordinator([_parcel("A")]), _entry(), "OTHER")
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}


def _in(**delta) -> str:
    return (datetime.now(UTC) + timedelta(**delta)).isoformat()


def test_next_delivery_picks_earliest():
    soon = datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)
    coordinator = _coordinator(
        [
            _parcel("A", planned_from=(soon + timedelta(days=1)).isoformat()),
            _parcel("B", planned_from=soon.isoformat()),
        ]
    )
    sensor = ExampleCarrierNextDeliverySensor(coordinator, _entry())
    assert sensor.native_value == soon
    assert sensor.extra_state_attributes["barcode"] == "B"


def test_next_delivery_carries_the_contents():
    parcel = _parcel("A", planned_from="2099-05-01T10:00:00Z")
    parcel["contents"] = "Running shoes"
    sensor = ExampleCarrierNextDeliverySensor(_coordinator([parcel]), _entry())
    assert sensor.extra_state_attributes["contents"] == "Running shoes"


def test_next_delivery_skips_a_window_that_has_ended():
    stale = _parcel("A", planned_from=_in(days=-3))
    stale["planned_to"] = _in(days=-2)
    moment_only = _parcel("B", planned_from=_in(hours=-2))
    coordinator = _coordinator(
        [stale, moment_only, _parcel("C", planned_from=_in(days=2))]
    )
    sensor = ExampleCarrierNextDeliverySensor(coordinator, _entry())
    assert sensor.extra_state_attributes["barcode"] == "C"


def test_next_delivery_keeps_a_window_that_is_still_running():
    running = _parcel("A", planned_from=_in(hours=-1))
    running["planned_to"] = _in(hours=2)
    sensor = ExampleCarrierNextDeliverySensor(_coordinator([running]), _entry())
    assert sensor.extra_state_attributes["barcode"] == "A"


def test_next_delivery_none_without_moments():
    sensor = ExampleCarrierNextDeliverySensor(_coordinator([_parcel("A")]), _entry())
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}


def test_next_delivery_skips_unparseable_moment():
    coordinator = _coordinator(
        [
            _parcel("A", planned_from="not-a-date"),
            _parcel("B", planned_from=_in(days=1)),
        ]
    )
    sensor = ExampleCarrierNextDeliverySensor(coordinator, _entry())
    assert sensor.extra_state_attributes["barcode"] == "B"


def test_en_route_and_awaiting_pickup_split():
    parcels = [
        _parcel("EN_ROUTE", pickup=True),
        _parcel("READY", pickup=True, status=ParcelStatus.AT_PICKUP_POINT),
        _parcel("HOME"),
    ]
    en_route = ExampleCarrierEnRouteToPickupPointSensor(_coordinator(parcels), _entry())
    awaiting = ExampleCarrierAwaitingPickupSensor(_coordinator(parcels), _entry())
    assert en_route.unique_id == "e1_en_route_to_pickup_point"
    assert awaiting.unique_id == "e1_awaiting_pickup"
    assert [p["barcode"] for p in en_route.extra_state_attributes["parcels"]] == [
        "EN_ROUTE"
    ]
    assert [p["barcode"] for p in awaiting.extra_state_attributes["parcels"]] == [
        "READY"
    ]
    assert en_route.native_value == 1
    assert awaiting.native_value == 1


def test_en_route_leaves_out_a_returning_pickup_parcel():
    parcels = [
        _parcel("BACK", status=ParcelStatus.RETURNING, pickup=True),
        _parcel("GOING", status=ParcelStatus.IN_TRANSIT, pickup=True),
    ]
    en_route = ExampleCarrierEnRouteToPickupPointSensor(_coordinator(parcels), _entry())
    assert [p["barcode"] for p in en_route.extra_state_attributes["parcels"]] == [
        "GOING"
    ]


def test_pickup_sensors_zero_without_data():
    coordinator = _coordinator([])
    coordinator.data = None
    assert (
        ExampleCarrierEnRouteToPickupPointSensor(coordinator, _entry()).native_value
        == 0
    )
    assert ExampleCarrierAwaitingPickupSensor(coordinator, _entry()).native_value == 0


def test_delivered_sensor():
    coordinator = _coordinator(
        [], delivered=[_parcel("D", status=ParcelStatus.DELIVERED)]
    )
    sensor = ExampleCarrierDeliveredParcelsSensor(coordinator, _entry())
    assert sensor.native_value == 1
    assert sensor.extra_state_attributes["parcels"][0]["barcode"] == "D"


def test_last_update_sensor():
    coordinator = _coordinator([])
    moment = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
    coordinator.last_success_time = moment
    sensor = ExampleCarrierLastUpdateSensor(coordinator, _entry())
    assert sensor.native_value == moment
