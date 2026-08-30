# ha-carrier-template

The scaffold for a new carrier integration in the
[ha-parcel-integrations](https://github.com/ha-parcel-integrations) suite.

This repository is **a working, fully tested Home Assistant integration** for a
fictional carrier (`example_carrier`). You do not copy files out of it by hand —
you run `scripts/bootstrap.py`, which stamps out a new repo with the carrier's
name, prunes the parts you did not ask for, and leaves behind exactly four files
marked `# TODO(carrier):`.

Why a runnable integration rather than a set of templates: a scaffold that is
itself installed, imported and tested cannot rot quietly. CI generates all four
variants on every push and runs their test suites.

## Bootstrap a new carrier

```bash
python scripts/bootstrap.py \
  --name "Cainiao" \
  --domain cainiao \
  --slug ha-cainiao \
  --manufacturer "Cainiao Network" \
  --auth none \
  --out ../ha-cainiao
```

| Flag | Choices | What it does |
|---|---|---|
| `--name` | free text | Display name, used in entity names and prose |
| `--domain` | snake_case | HA domain and the `custom_components/<domain>` folder |
| `--slug` | kebab-case, `ha-`-prefixed | Repo name (`ha-cainiao`, **not** `cainiao`), used in documentation and issue URLs |
| `--manufacturer` | free text | Device-registry manufacturer (defaults to `--name`) |
| `--auth` | `none`, `credentials` | Account-less tracking-code model, or username/password with reauth |
| `--out` | path | Where to write the new repo (must not exist) |

Pick `--auth credentials` when the carrier has consumer accounts with a parcel
feed; that swaps in login, reauth and a list endpoint, and drops the
`track_parcel` services (there is nothing to track manually — the account
already knows).

Polling is not a flag: every generated carrier gets the same dynamic,
status-driven cadence (quiet window, two daily anchors, hot/mid tiers, an
automatic full stop when nothing is left to track) with no user-facing
interval option. See `scaffold/CLAUDE.md`'s "Dynamic polling" section for the
algorithm and the reasoning. A carrier that genuinely throttles or soft-bans
unusual traffic is a local, documented divergence in that one repo, not a
generator flag.

## What you still have to write

After bootstrapping, `grep -rn "TODO(carrier)"` lists everything that is still
placeholder. The load-bearing ones:

| File | What to fill in |
|---|---|
| `api.py` | The request and the response envelope |
| `const.py` | Endpoint URLs, what you know about the endpoint, and `CAPABILITIES` (which optional contract fields this carrier actually populates — feeds the comparison table on the docs site; a carrier with more than one backend declares `CAPABILITIES_BY_VARIANT` instead — see the comment above it) |
| `parcels.py` | `_STATUS_MAP` and the field lookups in `normalize_parcel` |
| `config_flow.py` | The tracking-code format (or the credential fields) |
| `diagnostics.py` | The carrier's payload field names, in `TO_REDACT` |
| `device.py` | The carrier's site, as the device's configuration URL |

Plus `tests/payloads.py` (real, redacted responses), `CLAUDE.md`'s
*Carrier-specific notes* section, the README's carrier paragraphs, the e-mail
example's regex, and `brand/icon.png` — the generated one is a placeholder.

## Repository layout

| Path | Purpose |
|---|---|
| `custom_components/example_carrier/` | The reference integration — account-less |
| `tests/` | Its test suite (98% coverage) |
| `variants/credentials/` | Overlay applied for `--auth credentials` |
| `scaffold/` | The generated repo's `README.md`, `CLAUDE.md` and `.github/` |
| `examples/`, `hacs.json`, `pytest.ini`, … | Copied through as-is |
| `scripts/bootstrap.py` | The generator |
| `.github/workflows/template.yml` | CI for the template itself |

`README.md`, `CLAUDE.md`, `scripts/`, `variants/` and this repo's own
`.github/` are template-only — the generator does not copy them into the new
repo.

Two mechanisms shape the output. Whole files that differ between the account
models come from the **overlay** in `variants/credentials/`. Smaller, scattered
differences use **variant markers** instead — `# >>> variant: <tag>` /
`# <<< variant: <tag>` (or `<!-- -->` in Markdown) — because an overlay for a
handful of lines would mean maintaining two near-identical copies of a file.
An active block keeps its body and loses its markers; an inactive one is
deleted. Only the `auth-<none|credentials>` axis is active today — the polling
axis these markers used to carry was retired when dynamic polling became
unconditional (see `scaffold/CLAUDE.md`). The mechanism stays for the next
axis that needs it.

## Working on the template itself

See [CLAUDE.md](CLAUDE.md).
