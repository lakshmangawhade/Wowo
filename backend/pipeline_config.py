# pipeline_config.py — hybrid pipeline feature flags
from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class PipelineConfig:
    use_rule_extraction: bool = True
    use_rule_router: bool = True
    use_esrs_lookup: bool = True
    use_evidence_windows: bool = True
    use_pipeline_cache: bool = True
    rule_router_min_score: float = 2.0
    rule_router_min_margin: float = 1.0
    parallel_family_workers: int = 4
    max_body_chars: int = 8000
    max_evidence_window_chars: int = 1200


def load_pipeline_config() -> PipelineConfig:
    return PipelineConfig(
        use_rule_extraction=_env_bool("USE_RULE_EXTRACTION", True),
        use_rule_router=_env_bool("USE_RULE_ROUTER", True),
        use_esrs_lookup=_env_bool("USE_ESRS_LOOKUP", True),
        use_evidence_windows=_env_bool("USE_EVIDENCE_WINDOWS", True),
        use_pipeline_cache=_env_bool("USE_PIPELINE_CACHE", True),
        rule_router_min_score=_env_float("RULE_ROUTER_MIN_SCORE", 2.0),
        rule_router_min_margin=_env_float("RULE_ROUTER_MIN_MARGIN", 1.0),
        parallel_family_workers=_env_int("PARALLEL_FAMILY_WORKERS", 4),
        max_body_chars=_env_int("MAX_BODY_CHARS", 8000),
        max_evidence_window_chars=_env_int("MAX_EVIDENCE_WINDOW_CHARS", 1200),
    )