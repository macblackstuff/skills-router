"""U3 tests: Jev client (typed answers, retry, timeout, trace, redaction) + thresholds."""
import hashlib
import json
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest
import urllib.request

import router.jev as jev
from router.jev import (
    Choice,
    JevError,
    JevTimeoutError,
    Noul,
    Score,
    ask,
    redact,
    resolve_credential,
)
from router.thresholds import act, confidence, resample


def canned_payload():
    return {
        "model": "jev-latest",
        "answers": {
            "is_urgent": {"type": "noul", "noul": 0.97},
            "department": {
                "type": "choice",
                "choice": "billing",
                "probabilities": {"billing": 0.88, "technical": 0.12},
                "confidence": 0.81,
            },
            "frustration": {
                "type": "score",
                "score": 1.05,
                "legend": {"0": "Calm", "1": "Frustrated"},
                "probabilities": {"0": 0.6, "1": 0.4},
                "confidence": 0.92,
            },
        },
        "usage": {"input_tokens": 7000, "output_tokens": 20},
    }


def questions_spec():
    return {
        "is_urgent": {"type": "noul", "instructions": "Is the user urgent?"},
        "department": {
            "type": "choice",
            "instructions": "Pick the department.",
            "criteria": ["billing", "technical"],
        },
        "frustration": {"type": "score", "instructions": "Score frustration 0-2."},
    }


class _Resp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def install_urlopen(monkeypatch, outcomes):
    """Patch urllib.request.urlopen; each call pops one outcome.

    outcome: dict payload (success) or Exception instance (raised).
    Returns the list of captured requests.
    """
    calls = []
    queue = list(outcomes)

    def fake_urlopen(request, timeout=None):
        headers = {k.lower(): v for k, v in request.headers.items()}
        calls.append(
            {
                "body": json.loads(request.data.decode("utf-8")),
                "headers": headers,
                "timeout": timeout,
            }
        )
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return _Resp(item)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return calls


def http_error(code):
    return urllib.error.HTTPError(
        "https://api.typesafe.ai/v1/systemone", code, "err", None, None
    )


# --- ask(): typed answers, request shape, trace ---


def test_ask_returns_typed_answers_and_traces_usage_latency(monkeypatch, tmp_path):
    monkeypatch.setenv("JEV_TEST_KEY", "test-secret-token-123")
    calls = install_urlopen(monkeypatch, [canned_payload()])
    trace = tmp_path / "trace.jsonl"

    answers = ask(
        "prompt: help with pricing",
        questions_spec(),
        credential_ref="JEV_TEST_KEY",
        trace_path=trace,
    )

    assert isinstance(answers["is_urgent"], Noul)
    assert answers["is_urgent"].p == pytest.approx(0.97)
    assert isinstance(answers["department"], Choice)
    assert answers["department"].choice == "billing"
    assert answers["department"].probabilities == pytest.approx(
        {"billing": 0.88, "technical": 0.12}
    )
    assert answers["department"].confidence == pytest.approx(0.81)
    assert isinstance(answers["frustration"], Score)
    assert answers["frustration"].score == pytest.approx(1.05)
    assert answers["frustration"].confidence == pytest.approx(0.92)

    req = calls[0]
    assert req["body"]["model"] == "jev-latest"
    assert req["body"]["state"] == "prompt: help with pricing"
    assert req["body"]["questions"] == questions_spec()
    assert req["headers"]["authorization"] == "Bearer test-secret-token-123"
    assert req["timeout"] == pytest.approx(30.0)  # default timeout_ms 30000

    lines = trace.read_text().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["questions"] == questions_spec()
    assert rec["usage"] == {"input_tokens": 7000, "output_tokens": 20}
    assert isinstance(rec["latency_ms"], int) and rec["latency_ms"] >= 0
    assert rec["cost_usd"] == pytest.approx(7000 / 1e6 * 0.042)
    assert rec["ts"]
    assert rec["state_digest"] == hashlib.sha256(
        b"prompt: help with pricing"
    ).hexdigest()


def test_ask_honors_custom_timeout_ms(monkeypatch):
    monkeypatch.setenv("JEV_TEST_KEY", "k")
    calls = install_urlopen(monkeypatch, [canned_payload()])
    ask("s", {"q": {"type": "noul", "instructions": "i"}},
        timeout_ms=1500, credential_ref="JEV_TEST_KEY")
    assert calls[0]["timeout"] == pytest.approx(1.5)


# --- retry ---


def test_ask_retries_429_then_succeeds(monkeypatch):
    monkeypatch.setenv("JEV_TEST_KEY", "k")
    monkeypatch.setattr(jev, "_RETRY_BACKOFF_S", 0.0)
    calls = install_urlopen(monkeypatch, [http_error(429), {
        "model": "jev-latest",
        "answers": {"q": {"type": "noul", "noul": 0.97}},
        "usage": {"input_tokens": 100, "output_tokens": 5},
    }])
    answers = ask("s", {"q": {"type": "noul", "instructions": "i"}},
                  credential_ref="JEV_TEST_KEY")
    assert len(calls) == 2
    assert answers["q"].p == pytest.approx(0.97)


