"""ZCode hook adapter (U5, KTD4): stdin payload -> additionalContext | block.

Contract (verified ZCode hook wiring, jev-implementations Phase 4 evidence):

- Success: print {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
  "additionalContext": ...}} to stdout, exit 0. additionalContext NEVER blocks.
- No match: exit 0 with no stdout — the turn simply proceeds un-injected.
- ANY failure (Jev timeout/error, router exception, malformed payload, bad or
  missing config/catalog): exit 2 with "ROUTING BLOCKED: <cause>. Override:
  run `router off`" on stderr — fail-closed per R9/KTD4; no traceback ever.
- routing_enabled=false in the TOML is the one non-failure unrouted path:
  exit 0, no output (the `router off` override lands there).

The ZCode hook is registered with timeoutMs >= the Jev timeout so the harness
never kills the hook first (print_zcode_hook_config below).
"""
from __future__ import annotations

import argparse
import functools
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from router import capture, jev, memory, pipeline, telemetry
from router import caches as caches_mod
from router.caches import prompt_fingerprint
from router.catalog import Catalog
from router.config import RouterConfig

DEFAULT_CONFIG = "~/.config/router/router.toml"
TRANSCRIPT_TAIL_LINES = 5  # last-K transcript turns feed prompt state (KTD6)
MIN_HOOK_TIMEOUT_MS = 45_000  # >= default Jev 30s timeout, per KTD4
HOOK_EVENT = "UserPromptSubmit"


@dataclass(frozen=True)
class HookOutcome:
    exit_code: int
    additional_context: str | None = None
    stderr_reason: str | None = None


class _Blocked(Exception):
    """Internal: carry a block cause up to run_hook's fail-closed wrapper."""


def _blocked(cause: str) -> HookOutcome:
    return HookOutcome(
        exit_code=2,
        stderr_reason=f"ROUTING BLOCKED: {cause}. Override: run `router off`",
    )


# -- payload ------------------------------------------------------------------

def _parse_payload(stdin_json: str) -> dict:
    try:
        payload = json.loads(stdin_json)
    except ValueError as e:
        raise _Blocked(f"malformed payload JSON ({type(e).__name__})") from e
    if not isinstance(payload, dict):
        raise _Blocked("malformed payload: expected a JSON object")
    return payload


# -- core flow ------------------------------------------------------------------

def _run(stdin_json: str, config_path: Path) -> HookOutcome:
    payload = _parse_payload(stdin_json)
    config = RouterConfig.load(config_path)
    if not config.routing_enabled:
        return HookOutcome(exit_code=0)  # unrouted override path (KTD5)

    catalog_path = config.state_path("catalog.db")
    if not catalog_path.is_file():
        raise _Blocked(
            f"catalog missing at {catalog_path} "
            f"(run: python3 -m router.cli index)"
        )

    prompt = str(payload.get("prompt") or "")
    session_id = str(payload.get("session_id") or "")
    transcript_path = payload.get("transcript_path")

    # Session memory (R7/KTD6): rolling context + active-set feed Jev state;
    # record_turn after the route keeps judge/discovery fed.
    mem = memory.SessionMemory(config.state_dir)
    state = jev.redact(mem.context_state(prompt, session_id, transcript_path))

    catalog = Catalog(catalog_path)
    caches = caches_mod.Caches(catalog)  # patches fingerprint to exclude caches
    started = time.monotonic()
    cache_hit = False
    prompt_fp = prompt_fingerprint(prompt)
    catalog_fp = catalog.fingerprint()

    # Verdict/negative caches (R8/KTD7): replay before paying Jev (AE4).
    cached = caches.lookup_verdict(prompt_fp, catalog_fp)
    if cached is not None:
        cache_hit = True
        result = pipeline.RouteResult(
            injections=list(cached.get("injections", [])),
            verdicts={"cached": True},
            no_match=not cached.get("injections"),
            survivors=tuple(cached.get("survivors", ())),
        )
    elif caches.is_negative(prompt_fp, catalog_fp):
        cache_hit = True
        result = pipeline.RouteResult(
            injections=[], verdicts={"cached_negative": True}, no_match=True
        )
    else:
        ask_bound = functools.partial(
            jev.ask,
            credential_ref=config.credential_ref,
            timeout_ms=config.timeout_ms,
            trace_path=config.state_path("trace.jsonl"),
        )
        result = pipeline.route(state, catalog, ask=ask_bound)

    # per-turn learning capture (R13/KTD11): queue the candidate when the
    # gate raised a meaningful signal; append never raises and returns False
    # on failure (log-and-continue) — routing already succeeded.
    if result.capture_candidate is not None and result.capture_candidate >= 0.60:
        capture.append(
            {
                "kind": "learning",
                "text": jev.redact(prompt)[:500],
                "payload": {"score": result.capture_candidate},
                "session": session_id,
                "turn_context": {
                    "session": session_id,
                    "injections": list(result.injections),
                },
            },
            config,
        )

    if not cache_hit:
        try:
            if result.no_match:
                caches.store_negative(prompt_fp, catalog_fp)
            else:
                caches.store_verdict(
                    prompt_fp,
                    catalog_fp,
                    {
                        "injections": result.injections,
                        "survivors": list(result.survivors),
                    },
                )
        finally:
            catalog.close()

    mem.record_turn(session_id, prompt, injected_ids=result.survivors)

    # per-turn telemetry (U10, R11) — success path only, after route();
    # append_turn never raises (KTD11), so this cannot break the turn.
    telemetry.append_turn(
        config.state_dir,
        {
            "session": session_id,
            "prompt_fingerprint": prompt_fp,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "cost_usd": 0.0,  # not metered on the hook path; the jev.ask trace carries cost (KTD2)
            "injection_count": len(result.injections),
            "cache_hit": cache_hit,
            "verdicts_digest": telemetry.digest(result.verdicts),
        },
    )

    if not result.injections:
        return HookOutcome(exit_code=0)  # no match: exit 0, no stdout
    return HookOutcome(
        exit_code=0, additional_context="\n".join(result.injections)
    )


