# pipeline.py — TagForge hybrid multi-stage tagging pipeline
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from dataclasses import replace

from esrs_lookup import lookup_esrs_topics
from evidence import build_evidence_packet as _build_evidence_packet
from extraction_rules import extract_metadata_fields, extraction_is_complete
from family_registry import (
    STAGE_FAMILY_MAP,
    format_router_families,
    normalize_routed_families,
)
from pipeline_cache import get_cached_upstream, update_doc_context
from pipeline_config import PipelineConfig, load_pipeline_config
from router_rules import route_families_by_rules, router_output_to_families
from validator import validate_and_repair

ALL_PIPELINE_STAGES = [
    "km_04_orchestrator_extraction",
    "km_01a_specific_topic_family_router",
    "family_st_kms",
    "km_01z_specific_topic_reconciler",
    "km_02_applicable_sectors",
    "km_03_esrs_mapping",
]

GT_COLUMNS = [
    "SpecificTopic",
    "SpecificTopicFamily",
    "ClosestESRSTopics",
    "ApplicableSectors",
]

EXTRACT_KEYS = {
    "km_01a_specific_topic_family_router": ["topic_families_to_run", "primary_family"],
    "km_01z_specific_topic_reconciler": ["final_specific_topics", "specific_topics", "SpecificTopic"],
    "km_02_applicable_sectors": ["final_applicable_sectors", "applicable_sectors", "sectors"],
    "km_03_esrs_mapping": ["final_closest_esrs_topics", "closest_esrs", "esrs_topics"],
    # Extraction produces non-tag metadata fields only — never SpecificTopic
    "km_04_orchestrator_extraction": [],
}

# Alternate key spellings LLMs may emit instead of canonical EXTRACT_KEYS names
_EXTRACT_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "final_specific_topics": ("specific_topics", "SpecificTopic", "specific_topic", "topics"),
    "final_applicable_sectors": ("applicable_sectors", "sectors", "ApplicableSectors"),
    "final_closest_esrs_topics": ("closest_esrs", "esrs_topics", "ClosestESRSTopics", "closest_esrs_topics"),
    "topic_families_to_run": ("primary_family", "families", "topic_families", "SpecificTopicFamily"),
}


def _is_schema_placeholder(text: str) -> bool:
    """True when a string is an output_contract template, not extracted data."""
    if not text or not isinstance(text, str):
        return False
    lower = text.lower().strip()
    if len(lower) > 160:
        return False
    markers = (
        "array of",
        "0.0-1.0",
        "yes|no",
        "required when",
        "canonical specific",
        "canonical tag",
        "label strings",
        "max 5",
    )
    return any(marker in lower for marker in markers)


def _lookup_obj_key(obj: dict, key: str) -> Any:
    """Case- and separator-insensitive dict lookup."""
    if key in obj:
        return obj[key]
    norm = re.sub(r"[_\s]", "", key).lower()
    for candidate, value in obj.items():
        if re.sub(r"[_\s]", "", str(candidate)).lower() == norm:
            return value
    return None


@dataclass
class PipelineState:
    extraction_out: dict = field(default_factory=dict)
    router_out: dict = field(default_factory=dict)
    family_candidates: list = field(default_factory=list)
    reconciler_out: dict = field(default_factory=dict)
    sectors_out: dict = field(default_factory=dict)
    esrs_out: dict = field(default_factory=dict)
    routed_families: list[str] = field(default_factory=list)
    methods: dict = field(default_factory=dict)


def load_km(km_dir: Path, filename: str) -> dict:
    p = km_dir / filename
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def build_evidence_packet(input_doc: dict, config: PipelineConfig | None = None) -> dict:
    cfg = config or load_pipeline_config()
    return _build_evidence_packet(
        input_doc,
        use_windows=cfg.use_evidence_windows,
        max_body_chars=cfg.max_body_chars,
        max_window_chars=cfg.max_evidence_window_chars,
    )


def format_km_query(km: dict, evidence: dict, extra_context: dict | None = None) -> str:
    km_str = json.dumps(km, ensure_ascii=False)
    input_payload = {"evidence_packet": evidence}
    if extra_context:
        input_payload.update(extra_context)
    input_str = json.dumps(input_payload, ensure_ascii=False)
    return (
        f"KNOWLEDGE MODEL — apply these rules exactly:\n{km_str}\n\n"
        f"INPUT for this call:\n{input_str}"
    )


