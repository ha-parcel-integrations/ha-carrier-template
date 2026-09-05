"""Unit tests for the generator itself.

Lives under ``scripts/`` on purpose: ``tests/`` is copied into every generated
repo, and a carrier integration has no business shipping tests for a template
tool it no longer contains.

Run with ``pytest scripts/test_bootstrap.py``.
"""

import argparse
import json

import pytest
from bootstrap import (
    class_prefix,
    copy_tree,
    fix_articles,
    generate,
    prune_variant_blocks,
)

TAGS = {"auth-none"}


def prune(text: str) -> str:
    return prune_variant_blocks(text, TAGS, where="<test>")


def test_active_block_keeps_its_body_without_markers():
    assert prune(
        "before\n"
        "# >>> variant: auth-none\n"
        "kept\n"
        "# <<< variant: auth-none\n"
        "after\n"
    ) == "before\nkept\nafter\n"


def test_inactive_block_is_removed_entirely():
    assert prune(
        "before\n"
        "# >>> variant: auth-credentials\n"
        "dropped\n"
        "# <<< variant: auth-credentials\n"
        "after\n"
    ) == "before\nafter\n"


def test_markdown_comment_markers_work_too():
    assert prune(
        "<!-- >>> variant: auth-credentials -->\ndropped\n"
        "<!-- <<< variant: auth-credentials -->\nkept\n"
    ) == "kept\n"


def test_adjacent_blocks_resolve_independently():
    """The either/or pairs the template leans on."""
    assert prune(
        "# >>> variant: auth-none\nA\n# <<< variant: auth-none\n"
        "# >>> variant: auth-credentials\nB\n# <<< variant: auth-credentials\n"
    ) == "A\n"


def test_text_without_markers_is_untouched():
    assert prune("just\nsome\nlines\n") == "just\nsome\nlines\n"


# Unbalanced markers would silently delete real code, so they must be loud.


def test_unclosed_block_raises():
    with pytest.raises(SystemExit, match="never closed"):
        prune("# >>> variant: auth-credentials\nbody\n")


def test_nested_block_raises():
    with pytest.raises(SystemExit, match="nested"):
        prune(
            "# >>> variant: auth-credentials\n"
            "# >>> variant: auth-none\n"
            "# <<< variant: auth-none\n"
            "# <<< variant: auth-credentials\n"
        )


def test_mismatched_closing_marker_raises():
    with pytest.raises(SystemExit, match="closing marker"):
        prune(
            "# >>> variant: auth-credentials\n"
            "# <<< variant: auth-none\n"
        )


def test_stray_closing_marker_raises():
    with pytest.raises(SystemExit, match="closing marker"):
        prune("# <<< variant: auth-credentials\n")


# ---------------------------------------------------------------------------
# name handling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Cainiao", "Cainiao"),
        ("Acme Post", "AcmePost"),
        ("DHL eCommerce", "DHLeCommerce"),
        ("Post-NL", "PostNL"),
        ("Evri 2", "Evri2"),
    ],
)
def test_class_prefix_keeps_the_carrier_capitalisation(name, expected):
    assert class_prefix(name) == expected


def test_class_prefix_rejects_a_nameless_name():
    with pytest.raises(SystemExit):
        class_prefix("--")


@pytest.mark.parametrize(
    "name,text,expected",
    [
        ("Cainiao", "an Cainiao parcel", "a Cainiao parcel"),
        ("Evri", "a Evri parcel", "an Evri parcel"),
        ("Cainiao", "An Cainiao parcel", "A Cainiao parcel"),
        ("Cainiao", "a Cainiao parcel", "a Cainiao parcel"),
        # Only the article directly before the name moves.
        ("Cainiao", "a box and an Cainiao parcel", "a box and a Cainiao parcel"),
    ],
)
def test_fix_articles(name, text, expected):
    assert fix_articles(text, name) == expected


# ---------------------------------------------------------------------------


def test_copy_tree_leaves_local_state_behind(tmp_path):
    """Local state must never reach a generated carrier.

    ``.claude/`` in particular: it appears the moment anyone runs Claude Code
    in the template, and it carries machine-local settings and skills.
    """
    src = tmp_path / "src"
    (src / ".claude" / "skills").mkdir(parents=True)
    (src / ".claude" / "settings.local.json").write_text("{}")
    (src / "skills-lock.json").write_text('{"version": 1}')
    (src / "__pycache__").mkdir()
    (src / ".ruff_cache").mkdir()
    (src / "custom_components").mkdir()
    (src / "custom_components" / "const.py").write_text("DOMAIN = 'x'\n")
    (src / "docs").mkdir()
    (src / ".DS_Store").write_text("junk")

    dst = tmp_path / "dst"
    dst.mkdir()
    copy_tree(src, dst, skip_template_only=True)

    assert {path.name for path in dst.iterdir()} == {"custom_components"}
    assert (dst / "custom_components" / "const.py").read_text() == "DOMAIN = 'x'\n"


def test_copy_tree_skips_template_only_at_the_root_only(tmp_path):
    """A nested ``docs/`` belongs to the carrier; the root one is the template's."""
    src = tmp_path / "src"
    (src / "docs").mkdir(parents=True)
    (src / "docs" / "template.md").write_text("template")
    (src / "custom_components" / "docs").mkdir(parents=True)
    (src / "custom_components" / "docs" / "carrier.md").write_text("carrier")

    dst = tmp_path / "dst"
    dst.mkdir()
    copy_tree(src, dst, skip_template_only=True)

    assert not (dst / "docs").exists()
    assert (dst / "custom_components" / "docs" / "carrier.md").read_text() == "carrier"


def test_generated_repo_wires_its_domain_into_the_suite_automation(tmp_path):
    """The carrier repo only supplies its domain; the workflows live in ``.github``.

    A domain that fails to substitute would silently test, cover and release the
    wrong package, and nothing else in the generated repo would notice.
    """
    args = argparse.Namespace(
        name="Testy Post",
        domain="testy_post",
        slug="ha-testy-post",
        manufacturer="Testy Post",
        auth="none",
    )
    out = tmp_path / "ha-testy-post"
    generate(args, out)

    suite = json.loads((out / ".github" / "suite.json").read_text())
    assert suite == {
        "kind": "integration",
        "domain": "testy_post",
        "research_api_path": "carrier-research/testy_post/api/",
    }

    for name in ("validate.yml", "release.yml"):
        workflow = (out / ".github" / "workflows" / name).read_text()
        assert "domain: testy_post" in workflow
        assert "example_carrier" not in workflow
        assert "ha-parcel-integrations/.github/.github/workflows/" in workflow

    # The policy check reads this pointer out of CLAUDE.md.
    assert suite["research_api_path"] in (out / "CLAUDE.md").read_text()
