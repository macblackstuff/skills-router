"""U8 tests: knowledge_inject — verbatim section bodies, drift guard, budget.

Covers AE2: given Jev selected a knowledge section, the section text lands
verbatim in the injection. Fixtures index real markdown via run_index so
extras JSON comes from the actual indexer adapter.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from router.catalog import Catalog
from router.config import RouterConfig
from router.indexer import run_index
from router.knowledge import BODY_CHAR_BUDGET, TRUNCATION_MARKER, knowledge_inject

# -- fixtures -----------------------------------------------------------------

PRICING_MD = (
    "# Pricing Page\n\n"
    "Intro paragraph about pricing.\n\n"
    "## Competitor pricing\n\n"
    "Competitor pricing lives in the matrix.\n"
    "The matrix is at path X.\n\n"
    "## Discounts\n\n"
    "Discount policy text.\n"
)
NOTES_MD = "# Notes\n\nJust prose. No sections here.\nMore prose.\n"
LONG_MD = "# Long Page\n\n## Big section\n\n" + ("lorem ipsum " * 600)


@pytest.fixture()
def catalog(tmp_path):
    c = Catalog(tmp_path / "catalog.db")
    yield c
    c.close()


def index_vault(tmp_path, catalog, files: dict[str, str]) -> None:
    vault = tmp_path / "brain"
    vault.mkdir(exist_ok=True)
    for name, text in files.items():
        (vault / name).write_text(text)
    cfg = RouterConfig(
        skill_dirs=[], vault_rules=[], brain_vaults=[str(vault)],
        roster_path="", state_dir=str(tmp_path / "state"),
    )
    run_index(cfg, catalog=catalog)


def corrupt_body_hash(catalog, rid: str) -> None:
    (extras_raw,) = catalog.rows(
        "SELECT extras FROM knowledge WHERE id = ?", (rid,)
    )[0]
    extras = json.loads(extras_raw)
    extras["body_hash"] = "0" * 64  # not sha256(body) by construction
    catalog.db.execute(
        "UPDATE knowledge SET extras = ? WHERE id = ?",
        (json.dumps(extras), rid),
    )
    catalog.db.commit()


# -- scenarios ------------------------------------------------------------------

def test_matching_section_injected_verbatim(tmp_path, catalog):
    """Covers AE2: Jev-selected section text appears verbatim in the turn."""
    index_vault(tmp_path, catalog, {"pricing.md": PRICING_MD})
    lines = knowledge_inject(["knowledge:pricing#competitor-pricing"], catalog)

    expected = (
        "=== [knowledge] Pricing Page — Competitor pricing ===\n"
        "## Competitor pricing\n\n"
        "Competitor pricing lives in the matrix.\n"
        "The matrix is at path X."
    )
    assert lines == [expected]


def test_headingless_page_injected(tmp_path, catalog):
    index_vault(tmp_path, catalog, {"notes.md": NOTES_MD})
    lines = knowledge_inject(["knowledge:notes#page"], catalog)

    expected = (
        "=== [knowledge] Notes ===\n"
        "# Notes\n\n"
        "Just prose. No sections here.\n"
        "More prose."
    )
    assert lines == [expected]


def test_body_hash_mismatch_skips_with_stale_notice(tmp_path, catalog):
    index_vault(tmp_path, catalog, {"pricing.md": PRICING_MD})
    corrupt_body_hash(catalog, "pricing#competitor-pricing")

    lines = knowledge_inject(
        ["knowledge:pricing#competitor-pricing", "knowledge:pricing#discounts"],
        catalog,
    )
    assert lines == [
        "knowledge stale: pricing#competitor-pricing — run router index",
        "=== [knowledge] Pricing Page — Discounts ===\n"
        "## Discounts\n\n"
        "Discount policy text.",
    ]


def test_truncation_at_char_budget(tmp_path, catalog):
    index_vault(tmp_path, catalog, {"long.md": LONG_MD})
    body = "## Big section\n\n" + "lorem ipsum " * 600
    body = body[:-1].strip("\n")  # match indexer's trailing-newline strip

    lines = knowledge_inject(["knowledge:long#big-section"], catalog)
    expected = (
        "=== [knowledge] Long Page — Big section ===\n"
        + body[:BODY_CHAR_BUDGET] + TRUNCATION_MARKER
    )
    assert lines == [expected]
    injected_body = lines[0].split("\n", 1)[1]
    assert len(injected_body) == BODY_CHAR_BUDGET + len(TRUNCATION_MARKER)
    assert injected_body.startswith(body[:BODY_CHAR_BUDGET])


def test_non_knowledge_and_missing_ids_ignored(tmp_path, catalog):
    index_vault(tmp_path, catalog, {"pricing.md": PRICING_MD})
    winners = [
        "skill:pricing",                 # other type: pointer path's job, not ours
        "knowledge:nope#missing",        # not in the table
        "knowledge:pricing#discounts",   # real knowledge row
        "pricing#competitor-pricing",    # bare id form still resolves
    ]
    lines = knowledge_inject(winners, catalog)
    assert len(lines) == 2
    assert lines[0].startswith("=== [knowledge] Pricing Page — Discounts ===")
    assert lines[1].startswith("=== [knowledge] Pricing Page — Competitor pricing ===")