def parse_json_response(raw: str) -> dict:
    """Parse LLM JSON response, handling markdown fences."""
    if not raw or not raw.strip():
        raise ValueError("Empty response from LLM")
    cleaned = re.sub(r"```json\s*|```\s*", "", raw).strip()

    # Try direct parse first
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Extract first balanced JSON object
    start = cleaned.find("{")
    if start == -1:
        raise ValueError(f"No JSON object in response: {raw[:200]}")
    depth = 0
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(cleaned[start : i + 1])
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSON in response: {raw[:200]}") from exc
    raise ValueError(f"Unclosed JSON object in response: {raw[:200]}")


def _extract_yes_tags(obj: dict) -> list[str]:
    """Extract labels from binary tag_decisions with answer=Yes."""
    decisions = obj.get("tag_decisions") or []
    labels: list[str] = []
    for item in decisions:
        if not isinstance(item, dict):
            continue
        if str(item.get("answer", "")).strip().lower() != "yes":
            continue
        tag = item.get("tag") or item.get("label") or item.get("name")
        if tag:
            labels.append(str(tag).strip())
    return labels


def _labels_from_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        # KM output_contract shape: {"value": [...], "confidence": ...}
        inner = value.get("value")
        if inner is not None and not (
            isinstance(inner, str) and _is_schema_placeholder(inner)
        ):
            nested = _labels_from_value(inner)
            if nested:
                return nested
        for key in (
            "labels",
            "topics",
            "topic",
            "specific_topic",
            "tags",
            "items",
            "value",
            "final_specific_topics",
            "final_specific_topics_from_this_family",
            "final_applicable_sectors",
            "final_closest_esrs_topics",
            "tag_decisions",
        ):
            if key in value:
                nested = _labels_from_value(value[key])
                if nested:
                    return nested
        return []
    if isinstance(value, list):
        labels: list[str] = []
        for item in value:
            if isinstance(item, dict):
                if str(item.get("answer", "")).strip().lower() == "no":
                    continue
                tag = item.get("label") or item.get("tag") or item.get("name") or item.get("slug")
                if tag and not _is_schema_placeholder(str(tag)):
                    labels.append(str(tag).strip())
            elif item and not _is_schema_placeholder(str(item)):
                labels.append(str(item).strip())
        return labels
    if isinstance(value, str):
        if _is_schema_placeholder(value):
            return []
        return [part.strip() for part in re.split(r"[;,]", value) if part.strip()]
    return []


def _extract_field(obj: dict, keys: list[str]) -> str:
    """
    Extract a semicolon-joined string from LLM output.
    Handles binary tag_decisions, output_contract shapes, and plain lists.
    """
    if not obj:
        return ""

    # Unwrap output_contract wrapper if present
    contract = obj.get("output_contract")
    if isinstance(contract, dict):
        nested = _extract_field(contract, keys)
        if nested:
            return nested

    # Binary KM: tag_decisions with Yes answers
    yes_tags = _extract_yes_tags(obj)
    if yes_tags:
        return "; ".join(yes_tags)

    # Common final-output keys used by family / reconciler KMs
    for direct_key in (
        "final_specific_topics",
        "final_specific_topics_from_this_family",
        "final_closest_esrs_topics",
        "final_applicable_sectors",
        "specific_topics",
        "SpecificTopic",
        "specific_topic",
        "topic",
        "closest_esrs",
        "esrs_topics",
        "applicable_sectors",
        "sectors",
        "topic_families_to_run",
        "primary_family",
    ):
        value = _lookup_obj_key(obj, direct_key)
        if value is not None:
            labels = _labels_from_value(value)
            if labels:
                if direct_key in ("topic_families_to_run", "primary_family"):
                    return format_router_families(obj)
                return "; ".join(labels)

    expanded_keys: list[str] = list(keys)
    for key in keys:
        expanded_keys.extend(_EXTRACT_KEY_ALIASES.get(key, ()))

    seen: set[str] = set()
    for key in expanded_keys:
        if key in seen:
            continue
        seen.add(key)
        value = _lookup_obj_key(obj, key)
        if value is None:
            continue

        if isinstance(value, dict):
            inner = value.get("value")
            if inner is not None and not (
                isinstance(inner, str) and _is_schema_placeholder(inner)
            ):
                labels = _labels_from_value(inner)
                if labels:
                    return "; ".join(labels)
            labels = _labels_from_value(value)
            if labels:
                if key in ("topic_families_to_run", "primary_family"):
                    return format_router_families(obj)
                return "; ".join(labels)
            if key in ("topic_families_to_run", "primary_family"):
                return format_router_families(obj)
            continue

        labels = _labels_from_value(value)
        if labels:
            if key in ("topic_families_to_run", "primary_family") and isinstance(value, list) and value and isinstance(value[0], dict):
                return format_router_families(obj)
            return "; ".join(labels)

    # Last resort: scan every top-level value for extractable labels
    for value in obj.values():
        if isinstance(value, (dict, list, str)):
            labels = _labels_from_value(value)
            if labels:
                return "; ".join(labels)

    return ""


