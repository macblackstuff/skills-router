"""U15 capture drainer (KTD11, R13/F5): queued learnings -> drafted files.

Drains ``<state_dir>/captures/pending.jsonl`` (U14 queue lines:
``{ts, session, kind, payload, turn_context}``). Each candidate is judged by
ONE jev.ask call carrying one Score question ("capture_worth"); acceptance is
``score >= 0.8`` (ACCEPT_THRESHOLD), below discards with the rationale logged
to ``<state_dir>/captures/drainer.log``.

Modes (config.capture_mode, KTD5/KTD11 — review is the shipped default):
- review: drafts land under ``<state_dir>/captures/drafts/<type>/``; the
  source tree is never written and no reindex runs.
- auto: drafts land in the router-owned captured-sources root
  ``<repo>/sources/captured/<type>/`` (default_captured_root, overridable via
  the ``captured_root`` argument), and the indexer's run reindexes after any
  apply — the catalog stays derived-only (R13).

Every processed candidate (accepted or discarded) is ledgered by content-hash
to ``<state_dir>/captures/drained.jsonl``; later drains skip ledgered hashes,
so a discarded capture is never re-judged and a Jev failure (which ledgeres
nothing) is retried on the next drain. pending.jsonl is never rewritten —
append-only from the capture side; the ledger is the dedupe bookkeeping.

Drafts are written via temp-file + os.replace rename (atomic, same
directory). Kind -> draft shape:
- skill:    <root>/skill/<slug>/SKILL.md frontmatter stub
- rule:     <root>/rule/<slug>.md  "# Title" + body section
- model:    <root>/model/captured-models.md  "- Name — description" line
- learning: <root>/learning/<slug>.md note (same section shape as rule)
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from router import indexer, jev
from router.config import ConfigError, RouterConfig
from router.indexer import IndexerError
from router.jev import JevError, Score
from router.sources.rules import slug

PENDING_REL = ("captures", "pending.jsonl")
DRAINED_REL = ("captures", "drained.jsonl")
DRAFTS_REL = ("captures", "drafts")
LOG_REL = ("captures", "drainer.log")

ACCEPT_THRESHOLD = 0.8
WORTH_QID = "capture_worth"
WORTH_QUESTION = {
    "type": "score",
    "instructions": (
        "Score how worthwhile it is to permanently capture this candidate "
        "learning as a routable capability, rule, or roster entry "
        "(0.0 = worthless one-off noise, 1.0 = clearly worth keeping)."
    ),
}

_KIND_ALIASES = {"roster": "model"}


class DrainError(Exception):
    pass


@dataclass
class DrainResult:
    judged: int = 0
    accepted: int = 0
    discarded: int = 0
    duplicates: int = 0
    drafts: list[Path] = field(default_factory=list)
    reindexed: bool = False
    error: str | None = None


# -- helpers ------------------------------------------------------------------------

def default_captured_root() -> Path:
    """Router-owned captured-sources root inside the repo (KTD11)."""
    return Path(__file__).resolve().parents[2] / "sources" / "captured"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _first_line(text: str) -> str:
    for line in text.splitlines():
        line = " ".join(line.split())
        if line:
            return line
    return ""


def _title(text: str, limit_words: int = 8) -> str:
    line = _first_line(text).rstrip(".!?")
    words = line.split() or ["captured"]
    return " ".join(words[:limit_words])


def _atomic_write(path: Path, text: str) -> None:
    """Write via temp file in the target directory + os.replace rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _free_path(path: Path) -> Path:
    if not path.exists():
        return path
    n = 2
    while True:
        cand = path.with_name(f"{path.stem}-{n}{path.suffix}")
        if not cand.exists():
            return cand
        n += 1


def _log(config: RouterConfig, **fields: object) -> None:
    parts = [f"{_now()}"] + [f"{k}={v}" for k, v in fields.items()]
    path = config.state_path(*LOG_REL)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(" ".join(parts) + "\n")


# -- queue + ledger -------------------------------------------------------------------

def _read_entries(pending: Path) -> list[tuple[dict | None, str]]:
    out: list[tuple[dict | None, str]] = []
    for raw in pending.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw)
        except ValueError:
            entry = None
        out.append((entry if isinstance(entry, dict) else None, raw))
    return out


def _load_drained(path: Path) -> set[str]:
    hashes: set[str] = set()
    if not path.is_file():
        return hashes
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("hash"):
            hashes.add(str(record["hash"]))
    return hashes


def _mark_drained(config: RouterConfig, h: str, kind: str, disposition: str,
                  score: float | None, draft: Path | None) -> None:
    record: dict = {"ts": _now(), "hash": h, "kind": kind, "disposition": disposition}
    if score is not None:
        record["score"] = round(score, 4)
    if draft is not None:
        record["draft"] = str(draft)
    path = config.state_path(*DRAINED_REL)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _entry_text(entry: dict) -> str:
    payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
    text = str(payload.get("text") or entry.get("text") or "").strip()
    return " ".join(text.split())


def _normalize_kind(entry: dict) -> str:
    kind = str(entry.get("kind") or "learning").strip().lower()
    return _KIND_ALIASES.get(kind, kind if kind in ("skill", "rule", "model", "learning") else "learning")


def _candidate_state(entry: dict, text: str) -> str:
    ctx = entry.get("turn_context") if isinstance(entry.get("turn_context"), dict) else {}
    lines = [
        "A capture candidate was flagged during a routed agent turn.",
        f"kind: {entry.get('kind') or 'learning'}",
        f"session: {entry.get('session') or 'unknown'}",
    ]
    prompt = str(ctx.get("prompt") or "").strip()
    if prompt:
        lines.append(f"turn prompt: {prompt}")
    injections = ctx.get("injections")
    if isinstance(injections, list) and injections:
        lines.append("injected: " + "; ".join(str(i) for i in injections))
    lines.append(f"candidate: {text}")
    return "\n".join(lines)


