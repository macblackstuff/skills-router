"""Nightly judge (U11, R11): outcome logs -> Jev Scores -> descriptor tuning.

Scan: per KTD6/KTD10, <state_dir>/telemetry/turns.jsonl names the sessions
that had routed turns (injection_count > 0); the matching
<state_dir>/sessions/<sid>.jsonl turn entries carry prompt + injected ids.
Usage heuristic (session-settled, 17A): an injected capability counts as
USED when a later prompt in the same session references its name or id.

Judge: one jev.ask call with a Score question per routed turn (a turn with
injections), judging outcome quality from the turn state + usage evidence.

Tune: capabilities injected >= MIN_INJECTIONS times, never referenced, with
avg score below DESCRIPTOR_FLOOR get a trigger_terms proposal — terms the
user actually typed on turns where the router fired. Proposals land as TOML
sidecars in <state_dir>/tuning/<capability_id>.toml:

    capability_id = "..."
    [[override]]
    field = "trigger_terms"
    old = "..."
    new = "..."
    rationale = "..."

The catalog is derived-only (R13): the judge never writes rows. The final
step reruns the indexer, which merges tuning/*.toml into rows at index time
— so a recreate migration (catalog.db deleted and rebuilt) never loses
tuning: it lives in files, not in the database. Every change is appended to
<state_dir>/judge.log.

CLI: python3 -m router.judge --config <path>   (nightly launchd chain,
scripts/bootstrap.py registers it before `router.cli capture`).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from router import indexer, jev
from router.catalog import Catalog
from router.config import ConfigError, RouterConfig

TUNING_REL = "tuning"
LOG_NAME = "judge.log"
SCORE_QID = "turn_outcome"
SCORE_QUESTION = {
    "type": "score",
    "instructions": (
        "Score how well this routed turn turned out: the router injected the "
        "listed capabilities into the agent turn — did the outcome look like "
        "the right call (1.0 = clearly useful injection, 0.0 = wrong or "
        "ignored injection)?"
    ),
}
MIN_INJECTIONS = 2       # min injections before a capability is tunable
DESCRIPTOR_FLOOR = 0.4   # avg score below this (never-used) -> proposal
MAX_TERMS = 3            # new trigger terms proposed per night
MIN_TERM_LEN = 4
STOPWORDS = frozenset(
    "this that with from have just want need please then when what into "
    "them they been were some also only over than very your will would "
    "there their about after before could should using used make made "
    "does done work working turn turns next help".split()
)
_TERM_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")
_REFERENCED_NOTE = "referenced by later turns: "


class JudgeError(Exception):
    pass


@dataclass
class CapStat:
    capability_id: str
    injected_n: int = 0
    used_n: int = 0
    scores: list[float] = field(default_factory=list)

    @property
    def avg_score(self) -> float | None:
        return sum(self.scores) / len(self.scores) if self.scores else None


@dataclass(frozen=True)
class Proposal:
    capability_id: str
    field: str
    old: str
    new: str
    rationale: str


@dataclass
class JudgeReport:
    sessions_scanned: int = 0
    turns_scored: int = 0
    ask_errors: int = 0
    stats: dict = field(default_factory=dict)  # id -> CapStat
    proposals: list = field(default_factory=list)  # list[Proposal]
    fingerprint: str | None = None  # catalog fingerprint after the rerun


# -- scan: telemetry + session traces --------------------------------------------

def _routed_sessions(state_dir: Path) -> list[str]:
    """Session ids from telemetry with at least one routed (injected) turn."""
    path = state_dir / "telemetry" / "turns.jsonl"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    seen: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        try:
            n = int(rec.get("injection_count") or 0)
        except (TypeError, ValueError):
            n = 0
        sid = rec.get("session")
        if n > 0 and sid and str(sid) not in seen:
            seen.append(str(sid))
    return seen


def _session_entries(state_dir: Path, session_id: str) -> list[dict]:
    """Per-turn entries for a session; corrupt/blank lines skipped (KTD4)."""
    safe = str(session_id).replace("/", "_").replace("\\", "_")
    path = state_dir / "sessions" / f"{safe}.jsonl"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    entries: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def _catalog_names(catalog_path: Path) -> dict:
    """{id: row} over every typed table; missing catalog -> {} (no names)."""
    if not catalog_path.is_file():
        return {}
    cat = Catalog(catalog_path)
    try:
        out: dict = {}
        tables = [
            r[0]
            for r in cat.rows(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        ]
        for t in tables:
            if t in ("relations", "meta"):
                continue
            try:
                cols = [c[1] for c in cat.db.execute(f"PRAGMA table_info({t})")]
            except Exception:  # noqa: BLE001 — skip unreadable tables
                continue
            for rec in cat.rows(f"SELECT * FROM {t}"):
                row = dict(zip(cols, rec))
                out[str(row.get("id"))] = row
        return out
    except Exception:  # noqa: BLE001 — a broken catalog must not kill the night
        return {}
    finally:
        cat.close()


def _referenced(text: str, cap_id: str, name: str | None) -> bool:
    """Usage heuristic: later prompt mentions the capability name or id."""
    low = str(text).lower()
    if cap_id and cap_id.lower() in low:
        return True
    if name:
        n = name.lower().strip()
        if len(n) >= 3 and n in low:
            return True
    return False


def _usage_later(entries: list[dict], idx: int, cap_id: str, name: str | None) -> bool:
    """Did any later turn of the same session reference this capability?"""
    return any(
        _referenced(e.get("prompt") or "", cap_id, name)
        for e in entries[idx + 1:]
    )


# -- judge: one Score per routed turn ---------------------------------------------

def _turn_state(entry: dict, entries: list[dict], idx: int, caps: dict) -> str:
    injected = [str(i) for i in (entry.get("injected") or [])]
    lines = [f"PROMPT:\n{entry.get('prompt') or ''}", "", "INJECTED CAPABILITIES:"]
    lines += [f"- {rid} (name: {(caps.get(rid) or {}).get('name') or '?'})" for rid in injected]
    lines += ["", "USAGE EVIDENCE (same-session later turns):"]
    for rid in injected:
        name = (caps.get(rid) or {}).get("name")
        used = _usage_later(entries, idx, rid, name)
        lines.append(f"- {rid}: {_REFERENCED_NOTE}{'yes' if used else 'no'}")
    return "\n".join(lines)


def _score_turn(ask_fn, state: str) -> float:
    """One jev.ask Score call; raises on failure (caller counts and continues)."""
    answers = ask_fn(state, {SCORE_QID: dict(SCORE_QUESTION)})
    answer = answers[SCORE_QID]
    if not isinstance(answer, jev.Score):
        raise JudgeError(f"answer for {SCORE_QID!r} is not a Score")
    return float(answer.score)


# -- tune: proposals from per-capability stats -------------------------------------

def _prompt_terms(prompts: list[str], exclude: str) -> list[str]:
    """Frequent non-stopword terms from prompts, not already covered."""
    exclude_low = exclude.lower()
    counts: dict[str, int] = {}
    for prompt in prompts:
        for term in _TERM_RE.findall(str(prompt).lower()):
            if len(term) < MIN_TERM_LEN or term in STOPWORDS:
                continue
            if term in exclude_low:  # already in name/description/triggers
                continue
            counts[term] = counts.get(term, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [t for t, _ in ranked[:MAX_TERMS]]


def _propose(stats: dict, caps: dict, prompts_by_cap: dict) -> list[Proposal]:
    out: list[Proposal] = []
    for cid in sorted(stats):
        st = stats[cid]
        avg = st.avg_score
        row = caps.get(cid) or {}
        if st.injected_n < MIN_INJECTIONS or st.used_n > 0:
            continue
        if avg is None or avg >= DESCRIPTOR_FLOOR:
            continue
        old = str(row.get("trigger_terms") or "")
        exclude = " ".join(
            str(row.get(k) or "") for k in ("id", "name", "description", "trigger_terms")
        )
        terms = _prompt_terms(prompts_by_cap.get(cid, []), exclude)
        if not terms:
            continue
        new = f"{old} {' '.join(terms)}".strip()
        rationale = (
            f"nightly judge: injected {st.injected_n}x, never referenced by "
            f"later turns, avg Jev score {avg:.2f} < {DESCRIPTOR_FLOOR}; "
            f"added user-typed terms {', '.join(terms)}"
        )
        out.append(Proposal(cid, "trigger_terms", old, new, rationale))
    return out


# -- sidecar TOML + log --------------------------------------------------------------

def _toml_str(v: str) -> str:
    """Basic TOML string; JSON escaping is TOML-1.0 compatible for these cases."""
    return json.dumps(str(v), ensure_ascii=False)


def _write_tuning(tuning_dir: Path, proposal: Proposal) -> Path:
    tuning_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", proposal.capability_id)
    path = tuning_dir / f"{safe}.toml"
    body = (
        f"capability_id = {_toml_str(proposal.capability_id)}\n"
        f"\n[[override]]\n"
        f"field = {_toml_str(proposal.field)}\n"
        f"old = {_toml_str(proposal.old)}\n"
        f"new = {_toml_str(proposal.new)}\n"
        f"rationale = {_toml_str(proposal.rationale)}\n"
    )
    path.write_text(body, encoding="utf-8")
    return path


def _log(state_dir: Path, message: str) -> None:
    """Append to <state_dir>/judge.log; never fatal."""
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        with (state_dir / LOG_NAME).open("a", encoding="utf-8") as fh:
            fh.write(
                f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {message}\n"
            )
    except OSError:
        pass


# -- orchestration --------------------------------------------------------------------

def _default_index_run(config: RouterConfig, config_path: Path | str | None):
    if config_path is not None:
        custom = indexer.load_custom_sources(config_path)
    else:
        custom = {}
    return indexer.run_index(config, custom_sources=custom)


def run_judge(
    config: RouterConfig,
    config_path: Path | str | None = None,
    ask_fn=jev.ask,
    index_fn=None,
) -> JudgeReport:
    """One nightly run; never raises for per-turn issues (logged and counted)."""
    state_dir = config.state_path()
    report = JudgeReport()
    _log(state_dir, f"judge run start (state_dir={state_dir})")

    sessions = _routed_sessions(state_dir)
    report.sessions_scanned = len(sessions)
    caps = _catalog_names(config.state_path("catalog.db"))
    if not sessions:
        _log(state_dir, "no routed turns in telemetry — no-op night")
        return report

    stats: dict = {}
    prompts_by_cap: dict = {}
    for sid in sessions:
        entries = _session_entries(state_dir, sid)
        if not entries:
            continue
        for idx, entry in enumerate(entries):
            injected = [str(i) for i in (entry.get("injected") or [])]
            if not injected:
                continue  # only routed turns carry an outcome to judge
            state = _turn_state(entry, entries, idx, caps)
            try:
                score = _score_turn(ask_fn, state)
            except Exception as e:  # noqa: BLE001 — JevError or mock raising
                report.ask_errors += 1
                _log(state_dir, f"ask failed for session {sid} turn {idx}: "
                                f"{type(e).__name__}: {e}")
                continue
            report.turns_scored += 1
            prompt = str(entry.get("prompt") or "")
            for rid in injected:
                st = stats.setdefault(rid, CapStat(rid))
                st.injected_n += 1
                st.scores.append(score)
                prompts_by_cap.setdefault(rid, []).append(prompt)
                name = (caps.get(rid) or {}).get("name")
                if _usage_later(entries, idx, rid, name):
                    st.used_n += 1
    report.stats = stats

    report.proposals = _propose(stats, caps, prompts_by_cap)
    for p in report.proposals:
        _write_tuning(state_dir / TUNING_REL, p)
        _log(state_dir, f"tuning written: {p.capability_id} {p.field}: "
                        f"{p.old!r} -> {p.new!r} ({p.rationale})")

    if report.proposals or report.turns_scored:
        run = index_fn() if index_fn is not None else _default_index_run(
            config, config_path
        )
        report.fingerprint = getattr(run, "fingerprint", None)
        _log(state_dir, f"index rerun done (fingerprint={report.fingerprint})")
    else:
        _log(state_dir, "nothing to tune and no scores — index not rerun")
    return report


# -- CLI --------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="router.judge",
        description="Nightly judge: score routed turns and write tuning sidecars.",
    )
    parser.add_argument("--config", default=indexer.DEFAULT_CONFIG,
                        help="router TOML config path")
    args = parser.parse_args(argv)

    config_path = Path(args.config).expanduser()
    try:
        config = RouterConfig.load(config_path)
        report = run_judge(config, config_path=config_path)
    except (ConfigError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    proposal_ids = ", ".join(p.capability_id for p in report.proposals) or "none"
    print(
        f"judge: sessions {report.sessions_scanned}, scored {report.turns_scored}, "
        f"ask errors {report.ask_errors}, proposals {len(report.proposals)} "
        f"({proposal_ids})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