def _extract_scalar_field(obj: dict, field_name: str) -> str:
    """Return one named extraction field as a plain string for stage scoring."""
    if not obj or not field_name:
        return ""
    val = _lookup_obj_key(obj, field_name)
    if val is None:
        return ""
    if isinstance(val, (dict, list)):
        labels = _labels_from_value(val)
        if labels:
            return "; ".join(labels)
        return ""
    text = str(val).strip()
    if not text or text.lower() == "none":
        return ""
    return text


def _call_llm(call_fab_agent: Callable[[str], str], query: str) -> dict:
    raw = call_fab_agent(query)
    return parse_json_response(raw)


def _run_extraction(
    input_doc: dict,
    evidence: dict,
    km_dir: Path,
    call_fab_agent: Callable[[str], str],
    config: PipelineConfig,
) -> tuple[dict, str]:
    if config.use_rule_extraction:
        ruled = extract_metadata_fields(input_doc)
        if extraction_is_complete(ruled):
            return ruled, "rules"

    km_extraction = load_km(km_dir, "km_04_orchestrator_extraction.json")
    if not km_extraction:
        return extract_metadata_fields(input_doc), "rules_partial"

    result = _call_llm(call_fab_agent, format_km_query(km_extraction, evidence))
    result["_extraction_method"] = "llm"
    return result, "llm"


def _run_router(
    evidence: dict,
    extraction_out: dict,
    km_dir: Path,
    call_fab_agent: Callable[[str], str],
    config: PipelineConfig,
    *,
    allow_rule_router: bool = True,
) -> tuple[dict, list[str], str]:
    # Rule router picks only 1-2 families — unsafe when family candidates are needed upstream
    if allow_rule_router and config.use_rule_router:
        try:
            router_out, confidence = route_families_by_rules(
                evidence,
                km_dir,
                min_score=config.rule_router_min_score,
                min_margin=config.rule_router_min_margin,
            )
            if router_out is not None:
                families = router_output_to_families(router_out)
                router_out["_routing_confidence"] = round(confidence, 3)
                return router_out, families, "rules"
        except Exception:
            pass  # Fall through to LLM router

    km_router = load_km(km_dir, "km_01a_specific_topic_family_router.json")
    if not km_router:
        return {}, list(STAGE_FAMILY_MAP.keys()), "none"

    try:
        router_out = _call_llm(
            call_fab_agent,
            format_km_query(km_router, evidence, {"extraction_output": extraction_out}),
        )
        router_out["_routing_method"] = "llm"
        families = normalize_routed_families(router_out)
        if not families:
            families = list(STAGE_FAMILY_MAP.keys())
        return router_out, families, "llm"
    except Exception:
        # Last resort: run all families
        return {}, list(STAGE_FAMILY_MAP.keys()), "fallback_all"


