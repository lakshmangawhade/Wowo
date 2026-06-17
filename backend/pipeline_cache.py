# pipeline_cache.py — cache upstream pipeline results per document
from __future__ import annotations

import threading
from typing import Any

from family_registry import is_upstream_stage

_lock = threading.Lock()
_cache: dict[str, dict[str, Any]] = {}


def _empty_context() -> dict[str, Any]:
    return {
        "extraction_out": {},
        "router_out": {},
        "family_candidates": [],
        "reconciler_out": {},
        "sectors_out": {},
        "routed_families": [],
        "methods": {},
    }


def get_doc_context(doc_id: str) -> dict[str, Any]:
    with _lock:
        cached = _cache.get(doc_id)
        if cached is None:
            return _empty_context()
        return {
            "extraction_out": dict(cached.get("extraction_out") or {}),
            "router_out": dict(cached.get("router_out") or {}),
            "family_candidates": list(cached.get("family_candidates") or []),
            "reconciler_out": dict(cached.get("reconciler_out") or {}),
            "sectors_out": dict(cached.get("sectors_out") or {}),
            "routed_families": list(cached.get("routed_families") or []),
            "methods": dict(cached.get("methods") or {}),
        }


def update_doc_context(doc_id: str, **kwargs: Any) -> None:
    with _lock:
        ctx = _cache.setdefault(doc_id, _empty_context())
        for key, value in kwargs.items():
            ctx[key] = value


def get_cached_upstream(doc_id: str, target_stage: str, enabled: bool) -> dict[str, Any] | None:
    if not enabled or not doc_id:
        return None

    with _lock:
        cached = _cache.get(doc_id)
        if not cached:
            return None

    result = _empty_context()
    found = False

    if is_upstream_stage("km_04_orchestrator_extraction", target_stage) and cached.get("extraction_out"):
        result["extraction_out"] = cached["extraction_out"]
        result["methods"]["extraction"] = cached.get("methods", {}).get("extraction")
        found = True

    if is_upstream_stage("km_01a_specific_topic_family_router", target_stage) and cached.get("router_out"):
        result["router_out"] = cached["router_out"]
        result["routed_families"] = list(cached.get("routed_families") or [])
        result["methods"]["router"] = cached.get("methods", {}).get("router")
        found = True

    if is_upstream_stage("family_st_kms", target_stage) and cached.get("family_candidates"):
        result["family_candidates"] = list(cached["family_candidates"])
        result["methods"]["families"] = cached.get("methods", {}).get("families")
        found = True

    if is_upstream_stage("km_01z_specific_topic_reconciler", target_stage) and cached.get("reconciler_out"):
        result["reconciler_out"] = cached["reconciler_out"]
        result["methods"]["reconciler"] = cached.get("methods", {}).get("reconciler")
        found = True

    if is_upstream_stage("km_02_applicable_sectors", target_stage) and cached.get("sectors_out"):
        result["sectors_out"] = cached["sectors_out"]
        result["methods"]["sectors"] = cached.get("methods", {}).get("sectors")
        found = True

    return result if found else None


def clear_pipeline_cache() -> None:
    with _lock:
        _cache.clear()
