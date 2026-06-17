# extraction_rules.py — deterministic non-tag field extraction
from __future__ import annotations

import re
from typing import Any


REGULATION_TYPES = (
    ("Directive", r"\bdirective\b"),
    ("Regulation", r"\bregulation\b"),
    ("Decision", r"\bdecision\b"),
    ("Convention", r"\bconvention\b"),
    ("Recommendation", r"\brecommendation\b"),
)


def _meta(input_doc: dict, *keys: str) -> str:
    metadata = input_doc.get("metadata") or {}
    for key in keys:
        val = input_doc.get(key) or metadata.get(key)
        if val:
            return str(val).strip()
    return ""


def _detect_regulation_type(title: str, body: str) -> str | None:
    corpus = f"{title}\n{body[:2000]}".lower()
    for label, pattern in REGULATION_TYPES:
        if re.search(pattern, corpus):
            return label
    return None


def _detect_jurisdiction(portal: str, body: str, metadata: dict) -> str | None:
    portal = (portal or "").lower()
    if "eur-lex" in portal or "europa.eu" in portal:
        return "European Union"
    creator = str(metadata.get("dcterms:creator") or metadata.get("DC.creator") or "")
    if "European Union" in creator or "Council of the European Union" in creator:
        return "European Union"
    return None


def _detect_sanctions(body: str) -> str:
    corpus = (body or "")[:12000].lower()
    if re.search(r"\b(?:criminal|fine|penalty|penalties|sanctions?)\b", corpus):
        return "Yes"
    return "No"


def _short_title(input_doc: dict, title: str) -> str:
    if input_doc.get("ShortTitle"):
        return str(input_doc["ShortTitle"]).strip()
    if not title:
        return ""
    # Prefer text before first comma or " of "
    head = re.split(r",|\sof\s+\d", title, maxsplit=1)[0].strip()
    return head[:120]


def _short_description(input_doc: dict, title: str, body: str) -> str:
    if input_doc.get("ShortDescription"):
        return str(input_doc["ShortDescription"]).strip()
    meta_desc = _meta(input_doc, "description")
    if meta_desc:
        return meta_desc[:400]
    # First substantive paragraph from body
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", body) if len(p.strip()) > 40]
    if paragraphs:
        return paragraphs[0][:400]
    return title[:400] if title else ""


def extract_metadata_fields(input_doc: dict) -> dict[str, Any]:
    """
    Extract non-tag fields from structured input JSON without an LLM.
    Returns orchestrator-compatible field names.
    """
    metadata = input_doc.get("metadata") or {}
    title = _meta(input_doc, "title", "OriginalTitle", "dcterms:title", "DC.title")
    body = input_doc.get("body_text") or input_doc.get("text") or ""

    adoption = _meta(input_doc, "extracted_date_of_adoption", "Dateofadoption")
    entry_force = _meta(input_doc, "extracted_entry_into_force_date", "EntryIntoForceDate")
    amendments = _meta(input_doc, "extracted_amendments", "Amendedordevelopedbyifany")
    portal = input_doc.get("portal") or ""

    result = {
        "Date_LastChange": None,
        "Topic1": _detect_jurisdiction(portal, body, metadata),
        "Topic2": None,
        "Topic3": None,
        "ShortTitle": _short_title(input_doc, title),
        "OriginalTitle": title or None,
        "ShortDescription": _short_description(input_doc, title, body),
        "TypeofRegulation": _detect_regulation_type(title, body),
        "Source": portal or None,
        "Amendedordevelopedbyifany": amendments or "N/A",
        "Dateofadoption": adoption or None,
        "EntryIntoForceDate": entry_force or None,
        "Sanctions": _detect_sanctions(body),
        "_extraction_method": "rules",
    }

    subject = metadata.get("DC.subject") or ""
    if subject:
        topics = [t.strip() for t in str(subject).split(",") if t.strip()]
        if topics:
            result["Topic2"] = topics[0][:120]
        if len(topics) > 1:
            result["Topic3"] = topics[1][:120]

    return result


REQUIRED_EXTRACTION_FIELDS = (
    "ShortTitle",
    "OriginalTitle",
    "ShortDescription",
    "TypeofRegulation",
    "Topic1",
)


def extraction_is_complete(extraction: dict) -> bool:
    for field in REQUIRED_EXTRACTION_FIELDS:
        if not extraction.get(field):
            return False
    return True