def _run_single_family(
    family_slug: str,
    evidence: dict,
    extraction_out: dict,
    router_out: dict,
    km_dir: Path,
    call_fab_agent: Callable[[str], str],
) -> dict:
    km_filename = STAGE_FAMILY_MAP.get(family_slug)
    if not km_filename:
        return {"family": family_slug, "error": "unknown family slug"}

    km_family = load_km(km_dir, km_filename)
    if not km_family:
        return {"family": family_slug, "error": f"missing family KM file: {km_filename}"}

    try:
        fam_out = _call_llm(
            call_fab_agent,
            format_km_query(km_family, evidence, {
                "extraction_output": extraction_out,
                "router_output": router_out,
            }),
        )
        return {"family": family_slug, "output": fam_out}
    except Exception as exc:
        return {"family": family_slug, "error": str(exc)}


def _run_families_parallel(
    routed_families: list[str],
    evidence: dict,
    extraction_out: dict,
    router_out: dict,
    km_dir: Path,
    call_fab_agent: Callable[[str], str],
    config: PipelineConfig,
) -> list[dict]:
    if not routed_families:
        return []

    workers = min(config.parallel_family_workers, len(routed_families))
    if workers <= 1:
        return [
            _run_single_family(slug, evidence, extraction_out, router_out, km_dir, call_fab_agent)
            for slug in routed_families
        ]

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _run_single_family,
                slug,
                evidence,
                extraction_out,
                router_out,
                km_dir,
                call_fab_agent,
            ): slug
            for slug in routed_families
        }
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                slug = futures.get(future, "unknown")
                results.append({"family": slug, "error": str(exc)})

    order = {slug: idx for idx, slug in enumerate(routed_families)}
    results.sort(key=lambda item: order.get(item.get("family", ""), 999))
    return results


def _run_esrs(
    reconciler_out: dict,
    sectors_out: dict,
    evidence: dict,
    km_dir: Path,
    call_fab_agent: Callable[[str], str],
    config: PipelineConfig,
) -> tuple[dict, str]:
    specific_topics = _extract_field(
        reconciler_out,
        ["final_specific_topics", "specific_topics", "SpecificTopic"]
    )

    if config.use_esrs_lookup and specific_topics:
        try:
            lookup_out = lookup_esrs_topics(specific_topics, km_dir)
            if lookup_out.get("final_closest_esrs_topics"):
                return lookup_out, "lookup"
        except Exception:
            pass

    km_esrs = load_km(km_dir, "km_03_esrs_mapping.json")
    if not km_esrs:
        if specific_topics:
            try:
                return lookup_esrs_topics(specific_topics, km_dir), "lookup_empty"
            except Exception:
                pass
        return {}, "empty"

    try:
        esrs_out = _call_llm(
            call_fab_agent,
            format_km_query(km_esrs, evidence, {
                "reconciler_output": reconciler_out,
                "sectors_output": sectors_out,
            }),
        )
        esrs_out["_esrs_method"] = "llm"
        return esrs_out, "llm"
    except Exception:
        if specific_topics:
            try:
                return lookup_esrs_topics(specific_topics, km_dir), "lookup_fallback"
            except Exception:
                pass
        return {}, "error"


def _merge_final(state: PipelineState) -> dict:
    final = {
        "SpecificTopic": _extract_field(
            state.reconciler_out,
            ["final_specific_topics", "specific_topics", "SpecificTopic"]
        ),
        "SpecificTopicFamily": format_router_families(state.router_out),
        "ClosestESRSTopics": _extract_field(
            state.esrs_out,
            ["final_closest_esrs_topics", "closest_esrs", "esrs_topics"]
        ),
        "ApplicableSectors": _extract_field(
            state.sectors_out,
            ["final_applicable_sectors", "applicable_sectors", "sectors"]
        ),
    }
    return validate_and_repair(final)


def _stage_enabled(selected_stages: list[str] | None, stage: str) -> bool:
    return selected_stages is None or stage in selected_stages


def _apply_cached_state(state: PipelineState, cached: dict[str, Any]) -> None:
    if cached.get("extraction_out"):
        state.extraction_out = cached["extraction_out"]
        state.methods["extraction"] = cached.get("methods", {}).get("extraction", "cache")
    if cached.get("router_out"):
        state.router_out = cached["router_out"]
        state.routed_families = list(
            cached.get("routed_families") or normalize_routed_families(state.router_out)
        )
        state.methods["router"] = cached.get("methods", {}).get("router", "cache")
    if cached.get("family_candidates"):
        state.family_candidates = list(cached["family_candidates"])
        state.methods["families"] = cached.get("methods", {}).get("families", "cache")
    if cached.get("reconciler_out"):
        state.reconciler_out = cached["reconciler_out"]
        state.methods["reconciler"] = cached.get("methods", {}).get("reconciler", "cache")
    if cached.get("sectors_out"):
        state.sectors_out = cached["sectors_out"]
        state.methods["sectors"] = cached.get("methods", {}).get("sectors", "cache")


