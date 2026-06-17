# esrs_lookup.py — deterministic SpecificTopic → ESRS mapping
from __future__ import annotations

import json
import re
from pathlib import Path

_CROSSWALK: dict[str, list[str]] | None = None


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


def load_esrs_crosswalk(km_dir: Path) -> dict[str, list[str]]:
    global _CROSSWALK
    if _CROSSWALK is not None:
        return _CROSSWALK

    path = km_dir / "km_03_esrs_mapping.json"
    if not path.exists():
        _CROSSWALK = {}
        return _CROSSWALK

    km = json.loads(path.read_text(encoding="utf-8"))
    raw = (km.get("topic_to_esrs_crosswalk") or {}).get("mapping") or {}
    crosswalk: dict[str, list[str]] = {}
    for topic, esrs_list in raw.items():
        if isinstance(esrs_list, list):
            crosswalk[topic.strip()] = [str(x).strip() for x in esrs_list if str(x).strip()]
        elif esrs_list:
            crosswalk[topic.strip()] = [str(esrs_list).strip()]

    _CROSSWALK = crosswalk
    return crosswalk


def lookup_esrs_topics(
    specific_topics: str,
    km_dir: Path,
    *,
    max_topics: int = 7,
) -> dict:
    """
    Map semicolon-separated SpecificTopic labels to ESRS via crosswalk.
    Returns orchestrator-compatible ESRS output.
    """
    crosswalk = load_esrs_crosswalk(km_dir)
    topics = _split_labels(specific_topics)
    matched: list[str] = []
    unmatched: list[str] = []

    for topic in topics:
        esrs = crosswalk.get(topic)
        if not esrs:
            # Case-insensitive fallback
            lower_map = {k.lower(): v for k, v in crosswalk.items()}
            esrs = lower_map.get(topic.lower())
        if esrs:
            for label in esrs:
                if label not in matched:
                    matched.append(label)
        else:
            unmatched.append(topic)

    matched = matched[:max_topics]
    return {
        "final_closest_esrs_topics": matched,
        "closest_esrs": matched,
        "esrs_topics": matched,
        "unmatched_specific_topics": unmatched,
        "_esrs_method": "lookup",
    }


def invalidate_esrs_cache() -> None:
    global _CROSSWALK
    _CROSSWALK = None
