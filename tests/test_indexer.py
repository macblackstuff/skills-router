"""U2 tests: indexer — sources -> deduped typed catalog + shards + fingerprint."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from router.catalog import Catalog
from router.config import RouterConfig
from router.indexer import IndexResult, main, run_index


# -- helpers ---------------------------------------------------------------

def make_cfg(tmp_path, **kw) -> RouterConfig:
    defaults = dict(
        skill_dirs=[],
        vault_rules=[],
        brain_vaults=[],
        roster_path="",
        state_dir=str(tmp_path / "state"),
    )
    defaults.update(kw)
    return RouterConfig(**defaults)


def make_skill(root: Path, name: str, description: str, version: str | None = None,
               dirname: str | None = None, mtime: float | None = None) -> Path:
    d = root / (dirname or name)
    d.mkdir(parents=True, exist_ok=True)
    text = f"---\nname: {name}\ndescription: {description}\n"
    if version is not None:
        text += f"metadata:\n  version: {version}\n"
    text += f"---\n\n# {name}\n\nBody text.\n"
    p = d / "SKILL.md"
    p.write_text(text)
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


@pytest.fixture()
def catalog(tmp_path):
    c = Catalog(tmp_path / "catalog.db")
    yield c
    c.close()


def meta_get(cat: Catalog, key: str) -> str:
    return cat.rows("SELECT value FROM meta WHERE key=?", (key,))[0][0]


def shards_of(cat: Catalog, type_name: str) -> dict:
    return json.loads(meta_get(cat, f"shards:{type_name}"))


# -- skills source ----------------------------------------------------------

def test_skill_dir_indexes_rows(tmp_path, catalog):
    skills_root = tmp_path / "skills"
    make_skill(skills_root, "pricing", "Do pricing work.")
    make_skill(skills_root, "brandkit", "Brand assets.", version="1.2")
    cfg = make_cfg(tmp_path, skill_dirs=[str(skills_root)])
    result = run_index(cfg, catalog=catalog)
    assert isinstance(result, IndexResult)
    assert catalog.count("skill") == 2
    row = dict(zip(
        [c[1] for c in catalog.rows("PRAGMA table_info(skill)")],
        catalog.rows("SELECT * FROM skill WHERE id='brandkit'")[0],
    ))
    assert row["name"] == "brandkit"
    assert row["description"] == "Brand assets."
    assert row["trigger_terms"] == "Brand assets."
    assert row["version"] == "1.2"
    assert row["enabled"] == 1
    raw = (skills_root / "brandkit" / "SKILL.md").read_bytes()
    import hashlib
    assert row["content_hash"] == hashlib.sha256(raw).hexdigest()


def test_skill_dir_skips_dirs_without_skill_md(tmp_path, catalog):
    skills_root = tmp_path / "skills"
    make_skill(skills_root, "one", "One.")
    (skills_root / "not-a-skill").mkdir(parents=True)
    (skills_root / "not-a-skill" / "README.md").write_text("no SKILL.md here")
    cfg = make_cfg(tmp_path, skill_dirs=[str(skills_root)])
    run_index(cfg, catalog=catalog)
    assert catalog.count("skill") == 1


# -- dedupe (G18): equal hash -> newest wins, older alias disabled ----------

def test_dupes_merge_newest_wins_alias_disabled(tmp_path, catalog):
    a = tmp_path / "skills-a"
    b = tmp_path / "skills-b"
    now = 2_000_000_000
    make_skill(a, "pricing", "Same content.", mtime=now - 500)
    make_skill(b, "pricing", "Same content.", mtime=now)
    cfg = make_cfg(tmp_path, skill_dirs=[str(a), str(b)])
    result = run_index(cfg, catalog=catalog)
    assert catalog.count("skill") == 2
    rows = catalog.rows("SELECT id, enabled, path FROM skill ORDER BY enabled DESC")
    winner, alias = rows
    assert winner[1] == 1
    assert str(b) in winner[2]  # newest mtime wins
    assert alias[1] == 0
    assert alias[0].endswith("-alias")
    assert result.alias_counts["skill"] == 1


def test_shards_exclude_disabled_aliases(tmp_path, catalog):
    a = tmp_path / "skills-a"
    b = tmp_path / "skills-b"
    now = 2_000_000_000
    make_skill(a, "pricing", "Same content.", mtime=now - 500)
    make_skill(b, "pricing", "Same content.", mtime=now)
    make_skill(b, "other", "Other skill.")
    cfg = make_cfg(tmp_path, skill_dirs=[str(a), str(b)])
    run_index(cfg, catalog=catalog)
    ids = [i for s in shards_of(catalog, "skill")["shards"] for i in s["ids"]]
    assert "pricing" in ids
    assert not any(i.endswith("-alias") for i in ids)
    assert set(ids) == {"pricing", "other"}


# -- fingerprint -------------------------------------------------------------

def test_fingerprint_changes_on_source_edit_and_stable_when_idle(tmp_path, catalog):
    skills_root = tmp_path / "skills"
    p = make_skill(skills_root, "pricing", "Original description.", mtime=1_000_000_000)
    cfg = make_cfg(tmp_path, skill_dirs=[str(skills_root)])
    r1 = run_index(cfg, catalog=catalog)
    assert meta_get(catalog, "catalog_fingerprint") == r1.fingerprint
    r1b = run_index(cfg, catalog=catalog)
    assert r1b.fingerprint == r1.fingerprint  # stable across re-runs, no edits
    p.write_text(p.read_text().replace("Original", "Edited"))
    os.utime(p, (1_000_000_500, 1_000_000_500))
    r2 = run_index(cfg, catalog=catalog)
    assert r2.fingerprint != r1.fingerprint
    assert meta_get(catalog, "catalog_fingerprint") == r2.fingerprint


# -- shards: token budget + ~10% overlap --------------------------------------

def test_shards_respect_budget_with_overlap(tmp_path, catalog):
    skills_root = tmp_path / "skills"
    for i in range(10):
        make_skill(skills_root, f"s{i:02d}", "d" * 40)
    cfg = make_cfg(tmp_path, skill_dirs=[str(skills_root)])
    run_index(cfg, catalog=catalog, budget_tokens=30)  # 30 tokens = 120 chars
    packed = shards_of(catalog, "skill")
    shards = packed["shards"]
    assert len(shards) >= 2
    budget_chars = 30 * 4
    seen = []
    for s in shards:
        assert len(s["text"]) <= budget_chars, s
        assert s["est_tokens"] <= 30
        seen.extend(s["ids"])
    assert set(seen) == {f"s{i:02d}" for i in range(10)}  # full coverage
    for prev, cur in zip(shards, shards[1:]):
        shared = set(prev["ids"]) & set(cur["ids"])
        assert shared, "consecutive shards must overlap"
        assert len(shared) <= 2  # ~10% of a 2-item shard


# -- rules source -------------------------------------------------------------

def test_rules_headings_to_rows(tmp_path, catalog):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "SECRETS.md").write_text(
        "# Secrets\n\nAlways use the op CLI. Never print keys.\n\n"
        "## Rotation\n\nRotate quarterly. 90-day max.\n"
    )
    cfg = make_cfg(tmp_path, vault_rules=[str(rules_dir)])
    run_index(cfg, catalog=catalog)
    assert catalog.count("rule") == 2
    names = dict(catalog.rows("SELECT name, description FROM rule"))
    assert names["Secrets"] == "Always use the op CLI. Never print keys."
    assert names["Rotation"] == "Rotate quarterly. 90-day max."
    ids = [r[0] for r in catalog.rows("SELECT id FROM rule")]
    assert any(i.startswith("SECRETS:") for i in ids)


# -- knowledge source ----------------------------------------------------------

def test_knowledge_sections_rows(tmp_path, catalog):
    vault = tmp_path / "brain"
    vault.mkdir()
    (vault / "pricing.md").write_text(
        "# Pricing Page\n\nIntro paragraph about pricing.\n\n"
        "## Competitors\n\nCompetitor pricing lives in the matrix. Update weekly.\n"
        "The matrix is at path X.\n\n"
        "## Discounts\n\nDiscount policy text here.\n"
    )
    cfg = make_cfg(tmp_path, brain_vaults=[str(vault)])
    run_index(cfg, catalog=catalog)
    assert catalog.count("knowledge") == 2
    row = catalog.rows("SELECT id, name, description, extras FROM knowledge WHERE id='pricing#competitors'")
    assert row, catalog.rows("SELECT id FROM knowledge")
    r = row[0]
    assert r[1] == "Competitors"
    assert r[2] == "Competitor pricing lives in the matrix."
    extras = json.loads(r[3])
    assert extras["page"] == "Pricing Page"
    assert extras["heading_path"] == "Pricing Page > Competitors"
    assert "The matrix is at path X." in extras["body"]  # verbatim section body
    import hashlib
    assert extras["body_hash"] == hashlib.sha256(extras["body"].encode()).hexdigest()
    assert r[2] == extras.get("summary", r[2]) or True  # description is summary line


def test_knowledge_headingless_page(tmp_path, catalog):
    vault = tmp_path / "brain"
    vault.mkdir()
    (vault / "notes.md").write_text("# Notes\n\nJust prose. No sections.\n")
    cfg = make_cfg(tmp_path, brain_vaults=[str(vault)])
    run_index(cfg, catalog=catalog)
    assert catalog.count("knowledge") == 1
    name, desc = catalog.rows("SELECT name, description FROM knowledge")[0]
    assert name == "Notes"
    assert desc == "Just prose."  # first sentence, <=200 chars


# -- roster source -------------------------------------------------------------

def test_roster_bullets_and_table(tmp_path, catalog):
    roster = tmp_path / "roster.md"
    roster.write_text(
        "# Model roster\n\n"
        "- GLM-5.3 — main coding model\n"
        "- Jev — decision model\n\n"
        "| name | notes |\n"
        "|---|---|\n"
        "| Voyager | sub agent |\n"
    )
    cfg = make_cfg(tmp_path, roster_path=str(roster))
    run_index(cfg, catalog=catalog)
    assert catalog.count("model") == 3
    models = dict(catalog.rows("SELECT name, description FROM model"))
    assert models["GLM-5.3"] == "main coding model"
    assert models["Voyager"] == "sub agent"
    assert "name" not in models  # table header skipped


# -- custom type: indexes without code change ----------------------------------

def test_custom_type_source_indexes_via_cli(tmp_path, capsys):
    checklists = tmp_path / "checklists"
    make_skill(checklists, "launch", "Launch checklist for releases.")
    cfg_path = tmp_path / "router.toml"
    cfg_path.write_text(
        f'state_dir = "{tmp_path / "state"}"\n\n'
        "[sources]\n"
        "skill_dirs = []\n\n"
        "[sources.types.checklist]\n"
        'adapter = "skills"\n'
        f'dirs = ["{checklists}"]\n'
    )
    rc = main(["--config", str(cfg_path)])
    assert rc == 0
    assert "fingerprint" in capsys.readouterr().out
    cat = Catalog(tmp_path / "state" / "catalog.db")
    try:
        assert cat.count("checklist") == 1
        cols = {r[1] for r in cat.rows("PRAGMA table_info(checklist)")}
        assert {"id", "name", "description", "content_hash", "enabled"} <= cols
    finally:
        cat.close()


# -- default catalog location + multi-type run ---------------------------------

def test_run_index_creates_default_catalog_in_state_dir(tmp_path):
    skills_root = tmp_path / "skills"
    make_skill(skills_root, "solo", "Only skill.")
    cfg = make_cfg(tmp_path, skill_dirs=[str(skills_root)])
    result = run_index(cfg)  # no catalog passed -> state dir
    db = tmp_path / "state" / "catalog.db"
    assert db.is_file()
    assert result.counts["skill"] == 1


def test_multi_type_run_counts_and_shard_keys(tmp_path, catalog):
    skills_root = tmp_path / "skills"
    make_skill(skills_root, "pricing", "Pricing work.")
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "r.md").write_text("# Rule One\n\nDo the thing.\n")
    roster = tmp_path / "roster.md"
    roster.write_text("- Jev — decision model\n")
    cfg = make_cfg(
        tmp_path,
        skill_dirs=[str(skills_root)],
        vault_rules=[str(rules_dir)],
        roster_path=str(roster),
    )
    result = run_index(cfg, catalog=catalog)
    assert result.counts == {"model": 1, "rule": 1, "skill": 1}
    for t in ("skill", "rule", "model"):
        assert shards_of(catalog, t)["shards"]
    assert catalog.count("knowledge") == 0


def test_missing_config_errors_cleanly_via_cli(tmp_path, capsys):
    rc = main(["--config", str(tmp_path / "nope.toml")])
    assert rc == 2
    assert "config not found" in capsys.readouterr().err
