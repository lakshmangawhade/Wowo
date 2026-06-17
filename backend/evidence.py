# evidence.py — evidence packet normalization with scoped windows
from __future__ import annotations

import re
from typing import Any

SECTION_PATTERNS = (
    (r"(?is)\b(?:whereas|recitals?)\b.{0,200}", "recitals"),
    (r"(?is)\b(?:scope|purpose|objective)\b.{0,400}", "scope"),
    (r"(?is)\b(?:definitions?|means)\b.{0,400}", "definitions"),
    (r"(?is)\b(?:article\s+\d+|section\s+\d+)\b.{0,500}", "operative"),
    (r"(?is)\b(?:sanctions?|penalties|fine|criminal)\b.{0,300}", "sanctions"),
)


def _first_match(text: str, pattern: str, max_len: int) -> str:
    match = re.search(pattern, text)
    if not match:
        return ""
    snippet = match.group(0).strip()
    if len(snippet) > max_len:
        return snippet[:max_len].rstrip() + "…"
    return snippet


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def build_evidence_windows(
    input_doc: dict,
    *,
    max_body_chars: int = 8000,
    max_window_chars: int = 1200,
) -> dict[str, Any]:
    """Build a compact evidence packet with scoped windows instead of full body."""
    metadata = input_doc.get("metadata") or {}
    title = (
        input_doc.get("title")
        or input_doc.get("OriginalTitle")
        or metadata.get("dcterms:title")
        or metadata.get("DC.title")
        or ""
    )
    short_title = input_doc.get("ShortTitle") or ""
    description = (
        input_doc.get("ShortDescription")
        or input_doc.get("description")
        or metadata.get("DC.description")
        or metadata.get("DC.subject")
        or ""
    )
    body_text = input_doc.get("body_text") or input_doc.get("text") or ""
    body_truncated = _truncate(body_text, max_body_chars)

    windows: dict[str, str] = {}
    for pattern, name in SECTION_PATTERNS:
        snippet = _first_match(body_truncated, pattern, max_window_chars)
        if snippet:
            windows[name] = snippet

    if title and "title" not in windows:
        windows["title"] = _truncate(title, max_window_chars)
    if description and "description" not in windows:
        windows["description"] = _truncate(description, max_window_chars)

    return {
        "title": title,
        "short_title": short_title,
        "description": description,
        "body_text": body_truncated,
        "body_text_full_length": len(body_text),
        "source_url": input_doc.get("source_url_normalized") or input_doc.get("source_url") or "",
        "portal": input_doc.get("portal") or "",
        "metadata": {
            k: v for k, v in input_doc.items()
            if k not in ("body_text", "text")
        },
        "evidence_windows": windows,
    }


def build_evidence_packet(
    input_doc: dict,
    *,
    use_windows: bool = True,
    max_body_chars: int = 8000,
    max_window_chars: int = 1200,
) -> dict[str, Any]:
    if use_windows:
        return build_evidence_windows(
            input_doc,
            max_body_chars=max_body_chars,
            max_window_chars=max_window_chars,
        )

    metadata = input_doc.get("metadata") or {}
    return {
        "title": input_doc.get("title", input_doc.get("OriginalTitle", metadata.get("dcterms:title", ""))),
        "short_title": input_doc.get("ShortTitle", ""),
        "description": input_doc.get("ShortDescription", input_doc.get("description", "")),
        "body_text": _truncate(input_doc.get("body_text") or input_doc.get("text") or "", max_body_chars),
        "source_url": input_doc.get("source_url_normalized", input_doc.get("source_url", "")),
        "portal": input_doc.get("portal", ""),
        "metadata": {k: v for k, v in input_doc.items() if k not in ("body_text", "text")},
    }


def evidence_corpus(evidence: dict) -> str:
    """Single searchable text blob for rule-based routing."""
    parts = [
        evidence.get("title", ""),
        evidence.get("short_title", ""),
        evidence.get("description", ""),
        evidence.get("body_text", ""),
    ]
    for window in (evidence.get("evidence_windows") or {}).values():
        parts.append(window)
    meta = evidence.get("metadata") or {}
    if isinstance(meta, dict):
        for key in ("DC.subject", "dcterms:title", "DC.description"):
            if meta.get(key):
                parts.append(str(meta[key]))
    return "\n".join(p for p in parts if p).lower()
