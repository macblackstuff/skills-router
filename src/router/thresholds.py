"""Threshold policy for Jev verdicts (KTD2): act / skip / escalate in code."""
from __future__ import annotations

from collections import Counter
from typing import Any, Hashable, List, Optional

ACT_THRESHOLD = 0.95
SKIP_THRESHOLD = 0.05


def act(p: float) -> str:
    """Threshold policy over a Noul yes-probability.

    p >= 0.95 -> "act", p <= 0.05 -> "skip", otherwise "escalate".
    """
    if p >= ACT_THRESHOLD:
        return "act"
    if p <= SKIP_THRESHOLD:
        return "skip"
    return "escalate"


def confidence(n: int, p_max: float) -> float:
    """Confidence that the modal answer is not chance, from n resamples.

    (n * p_max - 1) / (n - 1) for n > 1; the raw p_max for a single sample.
    """
    if n > 1:
        return (n * p_max - 1) / (n - 1)
    return p_max


def resample(values: List[Hashable], k: int = 3) -> Optional[Any]:
    """Majority vote across resampled answers; None when there is no majority.

    The Jev API exposes no seed (verified 2026-09-30), so gates that need
    stability run k samples and vote. The k most recent samples count; a
    strict majority (> half) wins, a split returns None and the caller
    escalates.
    """
    window = list(values)[-k:]
    if not window:
        return None
    counts = Counter(window)
    winner, n = counts.most_common(1)[0]
    return winner if n > len(window) / 2 else None
