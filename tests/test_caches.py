"""U7 tests: verdict + negative caches (R8, KTD7, AE4)."""
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from router.caches import Caches, normalize_prompt, prompt_fingerprint
from router.catalog import Catalog

VERDICT = {"inject": ["skills/pricing"], "model": "jev", "score": 0.83}


@pytest.fixture()
def cat(tmp_path):
    c = Catalog(tmp_path / "catalog.db")
    yield c
    c.close()


@pytest.fixture()
def caches(cat):
    return Caches(cat)


def test_tables_created_inside_catalog_file(cat, caches):
    names = {r[0] for r in cat.rows("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"verdict_cache", "negative_cache"} <= names
    vcols = {r[1] for r in cat.rows("PRAGMA table_info(verdict_cache)")}
    assert vcols == {"prompt_fingerprint", "catalog_fingerprint", "verdict_json", "ts"}
    ncols = {r[1] for r in cat.rows("PRAGMA table_info(negative_cache)")}
    assert ncols == {"prompt_fingerprint", "catalog_fingerprint", "ts"}


def test_verdict_roundtrip_and_latest_wins(caches, cat):
    pfp = prompt_fingerprint("route my pricing question")
    cfp = cat.fingerprint()
    assert caches.lookup_verdict(pfp, cfp) is None
    caches.store_verdict(pfp, cfp, VERDICT)
    assert caches.lookup_verdict(pfp, cfp) == VERDICT
    caches.store_verdict(pfp, cfp, {"inject": []})
    assert caches.lookup_verdict(pfp, cfp) == {"inject": []}


def test_replay_identical_prompt_unchanged_catalog_ae4(caches, cat, monkeypatch):
    # AE4: identical prompt + unchanged catalog replays from cache in <50ms
    # with zero Jev calls. The replay path must be pure SQLite reads.
    import router.jev as jev

    def _bomb(*a, **k):
        raise AssertionError("Jev must not be called on the replay path")

    monkeypatch.setattr(jev, "ask", _bomb)
    monkeypatch.setattr(jev, "_post_with_retry", _bomb)

    prompt = "How should I price my new SaaS tier?"
    pfp = prompt_fingerprint(prompt)

    # Turn 1: cold miss → the pipeline would call Jev; store the verdict.
    cfp1 = cat.fingerprint()
    assert caches.lookup_verdict(pfp, cfp1) is None
    caches.store_verdict(pfp, cfp1, VERDICT)

    # Turn 2: identical prompt, catalog untouched, fingerprint recomputed live.
    t0 = time.perf_counter()
    assert caches.is_negative(pfp, cat.fingerprint()) is False
    replayed = caches.lookup_verdict(pfp, cat.fingerprint())
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert replayed == VERDICT
    assert elapsed_ms < 50


def test_reindex_invalidates_both_caches(caches, cat):
    pfp = prompt_fingerprint("pricing")
    nfp = prompt_fingerprint("noop prompt")
    cfp = cat.fingerprint()
    caches.store_verdict(pfp, cfp, VERDICT)
    caches.store_negative(nfp, cfp)

    # Reindex: content arrives via the indexer → fingerprint changes.
    cat.ensure_type("skill")
    cat.upsert("skill", {"id": "pricing", "name": "pricing", "enabled": 1})

    assert cat.fingerprint() != cfp
    assert caches.lookup_verdict(pfp, cat.fingerprint()) is None
    assert caches.is_negative(nfp, cat.fingerprint()) is False


def test_near_identical_prompt_is_miss(caches, cat):
    cfp = cat.fingerprint()
    caches.store_verdict(prompt_fingerprint("route pricing question"), cfp, VERDICT)
    near = prompt_fingerprint("route pricing questions")
    assert near != prompt_fingerprint("route pricing question")
    assert caches.lookup_verdict(near, cfp) is None
    assert caches.is_negative(near, cfp) is False


def test_negative_entry_skips_on_repeat(caches, cat):
    cfp = cat.fingerprint()
    pfp = prompt_fingerprint("tell me a joke")
    assert caches.is_negative(pfp, cfp) is False
    caches.store_negative(pfp, cfp)
    assert caches.is_negative(pfp, cfp) is True


def test_normalization_equivalence(caches, cat):
    assert normalize_prompt("  A\t B\nC ") == "a b c"
    assert (
        prompt_fingerprint("  Route   THE\npricing question  ")
        == prompt_fingerprint("route the pricing question")
    )
    cfp = cat.fingerprint()
    caches.store_verdict(prompt_fingerprint("Route THE pricing question"), cfp, VERDICT)
    assert caches.lookup_verdict(prompt_fingerprint("route the pricing question"), cfp) == VERDICT


def test_fingerprint_stable_across_cache_writes(caches, cat):
    # Caller keys entries by catalog.fingerprint(); cache rows must not feed
    # that digest or every store would invalidate the cache (KTD7).
    f0 = cat.fingerprint()
    caches.store_verdict(prompt_fingerprint("p"), f0, VERDICT)
    caches.store_negative(prompt_fingerprint("q"), f0)
    assert cat.fingerprint() == f0


def test_store_verdict_clears_negative_twin(caches, cat):
    # Last write wins for a (prompt_fp, catalog_fp) key across both tables.
    cfp = cat.fingerprint()
    pfp = prompt_fingerprint("twin")
    caches.store_negative(pfp, cfp)
    caches.store_verdict(pfp, cfp, VERDICT)
    assert caches.is_negative(pfp, cfp) is False
    assert caches.lookup_verdict(pfp, cfp) == VERDICT


def test_ts_recorded_as_utc_aware(caches, cat):
    cfp = cat.fingerprint()
    caches.store_verdict(prompt_fingerprint("ts"), cfp, {})
    caches.store_negative(prompt_fingerprint("ts2"), cfp)
    vts = cat.rows("SELECT ts FROM verdict_cache")[0][0]
    nts = cat.rows("SELECT ts FROM negative_cache")[0][0]
    for ts in (vts, nts):
        assert datetime.fromisoformat(ts).tzinfo is not None