def _persist_state(doc_id: str | None, state: PipelineState, config: PipelineConfig) -> None:
    if not doc_id or not config.use_pipeline_cache:
        return
    try:
        update_doc_context(
            doc_id,
            extraction_out=state.extraction_out,
            router_out=state.router_out,
            family_candidates=state.family_candidates,
            reconciler_out=state.reconciler_out,
            sectors_out=state.sectors_out,
            routed_families=state.routed_families,
            methods=state.methods,
        )
    except Exception:
        pass


def run_tagging_pipeline(
    input_doc: dict,
    km_dir: Path,
    call_fab_agent: Callable[[str], str],
    selected_stages: list[str] | None = None,
    config: PipelineConfig | None = None,
    doc_id: str | None = None,
    cache_target_stage: str | None = None,
) -> dict:
    """Run the hybrid tagging pipeline on a single input document."""
    cfg = config or load_pipeline_config()
    trace: dict[str, Any] = {}
    start = time.time()
    state = PipelineState()

    try:
        evidence = build_evidence_packet(input_doc, cfg)
    except Exception as exc:
        evidence = {"title": "", "body_text": "", "metadata": {}}
        trace["evidence_error"] = str(exc)
    trace["evidence_packet"] = evidence

    if cache_target_stage:
        cache_stage = cache_target_stage
    elif selected_stages and len(selected_stages) == 1:
        cache_stage = selected_stages[0]
    else:
        cache_stage = "km_03_esrs_mapping"

    try:
        cached = get_cached_upstream(doc_id or "", cache_stage, cfg.use_pipeline_cache)
        if cached:
            _apply_cached_state(state, cached)
    except Exception:
        pass

    if _stage_enabled(selected_stages, "km_04_orchestrator_extraction") and not state.extraction_out:
        try:
            state.extraction_out, method = _run_extraction(
                input_doc, evidence, km_dir, call_fab_agent, cfg
            )
            state.methods["extraction"] = method
            trace["extraction"] = state.extraction_out
        except Exception as exc:
            state.extraction_out = {}
            trace["extraction_error"] = str(exc)

    if _stage_enabled(selected_stages, "km_01a_specific_topic_family_router") and not state.router_out:
        try:
            state.router_out, state.routed_families, method = _run_router(
                evidence,
                state.extraction_out,
                km_dir,
                call_fab_agent,
                cfg,
                allow_rule_router=True,
            )
            state.methods["router"] = method
            trace["router"] = state.router_out
        except Exception as exc:
            state.router_out = {}
            state.routed_families = list(STAGE_FAMILY_MAP.keys())
            trace["router_error"] = str(exc)
    elif not state.routed_families:
        state.routed_families = normalize_routed_families(state.router_out) or list(STAGE_FAMILY_MAP.keys())

    if _stage_enabled(selected_stages, "family_st_kms") and not state.routed_families:
        state.routed_families = list(STAGE_FAMILY_MAP.keys())

    if _stage_enabled(selected_stages, "family_st_kms") and not state.family_candidates:
        families_to_run = state.routed_families
        try:
            state.family_candidates = _run_families_parallel(
                families_to_run,
                evidence,
                state.extraction_out,
                state.router_out,
                km_dir,
                call_fab_agent,
                cfg,
            )
            state.methods["families"] = "llm_parallel"
            trace["family_candidates"] = state.family_candidates
        except Exception as exc:
            state.family_candidates = []
            trace["families_error"] = str(exc)

    if _stage_enabled(selected_stages, "km_01z_specific_topic_reconciler") and not state.reconciler_out:
        km_reconciler = load_km(km_dir, "km_01z_specific_topic_reconciler.json")
        if km_reconciler:
            try:
                state.reconciler_out = _call_llm(
                    call_fab_agent,
                    format_km_query(km_reconciler, evidence, {
                        "extraction_output": state.extraction_out,
                        "router_output": state.router_out,
                        "family_candidates": state.family_candidates,
                    }),
                )
                state.methods["reconciler"] = "llm"
                trace["reconciler"] = state.reconciler_out
            except Exception as exc:
                state.reconciler_out = {}
                trace["reconciler_error"] = str(exc)

    if _stage_enabled(selected_stages, "km_02_applicable_sectors") and not state.sectors_out:
        km_sectors = load_km(km_dir, "km_02_applicable_sectors.json")
        if km_sectors:
            try:
                state.sectors_out = _call_llm(
                    call_fab_agent,
                    format_km_query(km_sectors, evidence, {
                        "extraction_output": state.extraction_out,
                        "reconciler_output": state.reconciler_out,
                    }),
                )
                state.methods["sectors"] = "llm"
                trace["sectors"] = state.sectors_out
            except Exception as exc:
                state.sectors_out = {}
                trace["sectors_error"] = str(exc)

    if _stage_enabled(selected_stages, "km_03_esrs_mapping") and not state.esrs_out:
        try:
            state.esrs_out, method = _run_esrs(
                state.reconciler_out,
                state.sectors_out,
                evidence,
                km_dir,
                call_fab_agent,
                cfg,
            )
            state.methods["esrs"] = method
            trace["esrs"] = state.esrs_out
        except Exception as exc:
            state.esrs_out = {}
            trace["esrs_error"] = str(exc)

    final = _merge_final(state)
    trace["methods"] = state.methods
    _persist_state(doc_id, state, cfg)

    return {
        "final": final,
        "trace": trace,
        "methods": state.methods,
        "elapsed_sec": round(time.time() - start, 2),
    }


