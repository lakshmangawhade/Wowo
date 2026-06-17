# security.py — shared security helpers for TagForge
from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import Header, HTTPException

# Upload size limits (bytes)
MAX_DOC_BYTES = 10 * 1024 * 1024
MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_EVAL_BYTES = 256 * 1024
MAX_KM_BYTES = 2 * 1024 * 1024

SAFE_FILENAME = re.compile(r"^[a-zA-Z0-9._-]+$")

BLOCKED_EVAL_PATTERNS = (
    r"\bos\.system\b",
    r"\bsubprocess\b",
    r"\b__import__\b",
    r"\bexec\s*\(",
    r"\beval\s*\(",
    r"\bcompile\s*\(",
    r"\bshutil\.rmtree\b",
    r"\bos\.remove\b",
    r"\bos\.unlink\b",
    r"\bsocket\b",
    r"\brequests\b",
    r"\bhttpx\b",
    r"\burllib\b",
)

TAGFORGE_API_KEY = os.getenv("TAGFORGE_API_KEY", "").strip()


def safe_filename(name: str | None, *, allowed_suffix: str | None = None) -> str:
    """Return a basename-only filename; reject traversal and unsafe characters."""
    if not name or name in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid filename")

    base = Path(name).name
    if base != name or ".." in name or "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="Invalid filename")

    if not SAFE_FILENAME.match(base):
        raise HTTPException(status_code=400, detail="Filename contains invalid characters")

    if allowed_suffix and not base.endswith(allowed_suffix):
        raise HTTPException(
            status_code=400,
            detail=f"Filename must end with {allowed_suffix}",
        )

    return base


def safe_path(base_dir: Path, filename: str) -> Path:
    """Resolve filename under base_dir; reject path traversal."""
    safe_name = safe_filename(filename)
    base_resolved = base_dir.resolve()
    target = (base_resolved / safe_name).resolve()
    if not target.is_relative_to(base_resolved):
        raise HTTPException(status_code=400, detail="Invalid path")
    return target


def enforce_max_bytes(content: bytes, limit: int, label: str) -> None:
    if len(content) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"{label} exceeds maximum size of {limit // (1024 * 1024)} MB",
        )


def validate_eval_script_content(text: str) -> None:
    if "def evaluate(" not in text:
        raise HTTPException(status_code=400, detail="Eval script must define evaluate()")

    for pattern in BLOCKED_EVAL_PATTERNS:
        if re.search(pattern, text):
            raise HTTPException(
                status_code=400,
                detail="Eval script contains disallowed operations",
            )


async def require_api_key(x_tagforge_key: str = Header(default="", alias="X-TagForge-Key")) -> None:
    """Optional API key gate. Disabled when TAGFORGE_API_KEY is unset."""
    if not TAGFORGE_API_KEY:
        return
    if x_tagforge_key != TAGFORGE_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


def parse_cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "").strip()
    if not raw:
        return ["http://localhost:8000", "http://127.0.0.1:8000"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]
