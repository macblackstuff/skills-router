"""Knowledge section injection (U8, R6/KTD8, covers AE2).

`knowledge_inject` turns gate-winning knowledge ids into injection blocks
carrying the VERBATIM section body captured in the catalog at index time —
no summarizer, no live-file reads. Drift guard: sha256(body) must equal
extras.body_hash or the section is skipped with a stale notice; wrong text
is never injected. Bodies cap at BODY_CHAR_BUDGET chars (token budget) with
a truncation marker appended after the verbatim prefix.

Winner entries are gate survivor ids: "knowledge:<row-id>" qualified form
or a bare "<row-id>"; entries of other types are ignored (pointer types get
their R5 line from the pipeline, not here).

Header: "=== [knowledge] <page> — <section heading> ==="; a heading-less
page has no separate section to name, so its header is page-only.
"""
from __future__ import annotations

import hashlib
import json

from router.catalog import Catalog

BODY_CHAR_BUDGET = 4000
TRUNCATION_MARKER = f"\n[truncated at {BODY_CHAR_BUDGET} chars]"
STALE_NOTICE = "knowledge stale: {rid} — run router index"


def _knowledge_id(entry: str) -> str | None:
    """Row id for a knowledge winner entry; None for other types."""
    type_, _, rid = entry.partition(":")
    if type_ == "knowledge":
        return rid
    if rid:
        return None  # some other qualified type
    return entry  # bare id: knowledge assumed


def knowledge_inject(winner_ids: list[str], catalog: Catalog) -> list[str]:
    """Injection blocks for knowledge winners; verbatim bodies, never stale."""
    lines: list[str] = []
    for entry in winner_ids:
        rid = _knowledge_id(entry)
        if rid is None:
            continue
        rows = catalog.rows("SELECT extras FROM knowledge WHERE id = ?", (rid,))
        if not rows:
            continue
        try:
            extras = json.loads(rows[0][0] or "{}")
            page = extras["page"]
            body = extras["body"]
            body_hash = extras["body_hash"]
        except (TypeError, ValueError, KeyError):
            lines.append(STALE_NOTICE.format(rid=rid))  # unverifiable text
            continue
        digest = hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()
        if digest != body_hash:
            lines.append(STALE_NOTICE.format(rid=rid))
            continue
        section = extras.get("heading_path", "").split(" > ")[-1].strip()
        header = (
            f"=== [knowledge] {page} — {section} ==="
            if section and section != page
            else f"=== [knowledge] {page} ==="
        )
        if len(body) > BODY_CHAR_BUDGET:
            body = body[:BODY_CHAR_BUDGET] + TRUNCATION_MARKER
        lines.append(f"{header}\n{body}")
    return lines
