"""U9 tests: plugin/agent/memory/MCP source adapters, AGENTS.md -> rule rows,
custom [sources.types.<name>] wiring, roster auto-discovery flags."""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from router.catalog import Catalog
from router.config import RouterConfig
from router.indexer import IndexerError, load_custom_sources, main, run_index
from router.sources import agents as agents_source
from router.sources import mcp as mcp_source
from router.sources import memories as memories_source
from router.sources import plugins as plugins_source
from router.sources import roster as roster_source
from router.sources import rules as rules_source


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


# -- plugins adapter ----------------------------------------------------------

def test_plugins_adapter_parses_fixture(tmp_path):
    root = tmp_path / "plugins"
    pdir = root / "git-helper"
    pdir.mkdir(parents=True)
    text = (
        "---\nname: git-helper\ndescription: Safe git helpers.\n"
        "metadata:\n  version: 2.0\n---\n\nBody.\n"
    )
    raw = text.encode()
    (pdir / "plugin.md").write_bytes(raw)
    (root / "not-a-plugin").mkdir()
    (root / "not-a-plugin" / "README.md").write_text("no plugin.md here")
    rows = plugins_source.iter_rows([str(root)])
    assert len(rows) == 1
    r = rows[0]
    assert r["id"] == "git-helper"
    assert r["name"] == "git-helper"
    assert r["description"] == "Safe git helpers."
    assert r["trigger_terms"] == "Safe git helpers."
    assert r["version"] == "2.0"
    assert r["content_hash"] == hashlib.sha256(raw).hexdigest()
    assert r["path"] == str(pdir / "plugin.md")
    assert r["source"] == str(root)
    assert json.loads(r["extras"])["dir"] == "git-helper"
    assert r["enabled"] == 1


# -- agents adapter -----------------------------------------------------------

def test_agents_adapter_parses_fixture(tmp_path):
    root = tmp_path / "agents"
    root.mkdir(parents=True)
    text = (
        "---\nname: reviewer\ndescription: Reviews diffs before merge.\n"
        "model: inherit\ntools: read, grep\n---\n\nYou review code.\n"
    )
    raw = text.encode()
    (root / "reviewer.md").write_bytes(raw)
    (root / "plain.md").write_text("Fallback agent.\n\nDoes things.\n")
    rows = agents_source.iter_rows([str(root)])
    by_id = {r["id"]: r for r in rows}
    assert set(by_id) == {"reviewer", "plain"}
    r = by_id["reviewer"]
    assert r["name"] == "reviewer"
    assert r["description"] == "Reviews diffs before merge."
    assert r["version"] is None
    ex = json.loads(r["extras"])
    assert ex["model"] == "inherit"
    assert ex["tools"] == ["read", "grep"]
    assert r["path"] == str(root / "reviewer.md")
    assert r["content_hash"] == hashlib.sha256(raw).hexdigest()
    p = by_id["plain"]
    assert p["name"] == "plain"
    assert p["description"] == "Fallback agent."


# -- memories adapter ---------------------------------------------------------

def test_memories_adapter_parses_fixture(tmp_path):
    root = tmp_path / "memories"
    nested = root / "2026"
    nested.mkdir(parents=True)
    text = "# Prefers tables\n\nUser prefers tables over prose.\n"
    raw = text.encode()
    (nested / "style.md").write_bytes(raw)
    rows = memories_source.iter_rows([str(root)])
    assert len(rows) == 1
    r = rows[0]
    assert r["id"] == "style"
    assert r["name"] == "Prefers tables"
    assert r["description"] == "User prefers tables over prose."
    assert r["trigger_terms"] == "User prefers tables over prose."
    assert r["content_hash"] == hashlib.sha256(raw).hexdigest()
    assert r["path"] == str(nested / "style.md")
    assert r["source"] == str(nested)
    assert json.loads(r["extras"])["topic"] == "Prefers tables"


# -- mcp adapter --------------------------------------------------------------

def test_mcp_adapter_parses_fixture(tmp_path):
    root = tmp_path / "mcp"
    root.mkdir(parents=True)
    cfgfile = root / "mcp.json"
    raw = json.dumps({"mcpServers": {
        "github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]},
        "docs": {"url": "https://docs.example/mcp", "description": "Docs search."},
    }}).encode()
    cfgfile.write_bytes(raw)
    (root / "broken.json").write_text("{not json")
    rows = mcp_source.iter_rows([str(root)])
    by_id = {r["id"]: r for r in rows}
    assert set(by_id) == {"github", "docs"}
    g = by_id["github"]
    assert g["name"] == "github"
    assert g["description"] == "npx -y @modelcontextprotocol/server-github"
    assert json.loads(g["extras"])["transport"] == "stdio"
    assert g["path"] == str(cfgfile)
    d = by_id["docs"]
    assert d["description"] == "Docs search."
    assert json.loads(d["extras"])["transport"] == "http"


# -- AGENTS.md sections -> rule rows ------------------------------------------

def test_agents_md_sections_become_rule_rows(tmp_path):
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text(
        "## Always land work immediately\n\nCommit and push as each change lands.\n\n"
        "## Never push secrets\n\nKeep credentials in 1Password.\n"
    )
    rows = rules_source.iter_rows([str(agents_md)])
    assert [r["name"] for r in rows] == [
        "Always land work immediately",
        "Never push secrets",
    ]
    assert rows[0]["description"] == "Commit and push as each change lands."
    assert rows[0]["id"] == "AGENTS:always-land-work-immediately"
    catalog = Catalog(tmp_path / "cat.db")
    try:
        cfg = make_cfg(tmp_path, vault_rules=[str(agents_md)])
        run_index(cfg, catalog=catalog)
        assert catalog.count("rule") == 2
    finally:
        catalog.close()


