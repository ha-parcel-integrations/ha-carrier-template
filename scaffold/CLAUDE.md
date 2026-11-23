# Working in this repository

Home Assistant custom integration for **Example Carrier** parcel tracking.
Distributed via HACS; not part of HA core. One carrier in the
[ha-parcel-integrations](https://github.com/ha-parcel-integrations) suite,
**generated from ha-carrier-template** — everything outside *Carrier-specific
notes* is suite-wide; when in doubt check the template or a sibling repo.
No DTO layer.

API mechanics — endpoints, parameters, status vocabularies — live in the
private `carrier-research/example_carrier/api/` and are **never** copied here.

## Shared conventions — fetch when relevant

Suite-wide rules live in
[`.github/CONVENTIONS.md`](https://github.com/ha-parcel-integrations/.github/blob/main/CONVENTIONS.md)
and are **not** repeated here. Don't fetch it every session — fetch it **before**
you act in one of these areas:

| Before you … | Fetch `CONVENTIONS.md` § |
|---|---|
| touch entities, sensors, config/options flow, coordinator, diagnostics, translations | *Home Assistant developer docs* (its table points on to the canonical HA page — don't rely on memory) |
| add/rename a parcel field, a `ParcelStatus`, or a bus event; change the sort/first-refresh; touch unmapped-status logging | *Parcel contract* — exact key set, units, sort, events + suppression; `test_parcels.py::test_normalize_publishes_exactly_the_canonical_keys` guards the key set |
| change which optional field this carrier populates vs. always returns `None` | Update `const.py`'s `CAPABILITIES` in the same commit — it feeds the comparison table on the docs site, so a field that starts (or stops) coming back non-null and isn't reflected there is a wrong claim on the website, not just a stale comment. If this carrier has more than one backend (a country-specific transport, not just a config option) with genuinely different field support, `CAPABILITIES` should be a `CAPABILITIES_BY_VARIANT` dict instead — one frozenset per backend, so a field only some backends populate doesn't get silently intersected away or overclaimed for the rest. A field you could not verify (no real parcel yet) goes in `PENDING_CAPABILITIES` instead of being left out — the site then says "awaiting data" rather than claiming the API never exposes it; move it into `CAPABILITIES` once confirmed |
| ship anything while below 1.0.0 (unconfirmed data) | *Pre-1.0 releases* — one-shot WARNINGs for every guessed shape/code |
| consider "fixing" a lint/pattern the skill flags (poll interval, inline client, sync requests) | *Deliberate skill divergences* — likely intentional, don't re-flag |
| commit, bump, tag, release, or write release notes; add a feature without a test | *Workflow / Commits / Versioning / Testing* |

**Suite-wide tripwires, kept inline on purpose:**
- **First refresh in `__init__.py`, before `async_forward_entry_setups`** — from
  a forwarded platform HA can't catch `ConfigEntryNotReady` and half-sets-up the
  entry. Runtime-only; tests don't catch a regression.
- **Setup stale-entity sweep is scoped to `domain == "sensor"` and skips
  `non_parcel_unique_ids`** — else it deletes the refresh button / the
  summary+diagnostic sensors. Add a new non-parcel sensor's unique_id to the set.
- **Per-parcel sensors are removed by the summary sensor** via
  `entity_registry.async_remove` (self-removal races and leaves ghosts).
- **Events and `_known_state` are built from the unfiltered delivered list.**
  The "keep N days / N parcels" option only trims `coordinator.delivered`; a
  parcel it leaves out must still fire `_parcel_delivered`.
- **The pickup-point summaries are a pair.** A carrier that can deliver to a
  pickup point or locker exposes both `en_route_to_pickup_point` and
  `awaiting_pickup`, even before a real parcel has shown the status or flag
  (they read 0 until then; record it in `PENDING_*`). A carrier without pickup
  points exposes neither and keeps `pickup` constantly False.
  See *Parcel contract* in `CONVENTIONS.md`. Say "pickup point", not
  "ServicePoint"/"parcel shop"/"locker", for the generic concept; the
  example carrier demonstrates both canonical sensors.

## Carrier-specific notes

> **TODO(carrier):** replace this whole section with the carrier's *integration*
> decisions, then delete this note. Keep it HA-side: auth-error → HA-exception
> mapping, cost-control caching, fields that are `None` on purpose (this is
> prose context for a human — the machine-readable version a future carrier or
> the docs site can trust is `const.py`'s `CAPABILITIES`, keep the two in
> agreement), pickup/ETA quirks, and any live-verified caveat that changes
> integration behaviour.
>
> **API mechanics go in your own private research notes, NOT here and not in
> a local `docs/api/`** — the endpoint(s) and what keys them, auth flow, rate
> limits, response content type, the "unknown code" vs error signalling, the
> status vocabulary and its `ParcelStatus` mapping, and the timestamp format.
> See CONVENTIONS.md.

## Options and reloads

For code-based carriers, the options flow starts with exactly `Parcels` and
`Settings` — or, where the carrier supports outgoing parcels, `Incoming
parcels` / `Outgoing parcels` / `Settings` (see the next section).
`Parcels` is one editable multi-code list; `Settings` is
a flat form — some carriers use one sectioned form
(`data_entry_flow.section`) instead; both are generator variants, not carrier
decisions. Changes apply without a restart. Two models, **do not mix them**:
- **Account-less carriers** (the default, and the `--auth byo-key` build) apply
  changes live: an update listener calls `async_request_refresh()`, so
  added/removed parcel sensors appear immediately (this is also the resume
  path after polling has fully suspended — see "Dynamic polling" below).
- **Account-based carriers** make the options flow an `OptionsFlowWithReload`
  and register **no** update listener (the two may not be combined). Never call
  `async_schedule_reload` from the submit instead: that reload starts before the
  new options are saved, so anything read from `entry.options` at setup keeps
  the old value.

**`_async_options_updated` compares `entry.options` against the snapshot on
`runtime_data` before refreshing — don't drop that.** HA notifies an update
listener on *every* `async_update_entry`, not just an options edit, so the
moment this carrier's coordinator persists anything onto the entry (a rotated
token, a learned identifier) an unconditional refresh turns that write into a
poll — on the write's cadence, and straight past the "Enable polling for
updates" system option, which only gates the coordinator's *scheduled*
refresh. That is a reported bug elsewhere in the suite, not a theoretical
one: a ten-minute token renewal kept polling an entry whose owner had
switched polling off.

## Auth models

Three `--auth` builds, one axis: **what the config flow asks for and
validates**, not how tracking works. `none` and `byo-key` both key tracking on
codes the user types in (`Parcels`/`Settings` options, `track_parcel` /
`untrack_parcel` services, the account-less coordinator and its full-stop /
delivered-skip behaviour below) — `byo-key` only adds a required key field
validated against the carrier's **official** API at setup, `CONF_API_KEY` in
`entry.data`, and a reauth flow for when the key is rotated or revoked outside
Home Assistant (`ExampleCarrierAuthError` from any per-parcel fetch raises
`ConfigEntryAuthFailed` for the whole poll — one credential covers every
tracked code, so a rejected key is never treated as one parcel's problem).
`credentials` is the only one that changes the *tracking* model too (an
account feed, not user-entered codes) — see the split above.

Reach for `byo-key` only when carrier-research has already established that
the carrier's *unauthenticated/consumer* surface is unusable (bot-walled,
requires a session a script can't hold) and that the *official* developer key
is reachable by a private individual — `key_access: consumer` in the research
doc's front matter, not `business`. A `business`-gated key is a wall, not a
BYO key, whatever the portal's own copy claims (see
`carrier-research/CLAUDE.md`'s "Standing rulings").

## Incoming and outgoing parcels

**Add outgoing support whenever the carrier lets a consumer send a parcel** —
a C2C shipment, a locker drop-off, a marketplace or returns label. It is not
an optional extra to bolt on later: without it a parcel the user sent counts
towards `incoming_active` and sits on their dashboard next to the ones they
are waiting for. A carrier that genuinely has no consumer-sending surface is
exempt — say so in *Carrier-specific notes* so the gap reads as a decision.

Where the direction comes from has exactly two answers, and which one applies
follows from the carrier, not from taste:

- **Account-based** — the account feed distinguishes them, so derive it and
  never ask the user. A shipment matching neither side logs a one-shot
  warning and defaults to incoming rather than disappearing from every list.
  References: `ha-ppl-cz` (one call, split on a field), `ha-dhl-nl` (a
  separate "sent" endpoint).
- **Account-less** — the payload cannot reveal it (the user's own parcel and
  a stranger's look alike, and there is no account identity to compare a
  party against), so the **user declares it per parcel**: two menu entries in
  the options flow, each the same multi-code list, plus a `direction` field on
  `track_parcel`. Store it as `CONF_DIRECTION` on the `CONF_PARCELS` dicts,
  defaulting to incoming, so entries written before the option existed need no
  migration. Re-filing a code under the other direction moves it instead of
  erroring — that is the correction path. Reference: `ha-packeta`.
  **Never infer direction from free-text event wording**: a handover sentence
  that happens to name the drop-off point is not a structured field, says
  nothing before handover, and silently ties the split to one locale.

Above that split the shape is identical either way, and is suite-wide:
`coordinator.outgoing` / `coordinator.delivered_outgoing` alongside `data` /
`delivered`; `outgoing_parcels` + `outgoing_delivered_parcels` summary
sensors (their unique_ids belong in `non_parcel_unique_ids`); per-parcel
sensors spawned for **both** directions; the
`<domain>_outgoing_parcel_status_changed` / `_outgoing_parcel_delivered`
event pair, with **no** `registered` and no delivery-time event for outgoing;
`awaiting_pickup`, `next_delivery` and the calendar staying incoming-only;
and both new lists in `diagnostics.py`. The aggregator needs no change — it
buckets on the sensor suffix and the event prefix. Also set
`directions: incoming+outgoing` for the carrier in the docs site's
`data/carriers.yml`.

## Parcel contract: window, pickup and the sensors

The rules for when each parcel field is filled or emptied are in the suite's
`PARCEL_CONTRACT.md`. `parcels.py` carries three helpers that keep a
normaliser to them, and `tests/test_contract.py` runs the contract's checks
over every normalised sample; add a sample there when a new shape appears.

- `planned_window(start, end, *, zone)` builds `planned_from` / `planned_to`:
  a window keeps both ends, one moment with a time ends at `23:59:59` the same
  day, a date is `00:00:00`–`23:59:59`, two dates span first to last day.
  `zone` is the carrier's own zone for naive times and bare dates.
- `planned_for_status(status, planned_from, planned_to)` empties the window at
  `at_pickup_point`, `returning` and `delivered`.
- `is_pickup(route_flag, status, event_statuses)` stays `True` once a parcel
  has reached a pickup point, so a collected parcel keeps `pickup`.

`delivered` is `status is DELIVERED`, plus `RETURNING` only when the carrier
reports the parcel back at the sender. An explicit delivered signal from the
carrier (flag, timestamp or status) maps to `DELIVERED` even over
`AT_PICKUP_POINT`, because a collected parcel is delivered (a signal that
already fires on drop-off at the point does not count); on a `RETURNING`
parcel it counts only as evidence of delivery at the sender. `next_delivery` skips a parcel whose
window has ended, and `en_route_to_pickup_point` leaves out `returning`.

## Calendar: whole days are all-day events

`calendar.py` turns a `00:00:00`–`23:59:59` window (one day or several) into an
all-day event on dates, the end date being the day after the last day, as
Home Assistant expects. It checks the window's own offset first (a carrier's
local or naive wall clock), then Home Assistant's zone (a window sent in UTC).
Any other window, including a moment stretched to `23:59:59`, stays timed, and
a moment without an end still gets one hour. Once an event can be on dates,
compare it through `start_datetime_local` / `end_datetime_local`, never
`start` / `end`: a date does not compare with a datetime.

## Tracking-code validation

In code-based carriers (account-based sources have no code entry),
`valid_tracking_code` in `config_flow.py` accepts every non-empty code — no
format regex. This is a suite-wide convention, not a per-carrier TODO: real
tracking-number formats vary too much across carriers, and are often not
fully confirmed even for this one, to gate on a guessed shape. A too-strict
regex risks rejecting a genuinely valid code; an actually-bad code just comes
back "not found" on the next poll, which is a far cheaper failure mode. Do
not add one back in, even once the format is confirmed.

## Dynamic polling

There is no user-facing polling interval — this is a deliberate suite-wide
choice, not a gap. `coordinator.py`'s `_hottest_tier_minutes` /
`_next_update_interval` recompute `update_interval` at the end of every
refresh. The reference carrier in `ha-carrier-template` (its `coordinator.py`)
is the canonical implementation every carrier mirrors; the design rationale (quiet window, tiers, stagger,
backoff, delivered-skip) is spelled out below.

- **Quiet window:** no polling 00:00–06:00 local time, except two daily
  anchors (~00:00 and ~06:00) for overnight / end-of-day catch-up.
- **Tiers while polling:** *hot* (15 min) when a tracked, not-yet-delivered
  parcel is `out_for_delivery` within an hour of its `planned_from` (or has no
  `planned_from` at all); *mid* (45 min) for anything else still in flight —
  `problem`/`returning` included, deliberately not hot. Account-based carriers
  never fully stop even with nothing hot or in transit: the mid-tier poll is
  also how a new shipment gets discovered.
- **Full stop (account-less carriers only):** `update_interval = None` when
  nothing is tracked or every tracked parcel is delivered. Resumes the moment
  a parcel is added back, via the options-flow refresh above.
- **Failed polls:** `_async_update_data` wraps `_async_poll` and recomputes `update_interval` on any failure (never to `None`, falling back to the mid tier), so a failure after the overnight poll retries at the daytime cadence instead of waiting out the quiet window. A parcel whose fetch keeps failing logs one WARNING, then DEBUG on every further poll, and one INFO when it recovers (`_failing_codes`), so a carrier that stays inconclusive for days does not flood the log.
- **Stagger:** a small, stable per-install offset (hash of the config entry
  id) is added to every computed interval so installs don't all hit an anchor
  or tier boundary at the same second.
- **429 backoff:** a 429 anywhere in a poll raises `UpdateFailed` with
  `retry_after` — the carrier's own `Retry-After` header if present, otherwise
  an exponential backoff tracked per-coordinator. `api.py`'s
  `…ApiError.status_code` / `.retry_after` carry this from the HTTP layer.
- **Delivered codes are skipped from the fetch (account-less carriers only):**
  once a tracking code's payload comes back `delivered`, `coordinator.py`
  excludes it from the next cycle's fetch — its payload can never change
  again. `self._delivered_codes` (keyed on the tracking code, not the barcode)
  is rebuilt from each cycle's results and intersected with the tracked set on
  untrack. The code stays in the options list, keeps its sensor and its
  cached payload, and still shows under the retention window — it just costs
  no more requests. `coordinator.delivered_codes` surfaces the count in
  diagnostics. Account-based carriers have nothing to skip here — one account
  call already returns everything, so they either have no `delivered_codes` or
  it is always empty.

A carrier that genuinely throttles or soft-bans traffic harder than the 429
backoff handles is a documented, local divergence from this in that one
repo's own `CLAUDE.md` — not a generator flag.

## Module layout

| File | Carrier-specific? |
|---|---|
| `api.py` (HTTP client, error types; `account/` and `tracking/` packages instead when a repo has two sources) | **yes** |
| `const.py` (domain, URLs, `ParcelStatus`, option keys) | partly (URLs) |
| `parcels.py` (status map, `normalize_parcel`, history, sort, filters — pure, no I/O) | partly (the status map, `normalize_parcel`) |
| `coordinator.py` (fetch, cache, event firing) | mostly not |
| `config_flow.py` | partly (code validation; key/credential validation on `--auth byo-key`/`credentials`) |
| `sensor.py` / `button.py` / `calendar.py` / `device_trigger.py` | no |
| `device.py` (shared device-info helper) | no |
| `diagnostics.py` | partly (`TO_REDACT`) |
| `contents.py` (`clean_contents`, `join_contents`, `normalize_code`, `ContentsStore`) | no — identical in every carrier |
| `services.py` (`track_parcel` / `untrack_parcel`, account-less only; `update_contents` in every build) | no |

`parcels.py` is deliberately free of I/O and HA objects so the per-carrier part
stays unit-testable without Home Assistant. Config: `ConfigEntry.runtime_data`
(typed, no `hass.data`), `PARALLEL_UPDATES = 0`, coordinator takes
`config_entry=entry`. `aiohttp.ClientError` is caught **per parcel** in the gather
loop (one bad parcel doesn't fail the poll) but **not** around the whole update
(the coordinator wraps that). Entities: `has_entity_name` + `translation_key`,
`icons.json`, translated units, `_attr_attribution`, `_unrecorded_attributes` on
anything with a parcel list or `raw`. Over-redact diagnostics — they get pasted
into public issues.

## Parcel contents

`contents` is a short string describing what is in the parcel, right after
`receiver` in every normaliser, `None` when unknown, never `""`. Three rules:

- **Precedence**: the user's value (set with `update_contents`, or the optional
  `contents` field on `track_parcel`) beats a label the user gave the parcel in
  the carrier's own account, which beats the carrier's own item text.
  `normalize_parcel` stays pure and fills only the last two, through
  `clean_contents` / `join_contents`; the coordinator overlays the user's value
  straight after normalising, before sorting, events and the delivered split,
  keyed on the code the parcel was requested with (the barcode on an account
  feed).
- **Several accounts** (credentials build): `update_contents` stores in, and
  refreshes, every loaded entry whose `coordinator.known_codes` holds the code;
  none knows it and more than one is loaded raises, unless `config_entry_id`
  names the entry.
- **Storage** is one `Store` per config entry (`ContentsStore`, key
  `<domain>.contents.<entry_id>`, 200 codes, oldest dropped first). Nothing goes
  into `options`, so the options flow, its reload and any migration are never
  involved. `untrack_parcel` drops a code's value, `async_remove_entry` the file.
- **Capability**: declare `"contents"` in `CAPABILITIES` only where the carrier
  itself fills it (a user label counts); user-supplied text alone is not one.
  A carrier's generic text ("Consumer goods") maps to `None`: pass a
  `CONTENTS_FILLER` frozenset of casefolded strings to `clean_contents` rather
  than filtering by hand. The carrier's own field stays untouched in `raw`.

`contents` is free text about what someone bought: it is in `TO_REDACT`, and no
test or fixture carries a real value. A change to `contents` alone fires no
event.

## Running tests

```
python -m pytest tests/ --cov=custom_components.example_carrier
```

Coverage must stay **above 95%** (silver `test-coverage` rule). Run before
committing. A code change updates the README + this file + `docs/` in the same
commit; the API reference lives in your own private research notes, never in
this repo.
