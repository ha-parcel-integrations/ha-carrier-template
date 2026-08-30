#!/usr/bin/env python3
"""Generate a new carrier integration repo from this template.

    python scripts/bootstrap.py --name "Cainiao" --domain cainiao \
        --slug ha-cainiao --auth none --out ../ha-cainiao

Three things happen, in this order:

1. **Overlay** — with ``--auth credentials`` the files under
   ``variants/credentials/`` replace their counterparts, and the paths listed
   in that variant's ``remove.txt`` are deleted.
2. **Variant blocks** — lines between ``>>> variant: <tag>`` and
   ``<<< variant: <tag>`` markers are kept (markers stripped) when the tag is
   active for this build, and deleted otherwise. Used for a handful of
   scattered lines that differ, where a whole-file overlay would be overkill.
   Only the ``auth-<none|credentials>`` axis is active today; polling is no
   longer one of these — dynamic polling (see scaffold/CLAUDE.md) is
   unconditional, with nothing left for a build flag to select between.
3. **Tokens** — ``example_carrier`` / ``ExampleCarrier`` / ``Example Carrier``
   / ``ha-example-carrier`` are replaced in file *contents* and in path names.

Run it from anywhere; paths are resolved relative to the template root.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

TEMPLATE_ROOT = Path(__file__).resolve().parent.parent

# Never copied into a generated repo: template-only tooling and docs. Note
# ``.github`` — the generated repo gets its workflows from ``scaffold/github``
# instead, so the template's own CI cannot end up in a carrier repo.
TEMPLATE_ONLY = {
    ".github",
    "CLAUDE.md",
    "README.md",
    "docs",
    "reports",
    "scaffold",
    "scripts",
    "variants",
}
# Never copied at all: caches and local state. Everything the template's own
# .gitignore covers belongs here — if it is not worth committing here, it is not
# worth shipping into a carrier. ``.claude`` and ``skills-lock.json`` are the
# easy ones to forget: they appear the moment anyone runs Claude Code in the
# template, and carry machine-local settings and skills.
JUNK = {
    ".claude",
    ".coverage",
    ".DS_Store",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "skills-lock.json",
}

# Files we rewrite the contents of. Anything else (images, …) is copied as-is.
TEXT_SUFFIXES = {".py", ".json", ".md", ".yaml", ".yml", ".txt", ".cfg", ".ini", ""}

MARKER_RE = re.compile(r"(>>>|<<<)\s*variant:\s*([a-z0-9-]+)")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--name", required=True, help='Display name, e.g. "Cainiao"')
    parser.add_argument("--domain", required=True, help="HA domain, e.g. cainiao")
    parser.add_argument(
        "--slug",
        required=True,
        help="Repo name -- the full ha-* form, e.g. ha-cainiao, not 'cainiao'",
    )
    parser.add_argument("--manufacturer", help="Device manufacturer (defaults to --name)")
    parser.add_argument(
        "--auth",
        choices=("none", "credentials"),
        default="none",
        help="none: tracking codes entered by the user. credentials: account login + reauth.",
    )
    parser.add_argument("--out", required=True, help="Where to write the new repo")
    parser.add_argument(
        "--force", action="store_true", help="Overwrite --out if it already exists"
    )
    args = parser.parse_args(argv)

    if not re.fullmatch(r"[a-z][a-z0-9_]*", args.domain):
        parser.error("--domain must be snake_case and start with a letter")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", args.slug):
        parser.error("--slug must be kebab-case")
    if not args.slug.startswith("ha-"):
        # --slug is the *repo* name, but the suite also calls the bare carrier
        # key ("cainiao") a slug, and build plans have been written against the
        # wrong one. A bare slug generates without complaint and points every
        # GitHub URL at a repo that does not exist -- the README badge, the HACS
        # install line, manifest.json's documentation/issue_tracker, and the
        # unrecognised-status issue link the pre-1.0 warnings hang on.
        parser.error(
            f"--slug is the repo name and must start with 'ha-': "
            f"got {args.slug!r}, did you mean 'ha-{args.slug}'?"
        )
    args.manufacturer = args.manufacturer or args.name
    return args


def class_prefix(name: str) -> str:
    """Turn a display name into a Python class prefix.

    "Cainiao" -> "Cainiao"; "DHL eCommerce" -> "DHLeCommerce"; "Post-NL" ->
    "PostNL". Separators are dropped, and a word is only capitalised when it
    carries no capital of its own — otherwise "eCommerce" would become
    "ECommerce" and "NL" would survive as "NL" by luck rather than by rule.
    Carriers care about how their name is written.
    """
    cleaned = re.sub(r"[^0-9A-Za-z]+", " ", name).split()
    if not cleaned:
        raise SystemExit("--name must contain at least one alphanumeric character")
    return "".join(
        word if any(char.isupper() for char in word) else word[0].upper() + word[1:]
        for word in cleaned
    )


def active_tags(args: argparse.Namespace) -> set[str]:
    return {f"auth-{args.auth}"}


def copy_tree(src: Path, dst: Path, *, skip_template_only: bool) -> None:
    """Copy ``src`` into ``dst``, skipping junk (and optionally template-only)."""
    for item in sorted(src.iterdir()):
        if item.name in JUNK:
            continue
        if skip_template_only and item.name in TEMPLATE_ONLY:
            continue
        target = dst / item.name
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            copy_tree(item, target, skip_template_only=False)
        else:
            shutil.copy2(item, target)


def apply_overlay(out: Path, overlay: Path) -> list[str]:
    """Copy the overlay over the generated tree; return what it replaced."""
    replaced: list[str] = []
    for item in sorted(overlay.rglob("*")):
        if item.is_dir() or item.name == "remove.txt":
            continue
        relative = item.relative_to(overlay)
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            replaced.append(str(relative))
        shutil.copy2(item, target)
    return replaced


def apply_removals(out: Path, remove_file: Path) -> list[str]:
    """Delete the paths listed in ``remove.txt``; return what went."""
    if not remove_file.exists():
        return []
    removed: list[str] = []
    for line in remove_file.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        target = out / line
        if target.is_dir():
            shutil.rmtree(target)
            removed.append(line)
        elif target.exists():
            target.unlink()
            removed.append(line)
    return removed


def prune_variant_blocks(text: str, tags: set[str], *, where: str) -> str:
    """Resolve ``>>> variant: <tag>`` blocks against the active ``tags``.

    An active block keeps its body and loses its markers; an inactive one is
    dropped entirely. Unbalanced markers are a bug in the template, so they
    raise rather than silently mangling the output.
    """
    out: list[str] = []
    open_tag: str | None = None
    keep = True
    for number, line in enumerate(text.splitlines(keepends=True), start=1):
        match = MARKER_RE.search(line)
        if match is None:
            if keep:
                out.append(line)
            continue
        kind, tag = match.groups()
        if kind == ">>>":
            if open_tag is not None:
                raise SystemExit(
                    f"{where}:{number}: nested variant block "
                    f"({tag} inside {open_tag}) — blocks may not overlap"
                )
            open_tag, keep = tag, tag in tags
        else:
            if open_tag != tag:
                raise SystemExit(
                    f"{where}:{number}: closing marker for {tag} "
                    f"but {open_tag or 'nothing'} is open"
                )
            open_tag, keep = None, True
    if open_tag is not None:
        raise SystemExit(f"{where}: variant block {open_tag} is never closed")
    return "".join(out)


def fix_articles(text: str, name: str) -> str:
    """Correct "a/an <Name>" after substitution.

    The template says "an Example Carrier"; a name starting with a consonant
    would leave "an Cainiao" behind. Letter-based, so it gets "an hour" style
    edge cases wrong — but carrier names are proper nouns, where the letter is
    almost always right.
    """
    article = "an" if name[0].lower() in "aeiou" else "a"
    pattern = re.compile(rf"\b(a|an|A|An)(\s+{re.escape(name)})\b")

    def replace(match: re.Match[str]) -> str:
        chosen = article.capitalize() if match.group(1)[0].isupper() else article
        return chosen + match.group(2)

    return pattern.sub(replace, text)


def rewrite_contents(out: Path, args: argparse.Namespace, tags: set[str]) -> None:
    """Prune variant blocks and substitute tokens in every text file."""
    replacements = [
        # Longest / most specific first: "ExampleCarrier" must not be eaten by
        # the "Example Carrier" rule, and "ha-example-carrier" must not be
        # eaten by "example_carrier".
        ("ExampleCarrier", class_prefix(args.name)),
        ("ha-example-carrier", args.slug),
        ("Example Carrier", args.name),
        ("example_carrier", args.domain),
    ]

    for path in sorted(out.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # a binary file with a text-ish suffix; leave it alone

        text = prune_variant_blocks(
            text, tags, where=str(path.relative_to(out))
        )

        for old, new in replacements:
            text = text.replace(old, new)
        text = fix_articles(text, args.name)
        if args.manufacturer != args.name:
            text = text.replace(
                f'manufacturer="{args.name}"', f'manufacturer="{args.manufacturer}"'
            )
        path.write_text(text, encoding="utf-8")


def rename_paths(out: Path, domain: str) -> None:
    """Rename any path component containing the template domain."""
    for path in sorted(out.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if "example_carrier" in path.name:
            path.rename(path.with_name(path.name.replace("example_carrier", domain)))


def finalise_manifest(out: Path, args: argparse.Namespace) -> None:
    """Set the fields the token substitution cannot get right on its own."""
    manifest = out / "custom_components" / args.domain / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["version"] = "0.1.0"
    if args.auth == "none":
        # No account and no postcode: nothing to key a second hub on.
        data["single_config_entry"] = True
    else:
        data.pop("single_config_entry", None)
    manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def promote_scaffold(out: Path, scaffold: Path, tags: set[str]) -> None:
    """Put the generated repo's own docs and workflows in place.

    ``scaffold/github/`` becomes ``.github/``: the workflows in there are for
    the *generated* repo (HACS validation, hassfest), and would fail if the
    template ran them on itself. The template's own CI lives in its
    ``.github/workflows/template.yml``.
    """
    for name in ("README.md", "CLAUDE.md"):
        text = prune_variant_blocks(
            (scaffold / name).read_text(encoding="utf-8"),
            tags,
            where=f"scaffold/{name}",
        )
        (out / name).write_text(text, encoding="utf-8")

    github = out / ".github"
    if github.exists():
        shutil.rmtree(github)
    shutil.copytree(scaffold / "github", github)


def write_todo(out: Path, args: argparse.Namespace) -> list[str]:
    """Write TODO.md listing every remaining placeholder; return the files."""
    pending: list[str] = []
    for path in sorted(out.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            if "TODO(carrier)" in path.read_text(encoding="utf-8"):
                pending.append(str(path.relative_to(out)))
        except UnicodeDecodeError:
            continue

    lines = [
        f"# {args.name} — still to do",
        "",
        f"Generated from ha-carrier-template (`--auth {args.auth}`). "
        "The integration runs and its tests pass,",
        "but it talks to a fictional API until the placeholders below are replaced.",
        "",
        "## Files carrying `TODO(carrier)` markers",
        "",
    ]
    lines += [f"- [ ] `{name}`" for name in pending]
    lines += [
        "",
        "## Not marked, but still needed",
        "",
        "- [ ] `tests/payloads.py` — real, redacted responses from the carrier",
        "- [ ] `CLAUDE.md` — the *Carrier-specific notes* section",
        "- [ ] `README.md` — intro, requirements, status table, disclaimer",
        f"- [ ] `custom_components/{args.domain}/brand/icon.png` — still the placeholder",
        "- [ ] Install it in a real Home Assistant and track one real parcel",
        "      through at least two status changes",
        "- [ ] If you run a cross-carrier aggregator integration, register",
        "      `" + args.domain + "` with it so its events get picked up",
        "",
        "Delete this file once it is empty.",
        "",
    ]
    (out / "TODO.md").write_text("\n".join(lines), encoding="utf-8")
    return pending


def generate(args: argparse.Namespace, out: Path) -> dict[str, list[str]]:
    """Render a full carrier repo into ``out`` (which must not yet exist).

    The library entry point behind ``main()`` — split out so other tooling
    (``drift_report.py``) can render into a scratch directory without going
    through argument parsing or touching a real ``--out``.
    """
    tags = active_tags(args)
    out.mkdir(parents=True)

    copy_tree(TEMPLATE_ROOT, out, skip_template_only=True)

    replaced: list[str] = []
    removed: list[str] = []
    if args.auth == "credentials":
        overlay = TEMPLATE_ROOT / "variants" / "credentials"
        replaced = apply_overlay(out, overlay)
        removed = apply_removals(out, overlay / "remove.txt")

    promote_scaffold(out, TEMPLATE_ROOT / "scaffold", tags)
    rewrite_contents(out, args, tags)
    rename_paths(out, args.domain)
    finalise_manifest(out, args)
    pending = write_todo(out, args)

    return {"replaced": replaced, "removed": removed, "pending": pending}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out = Path(args.out).expanduser().resolve()

    if out.exists():
        if not args.force:
            raise SystemExit(f"{out} already exists (use --force to overwrite)")
        shutil.rmtree(out)

    result = generate(args, out)

    print(f"Generated {args.name} in {out}")
    print(f"  auth={args.auth}  domain={args.domain}")
    if result["replaced"]:
        print(
            f"  overlay replaced {len(result['replaced'])} file(s), "
            f"removed {len(result['removed'])}"
        )
    print(f"  {len(result['pending'])} file(s) still carry TODO(carrier) — see TODO.md")
    print()
    print("Next:")
    print(f"  cd {out}")
    print("  pip install -r requirements-dev.txt && pytest tests/")
    print()
    print(
        f"Note: custom_components/{args.domain}/brand/icon.png is still the "
        "template placeholder."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
