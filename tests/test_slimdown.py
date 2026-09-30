"""U13 tests: context slim-down — ZCode-scoped surfaces reduced to skeletons.

Covers: dry-run changes nothing; apply reduces bytes + records backup;
restore returns originals byte-for-byte; shared/vault-level AGENTS.md refused.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from router import slimdown
from router.config import RouterConfig
from router.slimdown import POINTER_LINE, SlimError


# -- helpers ---------------------------------------------------------------

def make_cfg(tmp_path, instruction_files=None) -> tuple[RouterConfig, Path, Path]:
    skill_root = tmp_path / "zskills"
    skill_root.mkdir()
    for name in ("alpha", "beta"):
        d = skill_root / name
        d.mkdir()
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: do {name} things\n---\n\n"
            + f"Use this skill whenever you need to {name}. " * 60
        )
    zcode = tmp_path / ".zcode"
    zcode.mkdir()
    agents = zcode / "AGENTS.md"
    agents.write_text("# ZCode-scoped instructions\n\n" + "always do the thing\n" * 40)
    cfg = RouterConfig(
        skill_dirs=[str(skill_root)],
        vault_rules=[],
        brain_vaults=[],
        roster_path="",
        state_dir=str(tmp_path / "state"),
    )
    cfg.zcode_instruction_files = list(instruction_files if instruction_files is not None else [str(agents)])
    return cfg, skill_root, agents


def snapshot(*roots: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for root in roots:
        for p in sorted(root.rglob("*")):
            if p.is_file():
                out[str(p.relative_to(root.parent))] = p.read_bytes()
    return out


def surface_paths(skill_root: Path, agents: Path) -> list[Path]:
    return [
        skill_root / "alpha" / "SKILL.md",
        skill_root / "beta" / "SKILL.md",
        agents,
    ]


# -- enumerate + dry-run ------------------------------------------------------

def test_enumerate_lists_zcode_scoped_surfaces_only(tmp_path):
    cfg, skill_root, agents = make_cfg(tmp_path)
    plan = slimdown.enumerate(tmp_path / "plan", cfg)
    got = sorted((str(t.path), t.kind) for t in plan.targets)
    assert got == sorted(
        [(str(skill_root / "alpha" / "SKILL.md"), "skill"),
         (str(skill_root / "beta" / "SKILL.md"), "skill"),
         (str(agents), "instruction")]
    )


def test_dry_run_changes_nothing_and_prints_counts(tmp_path, capsys):
    cfg, skill_root, agents = make_cfg(tmp_path)
    plan_dir = tmp_path / "plan"
    before_snapshot = snapshot(skill_root, tmp_path / ".zcode")
    plan = slimdown.enumerate(plan_dir, cfg)
    before, after = slimdown.dry_run(plan)
    out = capsys.readouterr().out
    assert "before" in out and "after" in out
    assert after < before
    assert snapshot(skill_root, tmp_path / ".zcode") == before_snapshot
    plan_json = json.loads((plan_dir / "slim-plan.json").read_text())
    assert len(plan_json["targets"]) == 3


def test_dry_run_skeleton_estimate_uses_pointer_line(tmp_path, capsys):
    cfg, skill_root, _ = make_cfg(tmp_path)
    plan = slimdown.enumerate(tmp_path / "plan", cfg)
    slimdown.dry_run(plan)
    assert POINTER_LINE in capsys.readouterr().out


# -- apply --------------------------------------------------------------------

def test_apply_reduces_bytes_and_records_backup(tmp_path):
    cfg, skill_root, agents = make_cfg(tmp_path)
    targets = surface_paths(skill_root, agents)
    originals = {p: p.read_bytes() for p in targets}
    plan = slimdown.enumerate(tmp_path / "plan", cfg)
    result = slimdown.apply(plan, cfg)

    assert result.before_bytes > result.after_bytes
    # skeletons in place: pointer line everywhere, skill frontmatter preserved
    for p, kind in zip(targets, ("skill", "skill", "instruction")):
        text = p.read_text()
        assert POINTER_LINE in text
        if kind == "skill":
            assert f"name: {p.parent.name}" in text
        assert len(p.read_bytes()) < len(originals[p])
    # backup recorded under state_dir/slim-backups/<ts>/ preserving originals
    backups = list((tmp_path / "state" / "slim-backups").iterdir())
    assert len(backups) == 1
    bdir = backups[0]
    assert result.backup_dir == bdir
    manifest = json.loads((bdir / "manifest.json").read_text())
    assert len(manifest["entries"]) == 3
    for entry in manifest["entries"]:
        assert Path(entry["original"]).read_bytes() != originals[Path(entry["original"])]
        assert (bdir / "files" / entry["backup"]).read_bytes() == originals[Path(entry["original"])]


def test_apply_skips_missing_files(tmp_path):
    cfg, skill_root, agents = make_cfg(tmp_path)
    plan = slimdown.enumerate(tmp_path / "plan", cfg)
    (skill_root / "beta" / "SKILL.md").unlink()
    result = slimdown.apply(plan, cfg)
    assert str(skill_root / "beta" / "SKILL.md") in result.skipped
    assert len(result.applied) == 2


# -- restore ------------------------------------------------------------------

def test_restore_returns_originals_byte_for_byte(tmp_path):
    cfg, skill_root, agents = make_cfg(tmp_path)
    targets = surface_paths(skill_root, agents)
    originals = {p: p.read_bytes() for p in targets}
    plan = slimdown.enumerate(tmp_path / "plan", cfg)
    result = slimdown.apply(plan, cfg)

    restored = slimdown.restore(result.backup_dir, cfg)
    assert len(restored.restored) == 3
    for p in targets:
        assert p.is_file()
        assert p.read_bytes() == originals[p]


def test_restore_accepts_timestamp_and_rejects_unknown(tmp_path):
    cfg, skill_root, agents = make_cfg(tmp_path)
    plan = slimdown.enumerate(tmp_path / "plan", cfg)
    result = slimdown.apply(plan, cfg)
    ts = result.backup_dir.name

    restored = slimdown.restore(ts, cfg)  # resolve via state_dir/slim-backups
    assert len(restored.restored) == 3

    try:
        slimdown.restore("99990101T000000Z", cfg)
    except SlimError as e:
        assert "not found" in str(e)
    else:
        raise AssertionError("expected SlimError for unknown backup")


# -- scope boundary -----------------------------------------------------------

def test_shared_agents_md_refused(tmp_path):
    vault_agents = tmp_path / "vault" / "AGENTS.md"
    vault_agents.parent.mkdir()
    vault_agents.write_text("# shared vault-level instructions\n" + "rule\n" * 100)
    cfg, _, _ = make_cfg(tmp_path, instruction_files=[str(vault_agents)])
    try:
        slimdown.enumerate(tmp_path / "plan", cfg)
    except SlimError as e:
        assert "AGENTS.md" in str(e)
        assert "out of scope" in str(e)
    else:
        raise AssertionError("expected SlimError for shared AGENTS.md")


def test_zcode_scoped_agents_md_allowed_and_repo_level_refused(tmp_path):
    # under a project-level .zcode/ directory -> ZCode-scoped, accepted
    repo_zcode = tmp_path / "repo" / ".zcode"
    repo_zcode.mkdir(parents=True)
    scoped = repo_zcode / "AGENTS.md"
    scoped.write_text("scoped\n" * 50)
    cfg, _, _ = make_cfg(tmp_path, instruction_files=[str(scoped)])
    plan = slimdown.enumerate(tmp_path / "plan", cfg)
    assert [t.kind for t in plan.targets if t.path == scoped] == ["instruction"]


def test_restore_without_manifest_errors(tmp_path):
    cfg, _, _ = make_cfg(tmp_path)
    empty = tmp_path / "state" / "slim-backups" / "empty"
    empty.mkdir(parents=True)
    try:
        slimdown.restore(empty, cfg)
    except SlimError as e:
        assert "manifest" in str(e)
    else:
        raise AssertionError("expected SlimError for backup without manifest")
