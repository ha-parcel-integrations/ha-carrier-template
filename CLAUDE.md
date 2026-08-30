# Working on the template itself

This repo is the scaffold for new carrier integrations in the
[ha-parcel-integrations](https://github.com/ha-parcel-integrations) suite. See
[README.md](README.md) for how to *use* it; this file is about changing it.

The reference integration under `custom_components/example_carrier/` is a real,
installable, tested integration for a fictional carrier. Keep it that way — a
template that cannot run is a template that rots.

## The two audiences

Every file here serves one of two purposes, and mixing them up is the main way
this repo goes wrong:

| Audience | Files | Rule |
|---|---|---|
| The **generated repo** | `custom_components/`, `tests/`, `examples/`, `scaffold/`, `hacs.json`, `pytest.ini`, `requirements-dev.txt`, `LICENSE`, `.gitignore` | Written as if it were already the carrier's own repo. No mention of "the template". |
| The **template** | `README.md`, this file, `scripts/`, `variants/`, `.github/` | Never copied into a generated repo. |

`scaffold/` is the odd one out: it lives on the template side but everything in
it is *for* the generated repo. `scaffold/README.md` and `scaffold/CLAUDE.md`
become the new repo's root docs, and `scaffold/github/` becomes its `.github/`.

That last split matters: the generated repo's `validate.yml` runs HACS
validation, which would fail on a template that is not a HACS repo. Keeping it
under `scaffold/` means GitHub never runs it here. The template's own CI is
`.github/workflows/template.yml`.

## Changing shared behaviour

A change to something every carrier shares — the canonical parcel keys, the
event contract, the sensor set, the sort rules — is a **suite-wide** change:

1. Make it here first, with tests.
2. Note it in `scaffold/CLAUDE.md` so generated repos carry the reasoning.
3. Only then roll it out to the existing carrier repos, one PR each.

Going the other way (fixing a carrier repo and forgetting the template) is how
the repos drifted apart in the first place.

## The placeholder icon

`custom_components/example_carrier/brand/icon.png` is a deliberately neutral
parcel glyph on slate grey, with a dashed border so it reads as temporary.

**It must never be a real carrier's logo.** The template previously carried one
verbatim from the repo it was extracted from, which meant every generated
integration shipped another company's brand mark until someone noticed. A
generic placeholder that looks unfinished is doing its job; one that looks
plausible is not.

## Changing the reference carrier's payload

`example_carrier`'s API shape is deliberately generic — string status codes, an
ISO/epoch-ms timestamp mix, an ETA window, a pickup point, weight and
dimensions — so that `normalize_parcel` demonstrates every canonical field. Do
not make it resemble a specific real carrier: whatever quirks it grows, every
future carrier inherits and has to delete.

Samples live in `tests/payloads.py`, not inline in test modules.

## The two variant mechanisms

**Overlay** — `variants/credentials/` mirrors the paths it replaces, so
`variants/credentials/custom_components/example_carrier/api.py` overwrites
`custom_components/example_carrier/api.py`. `variants/credentials/remove.txt`
lists paths deleted after the overlay is applied (one per line, `#` comments
allowed). Use this when a whole file differs.

**Variant markers** — `# >>> variant: <tag>` … `# <<< variant: <tag>` (or
`<!-- >>> variant: <tag> -->` in Markdown). Use this when a handful of
scattered lines differ, where an overlay would mean maintaining two
near-identical copies of a file. Blocks may not nest or overlap —
`bootstrap.py` raises rather than guessing. `auth-<none|credentials>` is the
only axis active today; the polling axis these markers used to carry
(`interval-<configurable|fixed>`) was retired when dynamic, status-driven
polling became unconditional — see scaffold/CLAUDE.md's "Dynamic polling"
section. The mechanism itself stays, for the next axis that needs it.

When you touch a file the overlay also ships, check whether the overlay copy
needs the same change. The CI matrix catches a syntax-level break, but not
semantic drift.

## Keeping the generator honest

`.github/workflows/template.yml` runs a matrix over both `--auth` values.
Each job bootstraps a carrier, asserts that no template token or variant
marker survives, checks that no template-only directory leaked, and runs the
generated test suite. It then *moves the generated repo into the workspace
root* before running hassfest — that action mounts `${{ github.workspace }}`
and takes no path input, so this is the only way to validate the output the
way a real carrier repo is validated.

If you add a variant axis, add it to that matrix in the same commit.

## Running the tests

```
python -m pytest tests/ --cov=custom_components.example_carrier
```

Coverage must stay above 95% — the generated repos inherit both the suite and
the standard.