# -- custom types end-to-end via TOML ------------------------------------------

def test_custom_types_via_toml_end_to_end(tmp_path):
    proot = tmp_path / "plugins"
    pdir = proot / "templater"
    pdir.mkdir(parents=True)
    (pdir / "plugin.md").write_text(
        "---\nname: templater\ndescription: Templates.\n---\n\nBody.\n"
    )
    aroot = tmp_path / "agents"
    aroot.mkdir()
    (aroot / "scout.md").write_text(
        "---\nname: scout\ndescription: Finds files.\n---\n\nFind.\n"
    )
    mroot = tmp_path / "memories"
    mroot.mkdir()
    (mroot / "tone.md").write_text("# Tone\n\nBe terse.\n")
    jroot = tmp_path / "mcp"
    jroot.mkdir()
    (jroot / "mcp.json").write_text(json.dumps({"mcpServers": {"fs": {"command": "mcp-fs"}}}))

    toml = tmp_path / "router.toml"
    toml.write_text(f"""
state_dir = '{tmp_path / "state"}'

[sources.types.plugin]
adapter = "plugins"
dirs = ['{proot}']

[sources.types.agent]
adapter = "agents"
dirs = ['{aroot}']

[sources.types.memory]
adapter = "memories"
dirs = ['{mroot}']

[sources.types.mcp]
adapter = "mcp"
dirs = ['{jroot}']

[sources.types.vendor_note]
adapter = "memories"
dirs = ['{mroot}']
""")

    custom = load_custom_sources(str(toml))
    assert set(custom) == {"plugin", "agent", "memory", "mcp", "vendor_note"}
    assert {r["id"] for r in custom["plugin"]} == {"templater"}
    assert {r["id"] for r in custom["agent"]} == {"scout"}
    assert {r["id"] for r in custom["mcp"]} == {"fs"}
    assert {r["id"] for r in custom["vendor_note"]} == {"tone"}

    assert main(["--config", str(toml)]) == 0
    catalog = Catalog(tmp_path / "state" / "catalog.db")
    try:
        assert catalog.count("plugin") == 1
        assert catalog.count("agent") == 1
        assert catalog.count("memory") == 1
        assert catalog.count("mcp") == 1
        assert catalog.count("vendor_note") == 1
    finally:
        catalog.close()


def test_unknown_adapter_rejected(tmp_path):
    toml = tmp_path / "router.toml"
    toml.write_text('[sources.types.thing]\nadapter = "nope"\ndirs = []\n')
    with pytest.raises(IndexerError):
        load_custom_sources(str(toml))


# -- roster auto-discovery ------------------------------------------------------

def test_roster_names_helper(tmp_path):
    roster = tmp_path / "roster.md"
    roster.write_text("- GLM-4.6 — primary routing model\n| Voyager | sub-agent |\n")
    assert roster_source.names(str(roster)) == ["GLM-4.6", "Voyager"]


def test_discovery_flags_unknown_model_on_index(tmp_path):
    roster = tmp_path / "roster.md"
    roster.write_text("- GLM-4.6 — primary routing model\n- jev-latest — judge\n")
    state = tmp_path / "state"
    sess = state / "sessions"
    sess.mkdir(parents=True)
    (sess / "chat.jsonl").write_text(
        '{"role":"user","content":"ask gpt-4o about the deadline"}\n'
        '{"role":"assistant","content":"GLM-4.6 routed this turn"}\n'
    )
    catalog = Catalog(tmp_path / "cat.db")
    try:
        run_index(make_cfg(tmp_path, roster_path=str(roster)), catalog=catalog)
    finally:
        catalog.close()
    flags_path = state / "captures" / "roster_flags.jsonl"
    lines = [json.loads(l) for l in flags_path.read_text().splitlines() if l.strip()]
    assert {e["model"] for e in lines} == {"gpt-4o"}
    assert lines[0]["count"] == 1
    assert lines[0]["transcript"].endswith("chat.jsonl")
    # idempotent: a second index run does not duplicate the flag
    catalog = Catalog(tmp_path / "cat.db")
    try:
        run_index(make_cfg(tmp_path, roster_path=str(roster)), catalog=catalog)
    finally:
        catalog.close()
    assert len(flags_path.read_text().splitlines()) == 1


def test_discovery_scan_direct_and_no_roster(tmp_path):
    from router import discovery

    cfg = make_cfg(tmp_path, roster_path="")
    assert discovery.scan(cfg) == []  # no roster configured -> no-op, no file
    assert not (tmp_path / "state" / "captures" / "roster_flags.jsonl").exists()

    roster = tmp_path / "roster.md"
    roster.write_text("- gpt-4o — known model\n")
    sess = tmp_path / "state" / "sessions"
    sess.mkdir(parents=True)
    (sess / "t.txt").write_text(
        "switch to claude-opus-4 then back, no claude-opus-4 again; gpt-4o is known\n"
    )
    cfg2 = make_cfg(tmp_path, roster_path=str(roster))
    flags = discovery.scan(cfg2, roster_names=["gpt-4o"])
    assert [f["model"] for f in flags] == ["claude-opus-4"]
    assert flags[0]["count"] == 2
    flags_path = tmp_path / "state" / "captures" / "roster_flags.jsonl"
    assert flags_path.is_file()
    # roster_names=None derives from config.roster_path; rerun is idempotent
    assert discovery.scan(cfg2) == []
    assert len(flags_path.read_text().splitlines()) == 1
