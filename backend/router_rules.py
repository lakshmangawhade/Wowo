import json
import re
from pathlib import Path
from typing import Any

from backend.evidence import evidence_corpus
from backend.family_registry import STAGE_FAMILY_MAP, normalize_routed_families

_ROUTER_SIGNALS: dict[str, list[str]] | None = None


def _terms_from_run_when(lines: list[str]) -> list[str]:
    """Extract high-signal quoted phrases from run_when rules (skip comma-split noise)."""
    terms: list[str] = []
    for line in lines:
        for quoted in re.findall(r'"([^"]{3,80})"', line):
            term = quoted.lower().strip()
            if len(term) >= 3:
                terms.append(term)
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        if term not in seen:
            seen.add(term)
            deduped.append(term)
    return deduped[:30]


def load_router_signals(km_dir: Path) -> dict[str, list[str]]:
    global _ROUTER_SIGNALS
    if _ROUTER_SIGNALS is not None:
        return _ROUTER_SIGNALS

    path = km_dir / "km_01a_specific_topic_family_router.json"
    if not path.exists():
        _ROUTER_SIGNALS = {}
        return _ROUTER_SIGNALS

    try:
        router = json.loads(path.read_text(encoding="utf-8"))
        signals: dict[str, list[str]] = {}
        for family in router.get("families", []):
            slug = family.get("slug")
            if slug in STAGE_FAMILY_MAP:
                signals[slug] = _terms_from_run_when(family.get("run_when", []))
        _ROUTER_SIGNALS = signals
    except Exception:
        _ROUTER_SIGNALS = {}

    return _ROUTER_SIGNALS


def invalidate_router_signals_cache() -> None:
    global _ROUTER_SIGNALS
    _ROUTER_SIGNALS = None


# ---------------------------------------------------------------------------
# Exclusion signals: if these phrases appear as the PRIMARY subject, do NOT
# route to the given family (even if some terms score positively).
# ---------------------------------------------------------------------------
_EXCLUSION_SIGNALS: dict[str, list[str]] = {
    "pollution_chemicals_air_soil": [
        # Water-primary docs should go to water_marine_fisheries, not here
        "wastewater treatment",
        "waste-water treatment",
        "water framework",
        "marine strategy",
        "river basin",
        "groundwater",
        "drinking water",
        "bathing water",
        "water quality",
        "water body",
        "water bodies",
        "marine environment",
        "nitrates directive",
        # Consumer/product-primary docs should go to consumers_products_privacy
        "defective products",
        "product liability",
        "consumer protection",
        "product safety",
        # GMO/traceability goes to consumers_products_privacy
        "gmo traceability",
        "genetically modified organism",
    ],
    "water_marine_fisheries": [
        # Pure chemical/industrial docs that only mention water incidentally
        "reach regulation",
        "persistent organic pollutants",
        "ozone-depleting",
        "industrial emissions directive",
        "large combustion plants",
    ],
}

# Priority order: if two families both score above threshold, prefer the one
# listed earlier when the document's title/scope clearly points to it.
_PRIORITY_RULES: list[tuple[list[str], str]] = [
    # If title contains water/marine/wastewater keywords → water_marine_fisheries wins
    (["wastewater", "waste-water", "water framework", "marine strategy",
      "river basin", "groundwater", "drinking water", "bathing water",
      "water quality", "nitrate", "marine environment", "fisheries"],
     "water_marine_fisheries"),
    # If title contains product/consumer/GMO → consumers_products_privacy wins
    (["defective products", "product liability", "consumer protection",
      "product safety", "gmo", "genetically modified", "traceability regulation",
      "food information", "toy safety", "cosmetics", "textile"],
     "consumers_products_privacy"),
    # Governance/reporting keywords → governance_reporting_conduct wins
    (["whistleblow", "anti-corruption", "anti-bribery", "non-financial reporting",
      "sustainability reporting", "esg reporting", "due diligence", "supply chain",
      "corporate governance", "fundamental rights charter"],
     "governance_reporting_conduct"),
    # Biodiversity/habitats → biodiversity_ecosystems_land wins over pollution
    (["habitats directive", "natura 2000", "biodiversity", "species conservation",
      "invasive species", "wildlife trade", "ecosystem restoration"],
     "biodiversity_ecosystems_land"),
    # End-of-life vehicles → waste_circular_products wins
    (["end-of-life vehicles", "end of life vehicles", "weee", "batteries directive",
      "packaging waste", "circular economy", "extended producer responsibility"],
     "waste_circular_products"),
]


def _apply_exclusions(corpus: str, scores: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Remove families from scores if exclusion signals are present in corpus."""
    filtered = []
    for slug, score in scores:
        exclusions = _EXCLUSION_SIGNALS.get(slug, [])
        if any(exc in corpus for exc in exclusions):
            continue
        filtered.append((slug, score))
    return filtered


def _apply_priority(title_corpus: str, scores: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Boost a family to the top if a priority rule matches the document title/scope."""
    for keywords, priority_slug in _PRIORITY_RULES:
        if any(kw in title_corpus for kw in keywords):
            # Move priority_slug to front if it's in scores
            reordered = [(s, sc) for s, sc in scores if s == priority_slug]
            reordered += [(s, sc) for s, sc in scores if s != priority_slug]
            if reordered:
                return reordered
    return scores


def score_families(
    evidence: dict,
    km_dir: Path,
) -> list[tuple[str, float]]:
    try:
        corpus = evidence_corpus(evidence)
    except Exception:
        return []

    if not corpus:
        return []

    signals = load_router_signals(km_dir)
    scores: list[tuple[str, float]] = []

    for slug, terms in signals.items():
        score = 0.0
        for term in terms:
            if not term:
                continue
            # Short quoted phrases: substring match
            if len(term) <= 40 and term in corpus:
                score += 1.0 + min(len(term) / 40.0, 1.0)
                continue
            # Long run_when sentences: score by significant word overlap
            words = [w for w in re.findall(r"\b[a-z]{4,}\b", term) if w not in _STOPWORDS]
            if not words:
                continue
            hits = sum(1 for w in words if w in corpus)
            if hits >= 2:
                score += hits * 0.75

        if score > 0:
            scores.append((slug, score))

    scores.sort(key=lambda item: item[1], reverse=True)

    # Apply exclusion filter — remove families whose primary-subject signals
    # indicate this doc belongs elsewhere
    scores = _apply_exclusions(corpus, scores)

    # Apply priority rules using title+scope as a narrow corpus
    title_scope = (
        (evidence.get("title") or "") + " " +
        (evidence.get("short_title") or "") + " " +
        (evidence.get("description") or "")
    ).lower()
    scores = _apply_priority(title_scope, scores)

    return scores


_STOPWORDS = frozenset({
    "source", "mentions", "regulates", "ordinary", "central", "legal",
    "when", "only", "with", "from", "that", "this", "their", "also",
    "more", "than", "into", "through", "unless", "explicit", "generic",
})


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
    try:
        scores = score_families(evidence, km_dir)
    except Exception:
        return None, 0.0

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