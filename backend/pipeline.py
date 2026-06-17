# pipeline.py — TagForge hybrid multi-stage tagging pipeline
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

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
    "km_01z_specific_topic_reconciler": ["final_specific_topics", "specific_topics"],
    "km_02_applicable_sectors": ["applicable_sectors", "sectors"],
    "km_03_esrs_mapping": ["closest_esrs", "esrs_topics", "final_closest_esrs_topics"],
    "km_04_orchestrator_extraction": ["SpecificTopic"],
}


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
        return json.loads(p.read_text(encoding="utf-8"))
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
    cleaned = re.sub(r"```json|```", "", raw).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        cleaned = match.group()
    return json.loads(cleaned)


def _extract_field(obj: dict, keys: list[str]) -> str:
    for key in keys:
        value = obj.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            if value and isinstance(value[0], dict):
                return format_router_families(obj) if key == "topic_families_to_run" else json.dumps(value)
            return "; ".join(str(item) for item in value)
        return str(value)
    return ""


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
) -> tuple[dict, list[str], str]:
    if config.use_rule_router:
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

    km_router = load_km(km_dir, "km_01a_specific_topic_family_router.json")
    if not km_router:
        return {}, list(STAGE_FAMILY_MAP.keys()), "none"

    router_out = _call_llm(
        call_fab_agent,
        format_km_query(km_router, evidence, {"extraction_output": extraction_out}),
    )
    router_out["_routing_method"] = "llm"
    families = normalize_routed_families(router_out)
    if not families:
        families = list(STAGE_FAMILY_MAP.keys())
    return router_out, families, "llm"


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
        return {"family": family_slug, "error": "missing family KM"}

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
            results.append(future.result())

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
    specific_topics = _extract_field(reconciler_out, ["final_specific_topics", "specific_topics"])

    if config.use_esrs_lookup and specific_topics:
        lookup_out = lookup_esrs_topics(specific_topics, km_dir)
        if lookup_out.get("final_closest_esrs_topics"):
            return lookup_out, "lookup"

    km_esrs = load_km(km_dir, "km_03_esrs_mapping.json")
    if not km_esrs:
        return lookup_esrs_topics(specific_topics, km_dir) if specific_topics else {}, "lookup_empty"

    esrs_out = _call_llm(
        call_fab_agent,
        format_km_query(km_esrs, evidence, {
            "reconciler_output": reconciler_out,
            "sectors_output": sectors_out,
        }),
    )
    esrs_out["_esrs_method"] = "llm"
    return esrs_out, "llm"


def _merge_final(state: PipelineState) -> dict:
    final = {
        "SpecificTopic": _extract_field(state.reconciler_out, ["final_specific_topics", "specific_topics"]),
        "SpecificTopicFamily": format_router_families(state.router_out),
        "ClosestESRSTopics": _extract_field(state.esrs_out, ["final_closest_esrs_topics", "closest_esrs", "esrs_topics"]),
        "ApplicableSectors": _extract_field(state.sectors_out, ["applicable_sectors", "sectors"]),
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
        state.routed_families = list(cached.get("routed_families") or normalize_routed_families(state.router_out))
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

    evidence = build_evidence_packet(input_doc, cfg)
    trace["evidence_packet"] = evidence

    if cache_target_stage:
        cache_stage = cache_target_stage
    elif selected_stages and len(selected_stages) == 1:
        cache_stage = selected_stages[0]
    else:
        cache_stage = "km_03_esrs_mapping"

    cached = get_cached_upstream(doc_id or "", cache_stage, cfg.use_pipeline_cache)
    if cached:
        _apply_cached_state(state, cached)

    if _stage_enabled(selected_stages, "km_04_orchestrator_extraction") and not state.extraction_out:
        state.extraction_out, method = _run_extraction(input_doc, evidence, km_dir, call_fab_agent, cfg)
        state.methods["extraction"] = method
        trace["extraction"] = state.extraction_out

    if _stage_enabled(selected_stages, "km_01a_specific_topic_family_router") and not state.router_out:
        state.router_out, state.routed_families, method = _run_router(
            evidence, state.extraction_out, km_dir, call_fab_agent, cfg
        )
        state.methods["router"] = method
        trace["router"] = state.router_out
    elif not state.routed_families:
        state.routed_families = normalize_routed_families(state.router_out) or list(STAGE_FAMILY_MAP.keys())

    if _stage_enabled(selected_stages, "family_st_kms") and not state.family_candidates:
        state.family_candidates = _run_families_parallel(
            state.routed_families,
            evidence,
            state.extraction_out,
            state.router_out,
            km_dir,
            call_fab_agent,
            cfg,
        )
        state.methods["families"] = "llm_parallel"
        trace["family_candidates"] = state.family_candidates

    if _stage_enabled(selected_stages, "km_01z_specific_topic_reconciler") and not state.reconciler_out:
        km_reconciler = load_km(km_dir, "km_01z_specific_topic_reconciler.json")
        if km_reconciler:
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

    if _stage_enabled(selected_stages, "km_02_applicable_sectors") and not state.sectors_out:
        km_sectors = load_km(km_dir, "km_02_applicable_sectors.json")
        if km_sectors:
            state.sectors_out = _call_llm(
                call_fab_agent,
                format_km_query(km_sectors, evidence, {
                    "extraction_output": state.extraction_out,
                    "reconciler_output": state.reconciler_out,
                }),
            )
            state.methods["sectors"] = "llm"
            trace["sectors"] = state.sectors_out

    if _stage_enabled(selected_stages, "km_03_esrs_mapping") and not state.esrs_out:
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
    partial = run_tagging_pipeline(
        input_doc,
        km_dir,
        call_fab_agent_fn,
        selected_stages=_upstream_stages_for(target_stage),
        config=cfg,
        doc_id=doc_id,
        cache_target_stage=target_stage,
    )
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


def score_stage_output(
    target_stage: str,
    km_obj: dict,
    evidence: dict,
    extra_context: dict,
    call_fab_agent_fn: Callable[[str], str],
    km_dir: Path,
    config: PipelineConfig | None = None,
    input_doc: dict | None = None,
) -> tuple[str, str, str]:
    """
    Produce AI output string for a scoring stage.
    Returns (ai_output, method, error_msg).
    """
    cfg = config or load_pipeline_config()

    if target_stage == "km_04_orchestrator_extraction" and cfg.use_rule_extraction and input_doc:
        ruled = extract_metadata_fields(input_doc)
        if extraction_is_complete(ruled):
            return json.dumps(ruled), "rules", ""

    if target_stage == "km_03_esrs_mapping" and cfg.use_esrs_lookup:
        reconciler = extra_context.get("reconciler_output") or {}
        topics = _extract_field(reconciler, ["final_specific_topics", "specific_topics"])
        if topics:
            lookup_out = lookup_esrs_topics(topics, km_dir)
            if lookup_out.get("final_closest_esrs_topics"):
                labels = _extract_field(lookup_out, ["final_closest_esrs_topics", "closest_esrs", "esrs_topics"])
                return labels, "lookup", ""

    try:
        raw = call_fab_agent_fn(format_km_query(km_obj, evidence, extra_context or None))
        raw_out = parse_json_response(raw)
        keys = EXTRACT_KEYS.get(target_stage, [])
        ai_output = _extract_field(raw_out, keys) if keys else json.dumps(raw_out)
        return ai_output, "llm", ""
    except Exception as exc:
        return f"ERROR: {exc}", "error", str(exc)
