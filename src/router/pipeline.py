"""Turn pipeline (U4): Jev triage -> parallel recall fan -> Jev gate.

R2: every relevance decision is Jev's — this module does I/O and applies the
settled code threshold policy (KTD2: p >= 0.95 act, p <= 0.05 skip, else
escalate). Recall shards are the indexer's precomputed payloads (R8) read
from the catalog meta key "shards:<type>".

Stage 1 triage: ONE ask() call, one Noul question per type present; only
    "act" types proceed.
Stage 2 fan: one worker (ask() Choice over a shard's option ids + "none")
    per shard of triage-passed types, run in parallel on a ThreadPoolExecutor
    capped at worker_ceiling. Shards beyond the ceiling merge into the last
    worker's criteria — coverage is preserved over parallelism, and an assert
    guards that no option is ever dropped.
Stage 3 gate: ONE ask() over the fan winners — Choice "which capabilities
    should actually be injected" (criteria = qualified winner ids "type:id"
    plus "none") and a Noul capture question. The capture answer is returned
    verbatim as RouteResult.capture_candidate (no-op placeholder here; U14
    wires the pending queue). Survivors are the gate's modal choice plus any
    winner whose gate probability clears the act threshold.

Injection format (R5): "- [type] name — description-first-line (path)".
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple

from router import jev
from router.catalog import Catalog
from router.jev import Answer, Choice, Noul
from router.thresholds import ACT_THRESHOLD, act

GATE_INJECT_QID = "gate_inject"
GATE_CAPTURE_QID = "gate_capture"
NONE = "none"

Ask = Callable[..., Dict[str, Answer]]


class PipelineError(Exception):
    """Malformed Jev answer shape inside the pipeline."""


@dataclass(frozen=True)
class RouteResult:
    injections: List[str]
    verdicts: dict
    no_match: bool
    capture_candidate: float | None = None


# -- stage 1: triage --------------------------------------------------------

def present_types(catalog: Catalog) -> List[Tuple[str, list]]:
    """Types with at least one indexed shard, as (type, shards), stable order."""
    out: List[Tuple[str, list]] = []
    for key, value in catalog.rows(
        "SELECT key, value FROM meta WHERE key LIKE 'shards:%' ORDER BY key"
    ):
        try:
            packed = json.loads(value)
        except (TypeError, ValueError):
            continue
        shards = packed.get("shards") or []
        if shards:
            out.append((key[len("shards:"):], shards))
    return out


def _triage(prompt_state: str, types: List[str], ask: Ask) -> Tuple[dict, List[str]]:
    questions = {
        f"triage_{t}": {
            "type": "noul",
            "instructions": f"Is a {t} capability relevant to this prompt?",
        }
        for t in types
    }
    answers = ask(prompt_state, questions)
    verdicts: dict = {}
    passed: List[str] = []
    for t in types:
        answer = answers[f"triage_{t}"]
        if not isinstance(answer, Noul):
            raise PipelineError(f"triage answer for {t!r} is not a Noul")
        verdicts[t] = act(answer.p)
        if verdicts[t] == "act":
            passed.append(t)
    return verdicts, passed


# -- stage 2: recall fan ------------------------------------------------------

def _plan_worker_groups(tasks: list, worker_ceiling: int) -> list:
    """Group (type, shard) tasks into <= worker_ceiling worker payloads.

    Below the ceiling: one worker per shard. Above: the overflow shards merge
    into the last worker's criteria list — every shard is still dispatched.
    """
    ceiling = max(1, worker_ceiling)
    if len(tasks) <= ceiling:
        return [[task] for task in tasks]
    return [[task] for task in tasks[: ceiling - 1]] + [tasks[ceiling - 1:]]


def _fan_question(group: list) -> Tuple[str, dict]:
    """Choice question covering every shard in one worker group."""
    t0, shard0 = group[0]
    qid = f"recall_{t0}_{shard0['i']}"
    ids: List[str] = []
    seen = set()
    texts: List[str] = []
    for _t, shard in group:
        texts.append(shard["text"])
        for rid in shard["ids"]:
            if rid not in seen:
                seen.add(rid)
                ids.append(rid)
    subject = f"{t0} capability" if len({t for t, _ in group}) == 1 else "capability"
    return qid, {
        "type": "choice",
        "instructions": (
            f"Which {subject}, if any, does the prompt need? Options are "
            f"'id | name | description' lines:\n" + "\n".join(texts)
            + f"\nPick '{NONE}' if none matches."
        ),
        "criteria": ids + [NONE],
    }


def _fan(
    prompt_state: str,
    passed_shards: List[Tuple[str, list]],
    ask: Ask,
    worker_ceiling: int,
) -> Tuple[dict, Dict[str, float]]:
    tasks = [(t, shard) for t, shards in passed_shards for shard in shards]
    groups = _plan_worker_groups(tasks, worker_ceiling)

    # Coverage guard (R3): every option of every shard of a passed type is
    # offered to some worker, ceiling or not.
    all_ids = {rid for _t, shard in tasks for rid in shard["ids"]}
    planned_ids = {rid for g in groups for _t, shard in g for rid in shard["ids"]}
    assert len([task for g in groups for task in g]) == len(tasks)
    assert all_ids <= planned_ids, "fan plan dropped shard options"

    planned = []
    for group in groups:
        qid, spec = _fan_question(group)
        planned.append((qid, spec, group))
    fan_verdicts: dict = {}
    winners: Dict[str, float] = {}  # qualified "type:id" -> probability
    with ThreadPoolExecutor(max_workers=max(1, min(worker_ceiling, len(groups)))) as ex:
        futures = [
            (ex.submit(ask, prompt_state, {qid: spec}), qid, group)
            for qid, spec, group in planned
        ]
        for future, qid, group in futures:
            answers = future.result()
            answer = answers[qid]
            if not isinstance(answer, Choice):
                raise PipelineError(f"recall answer for {qid!r} is not a Choice")
            p = answer.probabilities.get(answer.choice, answer.confidence)
            fan_verdicts[qid] = {"choice": answer.choice, "p": p}
            if answer.choice == NONE:
                continue
            owner = next((t for t, shard in group if answer.choice in shard["ids"]), group[0][0])
            qualified = f"{owner}:{answer.choice}"
            if p > winners.get(qualified, -1.0):
                winners[qualified] = p
    return fan_verdicts, winners


# -- stage 3: gate --------------------------------------------------------------

def _row(catalog: Catalog, type_: str, rid: str) -> Tuple[str, str, str] | None:
    rows = catalog.rows(
        f"SELECT name, description, path FROM {type_} WHERE id = ?", (rid,)
    )
    if not rows:
        return None
    name, description, path = rows[0]
    return name or rid, description or "", path or ""


def _first_line(description: str) -> str:
    for line in description.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _winner_line(catalog: Catalog, qualified: str) -> str:
    type_, _, rid = qualified.partition(":")
    row = _row(catalog, type_, rid)
    name, description, _path = row if row else (rid, "", "")
    head = f"{name} — {_first_line(description)}" if _first_line(description) else name
    return f"{qualified}: {head}"


def _gate(
    prompt_state: str, winners: Dict[str, float], catalog: Catalog, ask: Ask
) -> Tuple[dict, List[str], float]:
    state = (
        prompt_state
        + "\n\nCandidate capabilities found by recall (type:id: name — description):\n"
        + "\n".join(_winner_line(catalog, q) for q in winners)
    )
    questions = {
        GATE_INJECT_QID: {
            "type": "choice",
            "instructions": "Which capabilities should actually be injected "
            "into the agent turn for this prompt?",
            "criteria": list(winners) + [NONE],
        },
        GATE_CAPTURE_QID: {
            "type": "noul",
            "instructions": "Any learning candidate worth capturing from this turn?",
        },
    }
    answers = ask(state, questions)
    inject = answers[GATE_INJECT_QID]
    capture = answers[GATE_CAPTURE_QID]
    if not isinstance(inject, Choice):
        raise PipelineError("gate inject answer is not a Choice")
    if not isinstance(capture, Noul):
        raise PipelineError("gate capture answer is not a Noul")

    survivors: List[str] = []
    if inject.choice != NONE:
        # modal pick survives; high-probability winners ride along
        for qualified in winners:
            if qualified == inject.choice or inject.probabilities.get(qualified, 0.0) >= ACT_THRESHOLD:
                survivors.append(qualified)
    verdicts = {
        "choice": inject.choice,
        "probabilities": dict(inject.probabilities),
        "survivors": survivors,
    }
    return verdicts, survivors, capture.p


def _injection_line(catalog: Catalog, qualified: str) -> str | None:
    type_, _, rid = qualified.partition(":")
    row = _row(catalog, type_, rid)
    if row is None:
        return None
    name, description, path = row
    first = _first_line(description)
    core = f"{name} — {first}" if first else name
    return f"- [{type_}] {core} ({path})"


# -- orchestration ------------------------------------------------------------

def route(
    prompt_state: str,
    catalog: Catalog,
    ask: Ask = jev.ask,
    worker_ceiling: int = 6,
) -> RouteResult:
    """Run the three Jev layers over one prompt; return injections + verdicts."""
    present = present_types(catalog)
    if not present:
        return RouteResult(injections=[], verdicts={"triage": {}}, no_match=True)

    triage_verdicts, passed = _triage(prompt_state, [t for t, _ in present], ask)
    verdicts: dict = {"triage": triage_verdicts}
    if not passed:
        verdicts["fan"] = {}
        return RouteResult(injections=[], verdicts=verdicts, no_match=True)

    passed_shards = [(t, shards) for t, shards in present if t in passed]
    fan_verdicts, winners = _fan(prompt_state, passed_shards, ask, worker_ceiling)
    verdicts["fan"] = fan_verdicts
    if not winners:
        return RouteResult(injections=[], verdicts=verdicts, no_match=True)

    gate_verdicts, survivors, capture_p = _gate(prompt_state, winners, catalog, ask)
    verdicts["gate"] = gate_verdicts
    injections = [
        line
        for line in (_injection_line(catalog, q) for q in survivors)
        if line is not None
    ]
    no_match = gate_verdicts["choice"] == NONE or not injections
    return RouteResult(
        injections=injections,
        verdicts=verdicts,
        no_match=no_match,
        capture_candidate=capture_p,
    )