def build_prerequisite_context(
    input_doc: dict,
    km_dir: Path,
    target_stage: str,
    call_fab_agent_fn: Callable[[str], str],
    config: PipelineConfig | None = None,
    doc_id: str | None = None,
) -> dict:
    """
    Run upstream pipeline stages for single-stage scoring.
    Uses hybrid shortcuts, cache, and parallel family calls.
    """
    cfg = config or load_pipeline_config()
    upstream = _upstream_stages_for(target_stage)

    if not upstream:
        return {}

    try:
        partial = run_tagging_pipeline(
            input_doc,
            km_dir,
            call_fab_agent_fn,
            selected_stages=upstream,
            config=cfg,
            doc_id=doc_id,
            cache_target_stage=target_stage,
        )
    except Exception:
        return {}

    trace = partial.get("trace", {})
    extra: dict[str, Any] = {}
    if trace.get("extraction"):
        extra["extraction_output"] = trace["extraction"]
    if trace.get("router"):
        extra["router_output"] = trace["router"]
    if trace.get("family_candidates"):
        extra["family_candidates"] = trace["family_candidates"]
    if trace.get("reconciler"):
        extra["reconciler_output"] = trace["reconciler"]
    if trace.get("sectors"):
        extra["sectors_output"] = trace["sectors"]
    extra["_upstream_methods"] = trace.get("methods", {})
    return extra


def _upstream_stages_for(target_stage: str) -> list[str]:
    ordered = [
        "km_04_orchestrator_extraction",
        "km_01a_specific_topic_family_router",
        "family_st_kms",
        "km_01z_specific_topic_reconciler",
        "km_02_applicable_sectors",
    ]
    stage_idx = {
        "km_04_orchestrator_extraction": 0,
        "km_01a_specific_topic_family_router": 1,
        "family_st_kms": 2,
        "km_01z_specific_topic_reconciler": 3,
        "km_02_applicable_sectors": 4,
        "km_03_esrs_mapping": 5,
    }
    idx = stage_idx.get(target_stage, 5)
    return ordered[:idx]


def _successful_family_candidates(candidates: list) -> list:
    return [c for c in candidates if c.get("output") and not c.get("error")]


