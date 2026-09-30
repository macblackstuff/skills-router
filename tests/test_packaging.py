"""U12 tests: packaging + bootstrap + auto-push.

Packaging unit (KTD9) — these are install/runtime smoke tests driven through
subprocesses against a temp HOME, not unit coverage of router internals:

- bootstrap on a clean clone registers the UserPromptSubmit hook block
  (shape reused from hook.zcode_hook_config) and builds the catalog;
- --remove restores the exact pre-bootstrap ZCode config snapshot;
- nightly launchd registration is a no-op when declined, writes the plist
  when asked (launchctl load skipped in tests via --no-load);
- scripts/post-commit is a clean no-op with no git remote (exercised through
  a git shim on PATH — no real git commands are run);
- skills/router/router_runtime.py resolves the repo src/ package and errors
  cleanly when the package is absent.
"""
import json
import os
import plistlib
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from router.sources.skills import parse_frontmatter  # noqa: E402

BOOTSTRAP = REPO / "scripts" / "bootstrap.py"
RUNTIME = REPO / "skills" / "router" / "router_runtime.py"
POST_COMMIT = REPO / "scripts" / "post-commit"
SNAPSHOT_SUFFIX = ".router-snapshot"
FINGERPRINT_KEY = "catalog_fingerprint"
TIMEOUT = 180


def bootstrap_env(home: Path, extra_path: str = "") -> dict:
    path = f"{extra_path}:{os.environ['PATH']}" if extra_path else os.environ["PATH"]
    return {**os.environ, "HOME": str(home), "PATH": path}


def run_bootstrap(home: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(BOOTSTRAP), *args],
        env=bootstrap_env(home),
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )


def read_zcode_config(home: Path) -> dict:
    return json.loads((home / ".zcode/cli/config.json").read_text())


def router_entries(home: Path) -> list[dict]:
    events = read_zcode_config(home)["hooks"]["events"]
    return [e for e in events.get("UserPromptSubmit", []) if "router.hook" in e.get("command", "")]


# -- git shim (no real git commands are run in this suite) -----------------------

GIT_SHIM = """#!/bin/sh
case "$1" in
  remote)
    if [ -n "$SHIM_REMOTE" ]; then echo "$SHIM_REMOTE"; fi
    exit 0 ;;
  push)
    echo "push $*" >> "$SHIM_LOG"
    exit 0 ;;
esac
exit 0
"""


@pytest.fixture
def git_shim(tmp_path: Path) -> Path:
    """A fake `git` earlier on PATH. SHIM_REMOTE empty => no remote configured."""
    bindir = tmp_path / "shim-bin"
    bindir.mkdir()
    shim = bindir / "git"
    shim.write_text(GIT_SHIM)
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    return bindir


def run_post_commit(cwd: Path, shim_bin: Path, home: Path, shim_remote: str = ""):
    log = cwd / "pushlog"
    env = bootstrap_env(home, extra_path=str(shim_bin))
    env["SHIM_LOG"] = str(log)
    env["SHIM_REMOTE"] = shim_remote
    proc = subprocess.run(
        ["/bin/sh", str(POST_COMMIT)], cwd=cwd, env=env,
        capture_output=True, text=True, timeout=60,
    )
    pushes = log.read_text().splitlines() if log.exists() else []
    return proc, pushes


# -- bootstrap: clean clone -------------------------------------------------------

def test_bootstrap_clean_clone_registers_hook_and_builds_catalog(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    proc = run_bootstrap(home, "--nightly", "no")
    assert proc.returncode == 0, proc.stderr

    # hook block registered under UserPromptSubmit, command + timeoutMs present
    entries = router_entries(home)
    assert len(entries) == 1
    entry = entries[0]
    assert "python3 -m router.hook --config" in entry["command"]
    # timeoutMs >= Jev timeout + margin (KTD4): default 30s timeout -> >= 45s floor
    assert entry["timeoutMs"] >= 45_000
    assert entry["timeoutMs"] >= 30_000 + 15_000

    # snapshot of the pre-edit config written next to it
    assert Path(str(home / ".zcode/cli/config.json") + SNAPSHOT_SUFFIX).is_file()

    # router config created
    assert (home / ".config/router/router.toml").is_file()

    # first index built the catalog: db exists with a fingerprint row
    db = home / ".local/state/router/catalog.db"
    assert db.is_file()
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = ?", (FINGERPRINT_KEY,)
        ).fetchone()
    assert row and row[0], "catalog fingerprint missing after bootstrap index"

    # bootstrap printed the config diff
    assert "router.hook" in proc.stdout

    # nightly declined -> no launchd plist
    assert not (home / "Library/LaunchAgents/com.skills-router.judge.plist").exists()

    # full cycle: remove restores the clean-clone state (no config.json at all)
    zcfg = home / ".zcode/cli/config.json"
    proc = run_bootstrap(home, "--remove")
    assert proc.returncode == 0, proc.stderr
    assert not zcfg.exists()
    assert not Path(str(zcfg) + SNAPSHOT_SUFFIX).exists()