# -- draft builders ---------------------------------------------------------------------

def _draft_skill(root: Path, entry: dict, text: str) -> Path:
    payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
    name = str(payload.get("name") or _title(text))
    target = _free_path(root / "skill" / slug(name)) / "SKILL.md"
    body = (
        "---\n"
        f"name: {name}\n"
        f"description: {_first_line(text)}\n"
        "metadata:\n"
        "  version: 0.1.0\n"
        "  source: capture\n"
        "---\n\n"
        f"{text}\n"
    )
    _atomic_write(target, body)
    return target


def _draft_rule(root: Path, entry: dict, text: str) -> Path:
    payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
    title = str(payload.get("name") or _title(text))
    target = _free_path(root / "rule" / f"{slug(title)}.md")
    _atomic_write(target, f"# {title}\n\n{text}\n")
    return target


def _draft_model(root: Path, entry: dict, text: str) -> Path:
    payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
    models = [str(m).strip() for m in (payload.get("models") or []) if str(m).strip()]
    names = models or [str(payload.get("name") or _title(text))]
    target = root / "model" / "captured-models.md"
    existing = target.read_text(encoding="utf-8") if target.exists() else "# Captured models\n"
    if existing and not existing.endswith("\n"):
        existing += "\n"
    lines = [f"- {name} — {text}" for name in names]
    _atomic_write(target, existing + "\n".join(lines) + "\n")
    return target


def _draft_learning(root: Path, entry: dict, text: str) -> Path:
    payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
    title = str(payload.get("name") or _title(text))
    target = _free_path(root / "learning" / f"{slug(title)}.md")
    _atomic_write(target, f"# {title}\n\n{text}\n")
    return target


_DRAFTERS = {
    "skill": _draft_skill,
    "rule": _draft_rule,
    "model": _draft_model,
    "learning": _draft_learning,
}


# -- default reindex (auto mode) -----------------------------------------------------------

def _default_index_run(config: RouterConfig, config_path: Path | str | None):
    if config_path is not None:
        custom = indexer.load_custom_sources(config_path)
    else:
        custom = {}
    return indexer.run_index(config, custom_sources=custom)


# -- drain ------------------------------------------------------------------------------------

def drain(
    config: RouterConfig,
    ask=None,
    captured_root: Path | str | None = None,
    config_path: Path | str | None = None,
    index_run=None,
) -> DrainResult:
    """Judge and draft every not-yet-drained pending capture.

    ask defaults to jev.ask (resolved at call time so tests can mock
    ``drainer.jev.ask``). index_run defaults to the indexer's run over
    ``config`` (custom sources loaded from ``config_path`` when given).
    """
    result = DrainResult()
    pending = config.state_path(*PENDING_REL)
    if not pending.is_file():
        return result

    ask_fn = ask if ask is not None else jev.ask
    auto = config.capture_mode == "auto"
    if auto:
        root = Path(captured_root).expanduser() if captured_root else default_captured_root()
    else:
        root = config.state_path(*DRAFTS_REL)
    drained_hashes = _load_drained(config.state_path(*DRAINED_REL))

    for entry, raw in _read_entries(pending):
        if entry is None:
            _log(config, decision="malformed-line", raw=raw.strip()[:120])
            continue
        text = _entry_text(entry)
        if not text:
            _log(config, decision="skipped", reason="empty candidate text")
            continue
        h = content_hash(text)
        if h in drained_hashes:
            result.duplicates += 1
            _log(config, decision="duplicate", hash=h[:12], text=text[:80])
            continue

        kind = _normalize_kind(entry)
        try:
            answers = ask_fn(_candidate_state(entry, text), {WORTH_QID: WORTH_QUESTION})
        except JevError as e:
            # nothing ledgered: the candidate is retried on the next drain
            result.error = f"Jev judging failed: {e}"
            _log(config, decision="error", error=str(e), text=text[:80])
            return result
        answer = answers.get(WORTH_QID)
        if not isinstance(answer, Score):
            result.error = f"capture-worth answer is {type(answer).__name__}, not a Score"
            _log(config, decision="error", error=result.error, text=text[:80])
            return result

        result.judged += 1
        if answer.score >= ACCEPT_THRESHOLD:
            draft = _DRAFTERS[kind](root, entry, text)
            result.accepted += 1
            result.drafts.append(draft)
            _mark_drained(config, h, kind, "accepted", answer.score, draft)
            drained_hashes.add(h)  # dedupe identical candidates within one drain
            _log(config, decision="accepted", kind=kind, score=f"{answer.score:.2f}",
                 draft=draft)
        else:
            result.discarded += 1
            _mark_drained(config, h, kind, "discarded", answer.score, None)
            drained_hashes.add(h)
            _log(
                config,
                decision="discarded",
                kind=kind,
                score=f"{answer.score:.2f}",
                rationale=f"score {answer.score:.2f} below accept threshold {ACCEPT_THRESHOLD}",
                text=text[:80],
            )

    if result.accepted and auto:
        try:
            if index_run is not None:
                index_run()
            else:
                _default_index_run(config, config_path)
            result.reindexed = True
        except (IndexerError, ConfigError, OSError) as e:
            result.error = f"reindex after capture apply failed: {e}"
            _log(config, decision="error", error=str(e))
    return result
