# router_rules.py — keyword-based family routing with LLM fallback
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from evidence import evidence_corpus
from family_registry import STAGE_FAMILY_MAP, normalize_routed_families

_ROUTER_SIGNALS: dict[str, list[str]] | None = None


def _terms_from_run_when(lines: list[str]) -> list[str]:
    terms: list[str] = []
    for line in lines:
        line_lower = line.lower()
        for quoted in re.findall(r'"([^"]{3,60})"', line):
            terms.append(quoted.lower())
        for chunk in re.split(r"[,;]", line_lower):
            chunk = chunk.strip()
            if len(chunk) >= 4 and not chunk.startswith("the source"):
                terms.append(chunk[:60])
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        term = term.strip()
        if term and term not in seen:
            seen.add(term)
            deduped.append(term)
    return deduped[:25]


def load_router_signals(km_dir: Path) -> dict[str, list[str]]:
    global _ROUTER_SIGNALS
    if _ROUTER_SIGNALS is not None:
        return _ROUTER_SIGNALS

    path = km_dir / "km_01a_specific_topic_family_router.json"
    if not path.exists():
        _ROUTER_SIGNALS = {}
        return _ROUTER_SIGNALS

    router = json.loads(path.read_text(encoding="utf-8"))
    signals: dict[str, list[str]] = {}
    for family in router.get("families", []):
        slug = family.get("slug")
        if slug in STAGE_FAMILY_MAP:
            signals[slug] = _terms_from_run_when(family.get("run_when", []))

    _ROUTER_SIGNALS = signals
    return signals


def score_families(
    evidence: dict,
    km_dir: Path,
) -> list[tuple[str, float]]:
    corpus = evidence_corpus(evidence)
    signals = load_router_signals(km_dir)
    scores: list[tuple[str, float]] = []

    for slug, terms in signals.items():
        score = 0.0
        for term in terms:
            if term and term in corpus:
                score += 1.0 + min(len(term) / 40.0, 1.0)
        if score > 0:
            scores.append((slug, score))

    scores.sort(key=lambda item: item[1], reverse=True)
    return scores


def route_families_by_rules(
    evidence: dict,
    km_dir: Path,
    *,
    min_score: float = 2.0,
    min_margin: float = 1.0,
    max_families: int = 2,
) -> tuple[dict | None, float]:
    """
    Return router-shaped output when confidence is high enough, else None.
    Confidence is based on top score and margin over second place.
    """
    scores = score_families(evidence, km_dir)
    if not scores:
        return None, 0.0

    top_slug, top_score = scores[0]
    second_score = scores[1][1] if len(scores) > 1 else 0.0
    margin = top_score - second_score

    if top_score < min_score or margin < min_margin:
        return None, top_score / (top_score + second_score + 1.0)

    selected = [top_slug]
    if len(scores) > 1 and scores[1][1] >= min_score and margin < top_score * 0.5:
        selected.append(scores[1][0])
    selected = selected[:max_families]

    router_out = {
        "topic_families_to_run": [
            {
                "family_id": slug,
                "slug": slug,
                "confidence": round(min(0.99, 0.5 + top_score / 10.0), 2),
                "reason": "rule-based keyword routing",
                "evidence_excerpt": evidence.get("title", "")[:160],
            }
            for slug in selected
        ],
        "_routing_method": "rules",
    }
    confidence = top_score / (top_score + second_score + 1.0)
    return router_out, confidence


def router_output_to_families(router_out: dict) -> list[str]:
    return normalize_routed_families(router_out)
