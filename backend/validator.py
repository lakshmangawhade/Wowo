# validator.py — post-pipeline validation and repair (km_00 step 10)
from __future__ import annotations

import re
from typing import Any

MAX_SPECIFIC_TOPICS = 5
MAX_SECTORS = 5
MAX_ESRS = 7


def _split_labels(text: str) -> list[str]:
    parts = re.split(r"[;,]", text or "")
    labels = [p.strip() for p in parts if p.strip()]
    deduped: list[str] = []
    seen: set[str] = set()
    for label in labels:
        key = label.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(label)
    return deduped


def _join_labels(labels: list[str]) -> str:
    return "; ".join(labels)


def validate_and_repair(final: dict[str, Any]) -> dict[str, Any]:
    """
    Enforce max item counts, deduplicate labels, and strip empty fields.
    """
    repaired = dict(final)
    warnings: list[str] = []

    topic_labels = _split_labels(repaired.get("SpecificTopic", ""))
    if len(topic_labels) > MAX_SPECIFIC_TOPICS:
        warnings.append(f"SpecificTopic truncated from {len(topic_labels)} to {MAX_SPECIFIC_TOPICS}")
        topic_labels = topic_labels[:MAX_SPECIFIC_TOPICS]
    repaired["SpecificTopic"] = _join_labels(topic_labels)

    family_labels = _split_labels(repaired.get("SpecificTopicFamily", ""))
    if len(family_labels) > MAX_SPECIFIC_TOPICS:
        family_labels = family_labels[:MAX_SPECIFIC_TOPICS]
    repaired["SpecificTopicFamily"] = _join_labels(family_labels)

    sector_labels = _split_labels(repaired.get("ApplicableSectors", ""))
    if len(sector_labels) > MAX_SECTORS:
        warnings.append(f"ApplicableSectors truncated from {len(sector_labels)} to {MAX_SECTORS}")
        sector_labels = sector_labels[:MAX_SECTORS]
    repaired["ApplicableSectors"] = _join_labels(sector_labels)

    esrs_labels = _split_labels(repaired.get("ClosestESRSTopics", ""))
    if len(esrs_labels) > MAX_ESRS:
        warnings.append(f"ClosestESRSTopics truncated from {len(esrs_labels)} to {MAX_ESRS}")
        esrs_labels = esrs_labels[:MAX_ESRS]
    repaired["ClosestESRSTopics"] = _join_labels(esrs_labels)

    repaired["_validation"] = {
        "repaired": bool(warnings),
        "warnings": warnings,
    }
    return repaired