def test_bootstrap_is_idempotent(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    run_bootstrap(home, "--nightly", "no")
    run_bootstrap(home, "--nightly", "no")
    assert len(router_entries(home)) == 1


def test_bootstrap_preserves_unrelated_hook_entries(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    zcfg = home / ".zcode/cli/config.json"
    zcfg.parent.mkdir(parents=True)
    zcfg.write_text(json.dumps({
        "hooks": {"events": {"SessionStart": [{"command": "echo hi", "timeoutMs": 1000}]}}
    }))
    run_bootstrap(home, "--nightly", "no")
    cfg = read_zcode_config(home)
    assert cfg["hooks"]["events"]["SessionStart"] == [
        {"command": "echo hi", "timeoutMs": 1000}
    ]
    assert len(cfg["hooks"]["events"]["UserPromptSubmit"]) == 1


def test_bootstrap_remove_restores_snapshot(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    zcfg = home / ".zcode/cli/config.json"
    zcfg.parent.mkdir(parents=True)
    original = json.dumps({"model": "jev-latest", "hooks": {"events": {}}})
    zcfg.write_text(original)

    run_bootstrap(home, "--nightly", "no")
    assert len(router_entries(home)) == 1
    assert zcfg.read_text() != original  # hook was added

    proc = run_bootstrap(home, "--remove")
    assert proc.returncode == 0, proc.stderr
    assert zcfg.read_text() == original  # exact snapshot restore
    assert not Path(str(zcfg) + SNAPSHOT_SUFFIX).exists()
    assert read_zcode_config(home)["hooks"]["events"].get("UserPromptSubmit", []) == []


def test_bootstrap_remove_also_removes_plist(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    run_bootstrap(home, "--nightly", "yes", "--no-load")
    plist = home / "Library/LaunchAgents/com.skills-router.judge.plist"
    assert plist.is_file()
    run_bootstrap(home, "--remove", "--no-load")  # --no-load: never touch real launchd
    assert not plist.exists()


# -- nightly launchd registration --------------------------------------------------

def test_bootstrap_nightly_declined_is_noop(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    proc = run_bootstrap(home, "--nightly", "no")
    assert proc.returncode == 0
    assert not (home / "Library/LaunchAgents").exists()


def test_bootstrap_nightly_writes_plist_without_load(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    proc = run_bootstrap(home, "--nightly", "yes", "--no-load")
    assert proc.returncode == 0, proc.stderr
    plist_path = home / "Library/LaunchAgents/com.skills-router.judge.plist"
    assert plist_path.is_file()
    with plist_path.open("rb") as fh:
        plist = plistlib.load(fh)
    assert plist["Label"] == "com.skills-router.judge"
    args = plist["ProgramArguments"]
    assert args[0] == "/bin/sh" and args[1] == "-c"
    chain = args[2]
    judge_at = chain.index("python3 -m router.judge")
    capture_at = chain.index("python3 -m router.cli capture")
    assert judge_at < capture_at  # judge first, then capture drainer
    cal = plist["StartCalendarInterval"]
    assert 0 <= cal["Hour"] <= 23 and 0 <= cal["Minute"] <= 59
    assert plist["EnvironmentVariables"]["PYTHONPATH"] == str(REPO / "src")


# -- post-commit auto-push (shimmed git; no real git commands) ----------------------

def test_post_commit_no_remote_is_clean_noop(tmp_path, git_shim):
    home = tmp_path / "home"
    home.mkdir()
    proc, pushes = run_post_commit(tmp_path, git_shim, home, shim_remote="")
    assert proc.returncode == 0
    assert proc.stdout == "" and proc.stderr == ""
    assert pushes == []  # nothing pushed when no remote


def test_post_commit_pushes_when_remote_set(tmp_path, git_shim):
    home = tmp_path / "home"
    home.mkdir()
    proc, pushes = run_post_commit(tmp_path, git_shim, home, shim_remote="origin")
    assert proc.returncode == 0
    assert len(pushes) == 1 and "origin" in pushes[0]


# -- skills/router wrapper + runtime loader ----------------------------------------

def test_skill_md_frontmatter_matches_router_schema():
    text = (REPO / "skills/router/SKILL.md").read_text()
    fm = parse_frontmatter(text)
    assert fm.get("name") == "router"
    assert fm.get("description")


def test_runtime_loader_runs_router_cli(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    run_bootstrap(home, "--nightly", "no")
    cfg = home / ".config/router/router.toml"
    proc = subprocess.run(
        [sys.executable, str(RUNTIME), "status", "--config", str(cfg)],
        env=bootstrap_env(home), capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "fingerprint" in proc.stdout  # status output reached through the stub


def test_runtime_loader_without_package_fails_cleanly(tmp_path):
    detached = tmp_path / "detached" / "skills" / "router"
    detached.mkdir(parents=True)
    (detached / "router_runtime.py").write_text(
        (REPO / "skills/router/router_runtime.py").read_text()
    )
    proc = subprocess.run(
        [sys.executable, str(detached / "router_runtime.py"), "status"],
        env=bootstrap_env(tmp_path), capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 1
    assert "router" in proc.stderr.lower()
