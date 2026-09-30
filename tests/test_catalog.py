"""U1 tests: typed catalog schema + config loader."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from router.catalog import CORE_TYPES, Catalog, core_columns
from router.config import RouterConfig, ConfigError


@pytest.fixture()
def cat(tmp_path):
    c = Catalog(tmp_path / "catalog.db")
    yield c
    c.close()


def test_schema_creates_all_nine_type_tables(cat):
    names = {r[0] for r in cat.rows("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in CORE_TYPES:
        assert t in names, t
    assert "relations" in names


def test_core_contract_columns_present(cat):
    for t in CORE_TYPES:
        cols = {r[1] for r in cat.rows(f"PRAGMA table_info({t})")}
        for col in core_columns():
            assert col.split()[0] in cols, (t, col)


def test_relations_table_shape(cat):
    cols = {r[1] for r in cat.rows("PRAGMA table_info(relations)")}
    assert cols == {"from_id", "to_id", "kind"}


def test_custom_type_auto_creates_with_core_contract(cat):
    cat.ensure_type("checklist")
    cols = {r[1] for r in cat.rows("PRAGMA table_info(checklist)")}
    for col in core_columns():
        assert col.split()[0] in cols


def test_insert_and_upsert_row(cat):
    cat.ensure_type("skill")
    cat.upsert("skill", {"id": "pricing", "name": "pricing", "enabled": 1})
    assert cat.count("skill") == 1
    cat.upsert("skill", {"id": "pricing", "name": "pricing v2", "enabled": 1})
    assert cat.count("skill") == 1
    assert cat.rows("SELECT name FROM skill")[0][0] == "pricing v2"


def test_fingerprint_changes_on_write_and_is_stable_when_idle(cat):
    f1 = cat.fingerprint()
    cat.ensure_type("skill")
    cat.upsert("skill", {"id": "x", "name": "x", "enabled": 1})
    f2 = cat.fingerprint()
    assert f1 != f2
    assert f2 == cat.fingerprint()


def test_wal_mode(cat, tmp_path):
    mode = cat.rows("PRAGMA journal_mode")[0][0]
    assert mode == "wal"


def test_config_roundtrip(tmp_path):
    p = tmp_path / "router.toml"
    p.write_text(
        'routing_enabled = true\n'
        'capture_mode = "review"\n'
        '[sources]\n'
        'skill_dirs = ["/a", "/b"]\n'
    )
    cfg = RouterConfig.load(p)
    assert cfg.routing_enabled is True
    assert cfg.capture_mode == "review"
    assert cfg.skill_dirs == ["/a", "/b"]


def test_config_defaults(tmp_path):
    p = tmp_path / "router.toml"
    p.write_text("")
    cfg = RouterConfig.load(p)
    assert cfg.routing_enabled is True
    assert cfg.capture_mode == "review"


def test_missing_config_errors_cleanly(tmp_path):
    with pytest.raises(ConfigError):
        RouterConfig.load(tmp_path / "nope.toml")