def run_hook(stdin_json: str, config_path: Path | str) -> HookOutcome:
    """Route one hook payload; never raises — every failure becomes a block."""
    try:
        return _run(stdin_json, Path(config_path).expanduser())
    except _Blocked as e:
        return _blocked(str(e))
    except jev.JevTimeoutError as e:
        return _blocked(f"Jev timed out: {e}")
    except jev.JevError as e:
        return _blocked(f"Jev error: {e}")
    except Exception as e:  # noqa: BLE001 — fail closed, never a traceback
        return _blocked(f"{type(e).__name__}: {e}")


# -- process entry ---------------------------------------------------------------

def _stdout_json(additional_context: str) -> str:
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": HOOK_EVENT,
                "additionalContext": additional_context,
            }
        },
        ensure_ascii=False,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="router.hook",
        description="ZCode UserPromptSubmit hook: route the turn or block.",
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG,
                        help="router TOML config path")
    args = parser.parse_args(argv)

    try:
        stdin_json = sys.stdin.read()
        outcome = run_hook(stdin_json, Path(args.config))
    except Exception as e:  # noqa: BLE001 — a hook never crashes
        outcome = _blocked(f"{type(e).__name__}: {e}")

    if outcome.additional_context:
        print(_stdout_json(outcome.additional_context))
    if outcome.stderr_reason:
        print(outcome.stderr_reason, file=sys.stderr)
    return outcome.exit_code


# -- ZCode hook registration (KTD4) ---------------------------------------------

def zcode_hook_config(config: RouterConfig, config_path: Path | str | None = None) -> dict:
    """Mergeable hooks block for ~/.zcode/cli/config.json.

    timeoutMs stays >= the Jev timeout (config.timeout_ms, default 30s) so the
    harness never kills the hook before Jev's own timeout fires (KTD4).
    """
    path = (
        Path(config_path).expanduser()
        if config_path is not None
        else Path(DEFAULT_CONFIG).expanduser()
    )
    timeout_ms = max(
        MIN_HOOK_TIMEOUT_MS,
        # Pipeline worst case: 3 sequential Jev layers, each up to timeout_ms
        # per attempt with up to 2 retries + backoff (KTD4: the harness must
        # never kill the hook before the fail-closed notice renders).
        3 * config.timeout_ms + 3_000 + 15_000,
    )
    src_root = Path(__file__).resolve().parents[1]
    return {
        "hooks": {
            "events": {
                HOOK_EVENT: [
                    {
                        "command": (
                            f"PYTHONPATH={src_root} python3 -m router.hook"
                            f" --config {path}"
                        ),
                        "timeoutMs": timeout_ms,
                    }
                ]
            }
        }
    }


def print_zcode_hook_config(
    config: RouterConfig, config_path: Path | str | None = None
) -> None:
    print(json.dumps(zcode_hook_config(config, config_path), indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