def score_document_for_stage(
    input_doc: dict,
    km_dir: Path,
    call_fab_agent_fn: Callable[[str], str],
    target_stage: str,
    km_obj: dict,
    doc_id: str | None = None,
    config: PipelineConfig | None = None,
    gt_column: str | None = None,
) -> dict:
    """
    Score one document for a pipeline stage.
    Runs fresh upstream context (no cache) then the target stage LLM/rules.
    """
    try:
        cfg = config or load_pipeline_config()
        needs_families = "family_st_kms" in _upstream_stages_for(target_stage)
        scoring_cfg = replace(cfg, use_pipeline_cache=False)

        evidence = build_evidence_packet(input_doc, scoring_cfg)
        extra: dict[str, Any] = {}
        methods: dict[str, Any] = {}

        upstream = _upstream_stages_for(target_stage)
        if upstream:
            partial = run_tagging_pipeline(
                input_doc,
                km_dir,
                call_fab_agent_fn,
                selected_stages=upstream,
                config=scoring_cfg,
                doc_id=None,
            )
            trace = partial.get("trace", {})
            methods = dict(trace.get("methods") or {})
            if trace.get("extraction"):
                extra["extraction_output"] = trace["extraction"]
            if trace.get("router"):
                extra["router_output"] = trace["router"]
            if trace.get("family_candidates"):
                extra["family_candidates"] = list(trace["family_candidates"])

        ai_output, method, error = score_stage_output(
            target_stage,
            km_obj,
            evidence,
            extra,
            call_fab_agent_fn,
            km_dir,
            scoring_cfg,
            input_doc,
            gt_column=gt_column,
        )

        families_ok = len(_successful_family_candidates(extra.get("family_candidates", [])))

        return {
            "ai_output": ai_output,
            "method": method,
            "error": error,
            "upstream_methods": methods,
            "family_count": len(extra.get("family_candidates", [])),
            "families_ok": families_ok,
            "family_retry": False,
        }
    except Exception as exc:
        return {
            "ai_output": f"ERROR: {exc}",
            "method": "error",
            "error": str(exc),
            "upstream_methods": {},
            "family_count": 0,
            "families_ok": 0,
        }


def score_stage_output(
    target_stage: str,
    km_obj: dict,
    evidence: dict,
    extra_context: dict,
    call_fab_agent_fn: Callable[[str], str],
    km_dir: Path,
    config: PipelineConfig | None = None,
    input_doc: dict | None = None,
    gt_column: str | None = None,
) -> tuple[str, str, str]:
    """
    Produce AI output string for a scoring stage.
    Returns (ai_output, method, error_msg).
    """
    cfg = config or load_pipeline_config()

    # Rule-based extraction shortcut — return only the GT target field
    if target_stage == "km_04_orchestrator_extraction" and cfg.use_rule_extraction and input_doc:
        try:
            ruled = extract_metadata_fields(input_doc)
            if gt_column:
                scalar = _extract_scalar_field(ruled, gt_column)
                if scalar:
                    return scalar, "rules", ""
            if extraction_is_complete(ruled):
                field = gt_column or "ShortTitle"
                scalar = _extract_scalar_field(ruled, field)
                if scalar:
                    return scalar, "rules", ""
        except Exception:
            pass

    # ESRS lookup shortcut
    if target_stage == "km_03_esrs_mapping" and cfg.use_esrs_lookup:
        reconciler = extra_context.get("reconciler_output") or {}
        topics = _extract_field(reconciler, ["final_specific_topics", "specific_topics", "SpecificTopic"])
        if topics:
            try:
                lookup_out = lookup_esrs_topics(topics, km_dir)
                if lookup_out.get("final_closest_esrs_topics"):
                    labels = _extract_field(
                        lookup_out,
                        ["final_closest_esrs_topics", "closest_esrs", "esrs_topics"]
                    )
                    return labels, "lookup", ""
            except Exception:
                pass

    # LLM call
    try:
        query = format_km_query(km_obj, evidence, extra_context or None)
        raw = call_fab_agent_fn(query)
        raw_out = parse_json_response(raw)
        if target_stage == "km_04_orchestrator_extraction":
            field = gt_column or "ShortTitle"
            ai_output = _extract_scalar_field(raw_out, field)
            return ai_output, "llm", ""
        keys = EXTRACT_KEYS.get(target_stage, [])
        if keys:
            ai_output = _extract_field(raw_out, keys)
        else:
            ai_output = json.dumps(raw_out, ensure_ascii=False)
        return ai_output, "llm", ""
    except Exception as exc:
        return f"ERROR: {exc}", "error", str(exc)