def test_ask_retries_529_then_gives_up_after_two_retries(monkeypatch):
    monkeypatch.setenv("JEV_TEST_KEY", "k")
    monkeypatch.setattr(jev, "_RETRY_BACKOFF_S", 0.0)
    calls = install_urlopen(
        monkeypatch, [http_error(529), http_error(529), http_error(529)]
    )
    with pytest.raises(JevError):
        ask("s", {"q": {"type": "noul", "instructions": "i"}},
            credential_ref="JEV_TEST_KEY")
    assert len(calls) == 3  # 1 attempt + 2 retries


# --- timeout ---


def test_ask_timeout_raises_jev_timeout_error(monkeypatch):
    monkeypatch.setenv("JEV_TEST_KEY", "k")
    install_urlopen(monkeypatch, [TimeoutError("timed out")])
    with pytest.raises(JevTimeoutError):
        ask("s", {"q": {"type": "noul", "instructions": "i"}},
            credential_ref="JEV_TEST_KEY")


def test_ask_wrapped_connect_timeout_raises_jev_timeout_error(monkeypatch):
    monkeypatch.setenv("JEV_TEST_KEY", "k")
    install_urlopen(
        monkeypatch, [urllib.error.URLError(TimeoutError("connect timed out"))]
    )
    with pytest.raises(JevTimeoutError):
        ask("s", {"q": {"type": "noul", "instructions": "i"}},
            credential_ref="JEV_TEST_KEY")


def test_jev_timeout_is_jev_error():
    assert issubclass(JevTimeoutError, JevError)


# --- credential resolution ---


def test_resolve_credential_env_var(monkeypatch):
    monkeypatch.setenv("JEV_TEST_KEY", "env-value")
    assert resolve_credential("JEV_TEST_KEY") == "env-value"


def test_resolve_credential_missing_env_errors_without_leaking(monkeypatch):
    monkeypatch.delenv("JEV_TEST_KEY", raising=False)
    with pytest.raises(JevError, match="JEV_TEST_KEY"):
        resolve_credential("JEV_TEST_KEY")


def test_resolve_credential_op_path_uses_op_read(monkeypatch):
    captured = {}

    class P:
        returncode = 0
        stdout = "op-resolved-key\n"

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return P()

    monkeypatch.setattr(jev.subprocess, "run", fake_run)
    assert (
        resolve_credential("op://vault123/item456/credential") == "op-resolved-key"
    )
    assert captured["cmd"] == ["op", "read", "op://vault123/item456/credential"]


# --- redaction gate ---


def test_redact_scrubs_all_credential_patterns():
    text = (
        "key at op://wxfehwvpffxvjvxpyep7wjdv2a/fkxtpq2cjdhsgnngfko22ajjty/api_key "
        "and sk-aB1aB1aB1aB1aB1aB1aB1aB1aB1aB1 plus AKIAIOSFODNN7EXAMPLE "
        "and ghp_a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8 "
        "and -----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY----- "
        "plus an orphan -----BEGIN OPENSSH PRIVATE KEY----- header"
    )
    out = redact(text)
    assert "op://" not in out
    assert "sk-aB1" not in out
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "ghp_" not in out
    assert "PRIVATE KEY" not in out
    assert out.count("[REDACTED]") >= 5
    assert "and" in out  # non-secret text survives


def test_redact_leaves_plain_text_untouched():
    assert redact("price the annual plan at $99") == "price the annual plan at $99"


def test_ask_redacts_state_before_sending_and_trace_stores_digest_not_raw(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("JEV_TEST_KEY", "k")
    calls = install_urlopen(monkeypatch, [canned_payload()])
    secret_state = "use key sk-aB1aB1aB1aB1aB1aB1aB1aB1aB1aB1 for the call"
    trace = tmp_path / "trace.jsonl"

    ask(secret_state, {"q": {"type": "noul", "instructions": "i"}},
        credential_ref="JEV_TEST_KEY", trace_path=trace)

    assert "sk-aB1" not in calls[0]["body"]["state"]
    assert calls[0]["body"]["state"] == redact(secret_state)
    raw = trace.read_text()
    assert "sk-aB1" not in raw
    rec = json.loads(raw.splitlines()[0])
    assert rec["state_digest"] == hashlib.sha256(
        redact(secret_state).encode("utf-8")
    ).hexdigest()
    assert len(rec["state_digest"]) == 64


# --- thresholds ---


def test_act_threshold_policy():
    assert act(1.0) == "act"
    assert act(0.95) == "act"
    assert act(0.949999) == "escalate"
    assert act(0.5) == "escalate"
    assert act(0.050001) == "escalate"
    assert act(0.05) == "skip"
    assert act(0.0) == "skip"


def test_confidence_formula():
    assert confidence(3, 0.8) == pytest.approx((3 * 0.8 - 1) / (3 - 1))
    assert confidence(3, 0.8) == pytest.approx(0.7)
    assert confidence(1, 0.62) == pytest.approx(0.62)
    assert confidence(4, 1.0) == pytest.approx(1.0)
    assert confidence(3, 0.97) == pytest.approx(0.955)


def test_resample_majority():
    assert resample(["a", "a", "b"]) == "a"
    assert resample(["b", "b", "a"]) == "b"
    assert resample(["a", "b", "c"]) is None  # 3-way split: no majority
    assert resample([]) is None
    assert resample(["only"]) == "only"
