"""Evals (U10, KTD10, R11): golden-set scoring, native baseline, calibration sweep.

Golden set: tests/golden/golden.jsonl — one JSON object per line:

    {"id": ..., "prompt": ..., "expected": ["skill:pricing", ...],
     "partition": "calib" | "holdout"}

Expected ids are QUALIFIED router ids ("type:id") — the same format the
pipeline's gate survivors use, so router output compares directly.

Partition contract (KTD10): the sweep tunes on "calib" ONLY; the
router-vs-baseline gate scores "holdout" ONLY. evaluate() takes the partition
explicitly and sweep() hard-filters to calib before any routing happens.

Baseline: tests/golden/baseline.jsonl — the hand-authored record of what
ZCode-native skill triggering WOULD pick per prompt (the documented native
harness per KTD10):

    {"id": ..., "prompt": ..., "native": ["skill:cold-email", ...]}

Sampling: the Jev API exposes no seed (plan Dependencies, verified
2026-09-30), so every prompt runs DEFAULT_RUNS times and hits are
majority-voted via thresholds.resample (last 3 samples, strict majority;
no majority -> not a hit). Stability = mean share of runs agreeing with the
majority — the reported variance. The baseline is deterministic (one native
pick list) and reports stability n/a.

CLI: python3 -m router.evals --config <toml> [--golden P] [--baseline P]
    [--partition holdout] [--runs 3] [--live] [--sweep]
    [--budgets 600,3000,4500] [--max-options 0,12]

Without --live the run is a wiring smoke over a deterministic no-Jev mock
(routed nowhere, scores 0) and the report says mode=mock — no API calls
happen without --live. Sweep repacks shard meta in place (derived-only
invariant respected: shards recomputed from catalog rows); run
`router index` afterwards to restore the shipped packing.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Sequence, Tuple

from router import indexer, jev, pipeline, thresholds
from router.catalog import Catalog
from router.config import ConfigError, RouterConfig
from router.jev import Answer, Choice, Noul
from router.pipeline import RouteResult

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLDEN = REPO_ROOT / "tests" / "golden" / "golden.jsonl"
DEFAULT_BASELINE = REPO_ROOT / "tests" / "golden" / "baseline.jsonl"
PARTITIONS = ("calib", "holdout")
RESAMPLE_K = 3          # majority-of-3 (KTD10; thresholds.resample window)
DEFAULT_RUNS = 3
DEFAULT_BUDGETS = (600, 3000, 4500)
DEFAULT_MAX_OPTIONS = (0,)  # 0 = packer default (budget-driven shard size)


class EvalError(Exception):
    """Malformed golden/baseline data or missing eval inputs."""


# -- golden + baseline loading ---------------------------------------------------

@dataclass(frozen=True)
class GoldenEntry:
    id: str
    prompt: str
    expected: Tuple[str, ...]
    partition: str


def _lines(path: Path | str) -> Iterable[Tuple[int, dict]]:
    """Yield (line-number, parsed object); blank/corrupt lines skipped."""
    p = Path(path)
    if not p.is_file():
        raise EvalError(f"file not found: {p}")
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue  # corrupt line skipped (KTD4: rebuild rather than crash)
        if isinstance(obj, dict):
            yield n, obj


def load_golden(path: Path | str = DEFAULT_GOLDEN) -> List[GoldenEntry]:
    """Parse + validate the golden JSONL (prompt/expected/partition)."""
    entries: List[GoldenEntry] = []
    for n, obj in _lines(path):
        prompt = obj.get("prompt")
        expected = obj.get("expected")
        partition = obj.get("partition")
        if not isinstance(prompt, str) or not prompt.strip():
            raise EvalError(f"{path}: line {n}: missing prompt")
        if not isinstance(expected, list) or not expected:
            raise EvalError(f"{path}: line {n}: expected must be a non-empty list")
        if any(not isinstance(e, str) or not e for e in expected):
            raise EvalError(f"{path}: line {n}: expected ids must be non-empty strings")
        if partition not in PARTITIONS:
            raise EvalError(
                f"{path}: line {n}: partition must be one of {PARTITIONS}, "
                f"got {partition!r}"
            )
        entries.append(
            GoldenEntry(
                id=str(obj.get("id") or f"line{n}"),
                prompt=prompt,
                expected=tuple(expected),
                partition=partition,
            )
        )
    return entries


def partition_entries(entries: Sequence[GoldenEntry], partition: str) -> List[GoldenEntry]:
    """Entries of one partition; unknown partition names raise (KTD10 split)."""
    if partition not in PARTITIONS:
        raise EvalError(f"unknown partition {partition!r} (expected {PARTITIONS})")
    return [e for e in entries if e.partition == partition]


def load_baseline(path: Path | str = DEFAULT_BASELINE) -> Dict[str, Tuple[str, ...]]:
    """Native picks per prompt from the baseline JSONL (mock of ZCode-native)."""
    baseline: Dict[str, Tuple[str, ...]] = {}
    for n, obj in _lines(path):
        prompt = obj.get("prompt")
        native = obj.get("native", [])
        if not isinstance(prompt, str) or not prompt.strip():
            raise EvalError(f"{path}: line {n}: missing prompt")
        if not isinstance(native, list) or any(not isinstance(x, str) for x in native):
            raise EvalError(f"{path}: line {n}: native must be a list of strings")
        baseline[prompt] = tuple(native)
    return baseline


# -- routing under test -------------------------------------------------------------

def run_router(
    prompt: str, catalog: Catalog, ask: Callable[..., Dict[str, Answer]] | None = None
) -> RouteResult:
    """One routed turn. ask=None -> the real jev.ask; tests inject a mock."""
    return pipeline.route(prompt, catalog, ask=jev.ask if ask is None else ask)


def routed_ids(result: RouteResult) -> List[str]:
    """Qualified capability ids the router injected this turn (gate survivors)."""
    gate = result.verdicts.get("gate") or {}
    return [str(s) for s in (gate.get("survivors") or [])]


# -- scoring -------------------------------------------------------------------------

def _votes(
    results: Sequence[Sequence[str]], expected: Sequence[str], k: int
) -> List[bool]:
    expected_set = {str(e) for e in expected}
    return [
        bool(expected_set.intersection(str(rid) for rid in run[:k]))
        for run in results
    ]


def hit_at_k(
    results: Sequence[Sequence[str]], expected: Sequence[str], k: int
) -> bool | None:
    """Majority-of-RESAMPLE_K vote over per-run hit@k, via thresholds.resample.

    results: one list of routed ids per sampling run; a run hits when its
    top-k routed ids intersect expected. Returns True/False on a strict
    majority, None when the vote splits (caller treats None as no hit).
    """
    return thresholds.resample(_votes(results, expected, k), k=RESAMPLE_K)


def _stability(votes: Sequence[bool]) -> float:
    """Share of runs agreeing with the majority — the reported variance."""
    window = list(votes)[-RESAMPLE_K:]
    if not window:
        return 0.0
    winner = thresholds.resample(window, k=RESAMPLE_K)
    if winner is None:
        return 0.0
    return sum(1 for v in window if v == winner) / len(window)


@dataclass(frozen=True)
class Score:
    mode: str                    # "router" | "baseline"
    partition: str
    prompts: int
    hit1: float
    hit3: float
    stability: float | None = None  # None for the deterministic baseline


def evaluate(
    entries: Sequence[GoldenEntry],
    catalog: Catalog,
    partition: str,
    ask: Callable[..., Dict[str, Answer]] | None = None,
    runs: int = DEFAULT_RUNS,
) -> Score:
    """Score the ROUTER on one partition. Partition is explicit (KTD10).

    Every prompt runs `runs` times; hit@1/hit@3 are majority-voted; the mean
    majority agreement is the stability.
    """
    part = partition_entries(entries, partition)  # validates the name
    hits1: List[bool] = []
    hits3: List[bool] = []
    stabilities: List[float] = []
    for entry in part:
        per_run = [
            routed_ids(run_router(entry.prompt, catalog, ask=ask))
            for _ in range(max(1, runs))
        ]
        v1 = _votes(per_run, entry.expected, 1)
        v3 = _votes(per_run, entry.expected, 3)
        hits1.append(hit_at_k(per_run, entry.expected, 1) is True)
        hits3.append(hit_at_k(per_run, entry.expected, 3) is True)
        stabilities.append(_stability(v1))
    n = len(part)
    return Score(
        mode="router",
        partition=partition,
        prompts=n,
        hit1=(sum(hits1) / n) if n else 0.0,
        hit3=(sum(hits3) / n) if n else 0.0,
        stability=(sum(stabilities) / n) if n else 0.0,
    )


def score_baseline(
    entries: Sequence[GoldenEntry],
    baseline: Dict[str, Tuple[str, ...]],
    partition: str,
) -> Score:
    """Score the recorded native picks on the same prompts (KTD10 baseline).

    Deterministic single sample per prompt: hit@1/hit@3 over the recorded
    pick order; a prompt with no baseline row counts as a native miss.
    """
    part = partition_entries(entries, partition)
    hits1: List[bool] = []
    hits3: List[bool] = []
    for entry in part:
        picks = baseline.get(entry.prompt, ())
        hits1.append(hit_at_k([list(picks)], entry.expected, 1) is True)
        hits3.append(hit_at_k([list(picks)], entry.expected, 3) is True)
    n = len(part)
    return Score(
        mode="baseline",
        partition=partition,
        prompts=n,
        hit1=(sum(hits1) / n) if n else 0.0,
        hit3=(sum(hits3) / n) if n else 0.0,
        stability=None,
    )


# -- calibration sweep --------------------------------------------------------------

def _split_shards(shards: List[dict], max_options: int, chars_per_token: int) -> List[dict]:
    """Split packed shards so no worker sees more than max_options options.

    Shard ids and descriptor lines are parallel lists (indexer.pack_shards),
    so chunking both keeps id<->descriptor correspondence. Sub-shards are
    renumbered so every question id stays unique per type.
    """
    out: List[dict] = []
    for shard in shards:
        pairs = list(zip(shard["ids"], shard["text"].splitlines()))
        for start in range(0, len(pairs), max_options):
            chunk = pairs[start:start + max_options]
            text = "\n".join(line for _rid, line in chunk)
            chars = sum(len(line) + 1 for _rid, line in chunk)
            out.append({
                "i": len(out),
                "ids": [rid for rid, _line in chunk],
                "text": text,
                "chars": chars,
                "est_tokens": (chars + chars_per_token - 1) // chars_per_token,
            })
    return out


def repack_shards(
    catalog: Catalog, budget_tokens: int, max_options: int = 0
) -> None:
    """Repack every populated type's shards at a new budget (sweep knob).

    Shards are recomputed from catalog rows only (derived-only invariant,
    R13) and written back to meta. max_options > 0 additionally splits shards
    so no recall worker sees more options than that (plan: shard budget x
    options-per-shard).
    """
    tables = [
        name
        for (name,) in catalog.rows(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        if name not in ("relations", "meta")
    ]
    for table in tables:
        if catalog.count(table) == 0:
            continue
        cols = [c[1] for c in catalog.db.execute(f"PRAGMA table_info({table})")]
        rows = [dict(zip(cols, r)) for r in catalog.rows(f"SELECT * FROM {table}")]
        enabled = sorted(
            (r for r in rows if r.get("enabled", 1)), key=lambda r: str(r["id"])
        )
        packed = indexer.pack_shards(enabled, budget_tokens=budget_tokens)
        if max_options:
            packed["shards"] = _split_shards(
                packed["shards"], max_options, packed["chars_per_token"]
            )
        catalog.db.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (f"shards:{table}", json.dumps(packed, ensure_ascii=False)),
        )
    catalog.db.commit()


def sweep(
    entries: Sequence[GoldenEntry],
    catalog: Catalog,
    ask: Callable[..., Dict[str, Answer]] | None = None,
    runs: int = DEFAULT_RUNS,
    budgets: Sequence[int] = DEFAULT_BUDGETS,
    max_options: Sequence[int] = DEFAULT_MAX_OPTIONS,
) -> Tuple[List[dict], List[str]]:
    """Calibration sweep over shard budget x options-per-shard (KTD10, plan U10).

    Scores hit@1 on the CALIBRATION partition only — holdout entries are
    filtered out before any routing happens. Returns (rows, report_lines);
    rows carry budget/max_options/shards/prompts/hit1, the report names the
    winning budget (ties break toward fewer shards, then smaller budget).
    """
    calib = partition_entries(entries, "calib")
    rows: List[dict] = []
    for budget in budgets:
        for mo in max_options:
            repack_shards(catalog, budget_tokens=int(budget), max_options=int(mo))
            score = evaluate(calib, catalog, "calib", ask=ask, runs=runs)
            n_shards = sum(
                len(json.loads(value).get("shards") or [])
                for _key, value in catalog.rows(
                    "SELECT key, value FROM meta WHERE key LIKE 'shards:%'"
                )
            )
            rows.append({
                "budget": int(budget),
                "max_options": int(mo),
                "shards": n_shards,
                "prompts": score.prompts,
                "hit1": score.hit1,
            })
    lines = [
        "| budget | max_options | shards | prompts | hit@1 |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['budget']} | {r['max_options']} | {r['shards']} "
            f"| {r['prompts']} | {r['hit1']:.3f} |"
        )
    if rows:
        best = max(rows, key=lambda r: (r["hit1"], -r["shards"], -r["budget"]))
        lines.append(
            f"winning budget {best['budget']}, max_options {best['max_options']}, "
            f"hit@1 {best['hit1']:.3f}"
        )
    return rows, lines


# -- report ---------------------------------------------------------------------------

def report(scores: Sequence[Score]) -> List[str]:
    """Markdown lines: one router-vs-baseline row per scored partition."""
    lines = [
        "| mode | partition | prompts | hit@1 | hit@3 | stability |",
        "|---|---|---|---|---|---|",
    ]
    for s in scores:
        stability = "n/a (1 sample)" if s.stability is None else f"{s.stability:.3f}"
        lines.append(
            f"| {s.mode} | {s.partition} | {s.prompts} | {s.hit1:.3f} "
            f"| {s.hit3:.3f} | {stability} |"
        )
    return lines


# -- offline mock (no-Jev wiring smoke) ------------------------------------------------

def _offline_ask(state: str, questions: Dict[str, dict], **_kwargs) -> Dict[str, Answer]:
    """Deterministic no-Jev ask: every triage skips -> every turn no-match.

    Used ONLY when the CLI runs without --live, so the report is labeled
    mode=mock and no API call can happen by accident.
    """
    answers: Dict[str, Answer] = {}
    for qid, spec in questions.items():
        if spec.get("type") == "noul":
            answers[qid] = Noul(p=0.0)
        else:
            answers[qid] = Choice(choice="none", probabilities={"none": 1.0},
                                  confidence=1.0)
    return answers


# -- CLI --------------------------------------------------------------------------------

def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="router.evals",
        description="Score the router against the golden set and the native baseline.",
    )
    parser.add_argument("--config", default="~/.config/router/router.toml",
                        help="router TOML config path (locates the catalog)")
    parser.add_argument("--golden", default=str(DEFAULT_GOLDEN), help="golden JSONL path")
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE),
                        help="native-baseline JSONL path")
    parser.add_argument("--partition", default="holdout", choices=PARTITIONS,
                        help="partition the gate scores (default holdout, KTD10)")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS,
                        help=f"samples per prompt (default {DEFAULT_RUNS})")
    parser.add_argument("--live", action="store_true",
                        help="route through the real jev.ask (makes API calls)")
    parser.add_argument("--sweep", action="store_true",
                        help="run the calibration sweep (calib partition only)")
    parser.add_argument("--budgets", default=",".join(map(str, DEFAULT_BUDGETS)),
                        help="comma-separated shard budgets for --sweep")
    parser.add_argument("--max-options", dest="max_options",
                        default=",".join(map(str, DEFAULT_MAX_OPTIONS)),
                        help="comma-separated options-per-shard caps (0 = packer default)")
    args = parser.parse_args(argv)

    try:
        entries = load_golden(args.golden)
        baseline = load_baseline(args.baseline)
        config = RouterConfig.load(args.config)
        catalog_path = config.state_path("catalog.db")
        if not catalog_path.is_file():
            raise EvalError(f"catalog not found at {catalog_path} (run: router index)")
        catalog = Catalog(catalog_path)
    except (EvalError, ConfigError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    try:
        ask = jev.ask if args.live else _offline_ask
        mode = "live" if args.live else "mock (no Jev calls; pass --live to score for real)"
        if args.sweep:
            budgets = tuple(int(b) for b in str(args.budgets).split(",") if b.strip())
            options = tuple(int(m) for m in str(args.max_options).split(",") if m.strip())
            print(f"sweep mode: {mode}")
            _rows, lines = sweep(entries, catalog, ask=ask, runs=args.runs,
                                 budgets=budgets, max_options=options)
        else:
            scores = [
                evaluate(entries, catalog, args.partition, ask=ask, runs=args.runs),
                score_baseline(entries, baseline, args.partition),
            ]
            print(f"mode: {mode}")
            lines = report(scores)
    finally:
        catalog.close()

    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
