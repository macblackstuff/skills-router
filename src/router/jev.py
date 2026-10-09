"""Jev client (KTD2): one-call access, typed answers, JSONL trace, redaction gate.

Adopted from jev-implementations `jev.py` shape. Stdlib only: urllib.request
for HTTP, subprocess for `op read` credential resolution. Every routing
decision is Jev's (R2); this module is I/O only.

TypeSafe data posture (checked 2026-09-30, https://docs.typesafe.ai/): their
docs state no retain/train commitment for data sent to the API — treat state
text as leaving the machine. The redaction gate below is the compensating
control.
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Union

API_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
DEFAULT_TIMEOUT_MS = 30_000
DEFAULT_CREDENTIAL_ENV = "JEV_API_KEY"
INPUT_COST_PER_1M = 0.042  # output tokens are free (fact sheet 02-jev-typesafe)

_MAX_RETRIES = 2  # extra attempts on 429/529, after the first
_RETRY_BACKOFF_S = 0.5  # doubles per retry; patched to 0 in tests

# Egress redaction gate (KTD2): regexes compiled once, scrubbed before state
# assembly; linear pass keeps the gate under the <5ms budget.
_REDACTED = "[REDACTED]"
_REDACT_PATTERNS = (
    re.compile(r"op://[a-z0-9]+(?:/[A-Za-z0-9_.-]+)+"),  # 1Password refs
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),  # OpenAI/Anthropic-style keys (hyphen-tolerant)
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key ids
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),  # GitHub tokens (ghp_/gho_/ghu_/ghs_/ghr_)
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),  # fine-grained GitHub PATs
    re.compile(r"glpat-[A-Za-z0-9_-]{15,}"),  # GitLab PATs
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),  # Slack tokens
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),  # Google API keys
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"),  # JWTs
    re.compile(r"[A-Za-z0-9+/]{40}(?![A-Za-z0-9+/])"),  # AWS secret access keys (40-char b64)
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----", re.DOTALL),
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),  # orphaned header
)


class JevError(Exception):
    """Any Jev API failure; consumed by the U5 blocking path."""


class JevTimeoutError(JevError):
    """Jev unreachable or slow past timeout_ms."""


@dataclass(frozen=True)
class Noul:
    p: float


@dataclass(frozen=True)
class Choice:
    choice: str
    probabilities: Dict[str, float]
    confidence: float


@dataclass(frozen=True)
class Score:
    score: float
    confidence: float


Answer = Union[Noul, Choice, Score]


def redact(text: str) -> str:
    """Replace credential-shaped substrings with [REDACTED]."""
    for pattern in _REDACT_PATTERNS:
        text = pattern.sub(_REDACTED, text)
    return text


def _redact_questions(questions: dict) -> dict:
    """Apply the egress gate to question instructions/criteria (shard text)."""
    out = {}
    for qid, spec in questions.items():
        if not isinstance(spec, dict):
            out[qid] = spec
            continue
        cleaned = dict(spec)
        if isinstance(cleaned.get("instructions"), str):
            cleaned["instructions"] = redact(cleaned["instructions"])
        criteria = cleaned.get("criteria")
        if isinstance(criteria, dict):
            cleaned["criteria"] = {
                k: redact(v) if isinstance(v, str) else v
                for k, v in criteria.items()
            }
        elif isinstance(criteria, list):
            cleaned["criteria"] = [
                redact(v) if isinstance(v, str) else v for v in criteria
            ]
        out[qid] = cleaned
    return out


# One credential resolution per process (review finding: up to 8 `op read`
# subprocesses per turn when resolved inside every ask).
@functools.lru_cache(maxsize=4)
def _resolve_credential_cached(ref: str) -> str:
    return resolve_credential(ref)


def resolve_credential(ref: str) -> str:
    """Resolve a credential reference to an API key; never echo the key.

    ref without "://" -> environment variable name.
    ref with "://" (op:// path) -> `op read` subprocess; key stays out of
    argv beyond the ref itself and out of every error message.
    """
    if not ref:
        raise JevError("credential_ref is empty (set env var name or op:// path in config)")
    if "://" in ref:
        # House rule: every op call goes through the with-creds wrapper, which
        # injects the service-account token; bare `op` has none and exits 1.
        wrapper = "/Users/work/.local/bin/with-creds"
        op_bin = "/opt/homebrew/bin/op"
        argv = ([wrapper, "--env", "OP_SERVICE_ACCOUNT_TOKEN", op_bin, "read", ref]
                if os.path.exists(wrapper) else [op_bin, "read", ref])
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=20
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            raise JevError(f"op read failed for credential ref ({type(e).__name__})") from e
        if proc.returncode != 0 or not proc.stdout.strip():
            raise JevError(f"op read exited {proc.returncode} for credential ref")
        return proc.stdout.strip()
    value = os.environ.get(ref, "")
    if not value:
        raise JevError(f"credential env var {ref!r} is not set")
    return value


def ask(
    state: str,
    questions: Dict[str, dict],
    timeout_ms: int | None = None,
    credential_ref: str | None = None,
    model: str = DEFAULT_MODEL,
    trace_path: Path | str | None = None,
) -> Dict[str, Answer]:
    """Send one systemone call carrying all questions; return typed answers.

    state passes the redaction gate before assembly; the trace stores a
    sha256 digest of the sent state, never the raw state. On success a
    JSONL line {ts, state_digest, questions, answers, usage, latency_ms,
    cost_usd} is appended to trace_path when given.
    """
    state = redact(state)
    timeout_ms = DEFAULT_TIMEOUT_MS if timeout_ms is None else timeout_ms
    api_key = _resolve_credential_cached(credential_ref or DEFAULT_CREDENTIAL_ENV)
    # Shard text rides inside question instructions/criteria — same egress
    # gate as state (review finding: secrets quoted in indexed sources).
    questions = _redact_questions(questions)
    body = {"state": state, "model": model, "questions": questions}

    started = time.monotonic()
    payload = _post_with_retry(body, api_key, timeout_ms / 1000.0)
    latency_ms = int((time.monotonic() - started) * 1000)

    answers = _parse_answers(payload)
    usage = payload.get("usage") or {}
    if trace_path is not None:
        _append_trace(
            trace_path,
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "state_digest": hashlib.sha256(state.encode("utf-8")).hexdigest(),
                "questions": questions,
                "answers": {qid: _answer_record(a) for qid, a in answers.items()},
                "usage": usage,
                "latency_ms": latency_ms,
                "cost_usd": usage.get("input_tokens", 0) / 1e6 * INPUT_COST_PER_1M,
            },
        )
    return answers


def _post_with_retry(body: dict, api_key: str, timeout_s: float) -> dict:
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    for attempt in range(_MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 529) and attempt < _MAX_RETRIES:
                time.sleep(_RETRY_BACKOFF_S * (2 ** attempt))
                continue
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:200]
            except Exception:
                pass
            raise JevError(f"Jev API HTTP {e.code}: {detail}") from e
        except TimeoutError as e:
            raise JevTimeoutError(f"Jev API timed out after {timeout_s:.3f}s") from e
        except urllib.error.URLError as e:
            if isinstance(getattr(e, "reason", None), TimeoutError):
                raise JevTimeoutError(f"Jev API timed out after {timeout_s:.3f}s") from e
            raise JevError(f"Jev API unreachable: {getattr(e, 'reason', e)!r}") from e
    raise JevError("Jev API retries exhausted")  # pragma: no cover


def _parse_answers(payload: dict) -> Dict[str, Answer]:
    raw_answers = payload.get("answers")
    if not isinstance(raw_answers, dict):
        raise JevError("Jev API response missing answers map")
    return {qid: _parse_answer(qid, raw) for qid, raw in raw_answers.items()}


def _parse_answer(qid: str, raw: object) -> Answer:
    try:
        if not isinstance(raw, dict):
            raise TypeError(f"answer is {type(raw).__name__}, not an object")
        kind = raw["type"]
        if kind == "noul":
            return Noul(p=float(raw["noul"]))
        if kind == "choice":
            return Choice(
                choice=str(raw["choice"]),
                probabilities={
                    str(k): float(v) for k, v in raw.get("probabilities", {}).items()
                },
                confidence=float(raw.get("confidence", 0.0)),
            )
        if kind == "score":
            return Score(score=float(raw["score"]), confidence=float(raw.get("confidence", 0.0)))
    except (KeyError, TypeError, ValueError) as e:
        raise JevError(f"malformed answer for question {qid!r}: {type(e).__name__}: {e}") from e
    raise JevError(f"unknown answer type for question {qid!r}: {kind!r}")


def _answer_record(answer: Answer) -> dict:
    tag = {"noul": "noul", "choice": "choice", "score": "score"}[type(answer).__name__.lower()]
    return {"type": tag, **asdict(answer)}


def _append_trace(path: Path | str, record: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
