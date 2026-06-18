# server.py — TagForge API
import io
import os
import sys
import json
import csv
import random
import importlib.util
import time
import re
import logging
from pathlib import Path
from typing import Optional

import requests as http_requests
import threading

_versions_lock = threading.Lock()
_eval_module_cache = None
_eval_module_lock = threading.Lock()
log = logging.getLogger("tagforge")

from fastapi import APIRouter, Depends, FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator
from dotenv import load_dotenv

# Ensure backend modules resolve whether started as `server:app` or `backend.server:app`
_BACKEND_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _BACKEND_DIR.parent
for _path in (str(_BACKEND_DIR), str(_ROOT_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from pipeline import (
    score_document_for_stage,
    run_tagging_pipeline,
)
from pipeline_cache import clear_pipeline_cache
from pipeline_config import load_pipeline_config
from security import (
    MAX_CSV_BYTES,
    MAX_DOC_BYTES,
    MAX_EVAL_BYTES,
    MAX_KM_BYTES,
    enforce_max_bytes,
    parse_cors_origins,
    require_api_key,
    safe_filename,
    safe_path,
    validate_eval_script_content,
)

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

# ── FAB agent config ──────────────────────────────────────────────────────────
FAB_AGENT_URL         = os.getenv("FAB_AGENT_URL", "")
FAB_IMPROVE_AGENT_URL = os.getenv("FAB_IMPROVE_AGENT_URL", "")
FAB_USER_ID           = os.getenv("FAB_USER_ID", "")
FAB_WORKSPACE         = os.getenv("FAB_WORKSPACE_ID", "")
FAB_API_KEY           = os.getenv("FAB_API", "")

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT         = Path(__file__).parent.parent
PRODUCTS_DIR = ROOT / "products"
EVAL_DIR     = ROOT / "eval_code"
FRONTEND     = ROOT / "frontend"
VERSIONS_F   = ROOT / "versions.json"

TAGGING_DIR  = PRODUCTS_DIR / "tagging"
INPUT_DIR    = TAGGING_DIR / "input"
GT_CSV_DIR   = TAGGING_DIR / "gt_csv"
KM_DIR       = TAGGING_DIR / "km"

for d in [INPUT_DIR, GT_CSV_DIR, KM_DIR, EVAL_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── Ground-truth CSV loader ───────────────────────────────────────────────────
_gt_cache: dict | None = None
_gt_lock = threading.Lock()

GT_COLUMNS = ["SpecificTopic", "SpecificTopicFamily", "ClosestESRSTopics", "ApplicableSectors"]

def load_gt_csv() -> dict:
    """Returns {doc_id: {col: value}} for all GT rows."""
    global _gt_cache
    with _gt_lock:
        if _gt_cache is not None:
            return dict(_gt_cache)
        gt_files = list(GT_CSV_DIR.glob("*.csv"))
        if not gt_files:
            return {}
        result = {}
        with open(gt_files[0], newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                doc_id = (row.get("input_doc_id") or row.get("input_file", "")).strip()
                if doc_id.endswith(".json"):
                    doc_id = doc_id[:-5]
                if doc_id:
                    result[doc_id] = row
        _gt_cache = result
        return dict(_gt_cache)


def get_gt_for_doc(doc_id: str) -> dict:
    gt = load_gt_csv()
    # try exact, then strip extension
    row = gt.get(doc_id) or gt.get(doc_id.replace(".json", ""))
    if row is None:
        return {}
    return {col: row.get(col, "") for col in GT_COLUMNS}


# ── FAB agent calls ───────────────────────────────────────────────────────────
def _ensure_fab_config() -> None:
    missing = [
        name for name, val in [
            ("FAB_AGENT_URL", FAB_AGENT_URL),
            ("FAB_USER_ID", FAB_USER_ID),
            ("FAB_API", FAB_API_KEY),
        ] if not val
    ]
    if missing:
        raise HTTPException(
            status_code=503,
            detail=f"FAB agent not configured. Missing: {', '.join(missing)}",
        )


def call_fab_agent(user_message: str) -> str:
    _ensure_fab_config()
    headers = {
        "content-type":     "application/json",
        "x-user-id":        FAB_USER_ID,
        "x-authentication": f"api-key {FAB_API_KEY}",
    }
    payload = {"input": {"query": user_message}}
    for attempt in range(4):
        resp = http_requests.post(FAB_AGENT_URL, json=payload, headers=headers, timeout=180)
        if resp.status_code == 429:
            wait = 15 * (attempt + 1)
            log.warning("FAB rate limited — retrying in %ss", wait)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return _extract_fab_content(resp.json())
    raise Exception("FAB agent rate limit exceeded after retries")


def call_fab_improve_agent(user_message: str) -> str:
    _ensure_fab_config()
    url = FAB_IMPROVE_AGENT_URL or FAB_AGENT_URL
    headers = {
        "content-type":     "application/json",
        "x-user-id":        FAB_USER_ID,
        "x-authentication": f"api-key {FAB_API_KEY}",
    }
    payload = {
        "input": {"query": user_message},
        "templateVariables": {
            "COMPLETION_CONFIG": {"max_tokens": 16000, "temperature": 0.7, "top_p": 0.95}
        },
    }
    for attempt in range(4):
        resp = http_requests.post(url, json=payload, headers=headers, timeout=180)
        if resp.status_code == 429:
            wait = 15 * (attempt + 1)
            log.warning("FAB improve agent rate limited - retrying in %ss", wait)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return _extract_fab_content(resp.json())
    raise Exception("FAB improve agent rate limit exceeded after retries")


def _extract_fab_content(data: dict) -> str:
    """Extract text content from FAB agent JSON response."""
    output = data.get("output")
    if isinstance(output, dict):
        text = output.get("content") or output.get("text") or output.get("message")
        if text:
            return str(text)
    if isinstance(output, str):
        return output
    for key in ("content", "text", "message", "result"):
        if data.get(key):
            return str(data[key])
    raise ValueError(f"FAB response missing content: {list(data.keys())}")


# ── Eval script helpers ───────────────────────────────────────────────────────
def _invalidate_eval_cache() -> None:
    global _eval_module_cache
    with _eval_module_lock:
        _eval_module_cache = None


def load_eval_module(*, force_reload: bool = False):
    global _eval_module_cache
    with _eval_module_lock:
        if _eval_module_cache is not None and not force_reload:
            return _eval_module_cache

        scripts = sorted(EVAL_DIR.glob("*.py"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not scripts:
            raise HTTPException(status_code=400, detail="No eval script uploaded")

        path = scripts[0]
        source = path.read_text(encoding="utf-8", errors="replace")
        validate_eval_script_content(source)

        spec = importlib.util.spec_from_file_location("eval_mod", str(path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if not hasattr(mod, "evaluate"):
            raise HTTPException(status_code=400, detail="Eval script has no evaluate() function")

        _eval_module_cache = mod
        return mod


def load_eval_fn():
    return load_eval_module().evaluate


def detect_metric(text: str) -> str:
    low = text.lower()
    if "f1"         in low:  return "F1 Score"
    if "precision"  in low:  return "Precision/Recall/F1"
    if "exact"      in low:  return "Exact Match"
    if "rouge"      in low:  return "ROUGE Score"
    return "Custom Metric"


# ── KM helpers ────────────────────────────────────────────────────────────────
def load_km(filename: str) -> dict:
    p = safe_path(KM_DIR, filename)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def backup_km_file(km_path: Path) -> None:
    if not km_path.exists():
        return
    backup_dir = KM_DIR / ".backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{km_path.stem}_{stamp}{km_path.suffix}"
    backup_path.write_bytes(km_path.read_bytes())


def list_km_files() -> list[str]:
    return sorted(f.name for f in KM_DIR.glob("*.json"))


# ── Versions ──────────────────────────────────────────────────────────────────
def _load_versions() -> list:
    with _versions_lock:
        if VERSIONS_F.exists():
            try:
                return json.loads(VERSIONS_F.read_text())
            except Exception:
                return []
        return []


def _save_versions(versions: list):
    with _versions_lock:
        VERSIONS_F.write_text(json.dumps(versions, indent=2))


# ── Document pair helpers ─────────────────────────────────────────────────────
def list_input_docs() -> list[str]:
    return sorted(f.name for f in INPUT_DIR.glob("*.json") if not f.name.startswith("."))


def list_gt_doc_ids() -> list[str]:
    return sorted(load_gt_csv().keys())


def read_input_doc(filename: str) -> dict:
    p = safe_path(INPUT_DIR, safe_filename(filename, allowed_suffix=".json"))
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(title="TagForge API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=parse_cors_origins(),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-TagForge-Key"],
)
app.mount("/static", StaticFiles(directory=str(FRONTEND / "static")), name="static")

public_api = APIRouter(prefix="/api")
protected_api = APIRouter(prefix="/api", dependencies=[Depends(require_api_key)])


@app.get("/")
def index():
    return FileResponse(str(FRONTEND / "index.html"))


@public_api.get("/health")
def health():
    fab_ok = bool(FAB_AGENT_URL and FAB_USER_ID and FAB_API_KEY)
    cfg = load_pipeline_config()
    return {
        "status": "ok",
        "version": "1.0.0",
        "product": "tagforge",
        "fab_configured": fab_ok,
        "auth_required": bool(os.getenv("TAGFORGE_API_KEY", "").strip()),
        "pipeline": {
            "use_rule_extraction": cfg.use_rule_extraction,
            "use_rule_router": cfg.use_rule_router,
            "use_esrs_lookup": cfg.use_esrs_lookup,
            "use_evidence_windows": cfg.use_evidence_windows,
            "use_pipeline_cache": cfg.use_pipeline_cache,
            "parallel_family_workers": cfg.parallel_family_workers,
        },
    }


@public_api.get("/pipeline-config")
def pipeline_config():
    cfg = load_pipeline_config()
    return {
        "use_rule_extraction": cfg.use_rule_extraction,
        "use_rule_router": cfg.use_rule_router,
        "use_esrs_lookup": cfg.use_esrs_lookup,
        "use_evidence_windows": cfg.use_evidence_windows,
        "use_pipeline_cache": cfg.use_pipeline_cache,
        "rule_router_min_score": cfg.rule_router_min_score,
        "rule_router_min_margin": cfg.rule_router_min_margin,
        "parallel_family_workers": cfg.parallel_family_workers,
        "max_body_chars": cfg.max_body_chars,
        "max_evidence_window_chars": cfg.max_evidence_window_chars,
    }


# ── Upload eval script ────────────────────────────────────────────────────────
@protected_api.post("/upload-eval-script")
async def upload_eval_script(file: UploadFile = File(...)):
    name = safe_filename(file.filename, allowed_suffix=".py")
    content = await file.read()
    enforce_max_bytes(content, MAX_EVAL_BYTES, "Eval script")
    text = content.decode("utf-8", errors="replace")
    validate_eval_script_content(text)
    dest = EVAL_DIR / name
    dest.write_bytes(content)
    _invalidate_eval_cache()
    return {
        "filename":     name,
        "size_bytes":   len(content),
        "preview":      text[:800] + ("…" if len(text) > 800 else ""),
        "has_evaluate": True,
        "metric":       detect_metric(text),
    }


@protected_api.get("/eval-script")
def get_eval_script():
    scripts = list(EVAL_DIR.glob("*.py"))
    if not scripts:
        raise HTTPException(status_code=404, detail="No eval script uploaded yet")
    f = sorted(scripts, key=lambda x: x.stat().st_mtime, reverse=True)[0]
    return {"filename": f.name, "preview": f.read_text(errors="replace")[:800]}


@protected_api.post("/use-demo-script")
def use_demo_script():
    demo_path = ROOT / "eval_code" / "eval_tagging.py"
    text = demo_path.read_text(encoding="utf-8") if demo_path.exists() else _DEMO_EVAL
    dest = EVAL_DIR / "eval_tagging.py"
    dest.write_text(text)
    _invalidate_eval_cache()
    return {
        "filename": "eval_tagging.py",
        "preview": text[:800],
        "has_evaluate": True,
        "metric": "F1 Score",
    }


_DEMO_EVAL = '''def evaluate(ai_output, gt_output):
    """Semicolon-split label F1 for tagging evaluation."""
    import re
    def norm(t):
        parts = re.split(r"[;,]", t or "")
        return {p.strip().lower() for p in parts if p.strip()}
    pred = norm(ai_output); gold = norm(gt_output)
    if not gold: return 100.0 if not pred else 0.0
    if not pred: return 0.0
    tp = len(pred & gold)
    if not tp: return 0.0
    p = tp / len(pred); r = tp / len(gold)
    return round(2*p*r/(p+r)*100, 2)
'''


# ── Document listing & upload ─────────────────────────────────────────────────
@protected_api.get("/docs")
def list_docs():
    input_docs = list_input_docs()
    gt_ids     = list_gt_doc_ids()
    return {
        "input_docs": input_docs,
        "gt_doc_ids": gt_ids,
        "total_input": len(input_docs),
        "total_gt":    len(gt_ids),
        "pairs":       min(len(input_docs), len(gt_ids)),
    }


@protected_api.post("/upload-doc")
async def upload_doc(file: UploadFile = File(...)):
    """Upload a JSON input document."""
    name = safe_filename(file.filename, allowed_suffix=".json")
    content = await file.read()
    enforce_max_bytes(content, MAX_DOC_BYTES, "Document")
    try:
        json.loads(content.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc
    dest = INPUT_DIR / name
    dest.write_bytes(content)
    return {"filename": name, "size_bytes": len(content)}


@protected_api.post("/upload-gt-csv")
async def upload_gt_csv(file: UploadFile = File(...)):
    """Upload / replace the ground-truth CSV."""
    global _gt_cache
    name = safe_filename(file.filename, allowed_suffix=".csv")
    content = await file.read()
    enforce_max_bytes(content, MAX_CSV_BYTES, "Ground-truth CSV")
    text = content.decode("utf-8", errors="replace")
    try:
        row_count = sum(1 for _ in csv.DictReader(io.StringIO(text)))
    except csv.Error as exc:
        raise HTTPException(status_code=400, detail=f"Invalid CSV: {exc}") from exc
    for old in GT_CSV_DIR.glob("*.csv"):
        old.unlink()
    dest = GT_CSV_DIR / name
    dest.write_bytes(content)
    with _gt_lock:
        _gt_cache = None
    return {"filename": name, "row_count": row_count}


# ── KM management ─────────────────────────────────────────────────────────────
@protected_api.get("/km-list")
def km_list():
    return {"km_files": list_km_files()}


@protected_api.get("/km/{filename}")
def get_km(filename: str):
    km = load_km(filename)
    if not km:
        raise HTTPException(status_code=404, detail=f"KM file not found: {filename}")
    return km


@protected_api.post("/km/{filename}")
async def save_km(filename: str, file: UploadFile = File(...)):
    safe_name = safe_filename(filename, allowed_suffix=".json")
    content = await file.read()
    enforce_max_bytes(content, MAX_KM_BYTES, "Knowledge model")
    try:
        json.loads(content.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid KM JSON: {exc}") from exc
    dest = safe_path(KM_DIR, safe_name)
    dest.write_bytes(content)
    return {"saved": safe_name}


# ── KM stage selection ────────────────────────────────────────────────────────
IMPROVABLE_STAGES = {
    "km_01a_specific_topic_family_router":  "km_01a_specific_topic_family_router.json",
    "km_01z_specific_topic_reconciler":     "km_01z_specific_topic_reconciler.json",
    "km_02_applicable_sectors":             "km_02_applicable_sectors.json",
    "km_03_esrs_mapping":                   "km_03_esrs_mapping.json",
    "km_04_orchestrator_extraction":        "km_04_orchestrator_extraction.json",
}

GT_COLUMN_FOR_STAGE = {
    "km_01a_specific_topic_family_router": "SpecificTopicFamily",
    "km_01z_specific_topic_reconciler":    "SpecificTopic",
    "km_02_applicable_sectors":            "ApplicableSectors",
    "km_03_esrs_mapping":                  "ClosestESRSTopics",
}


# ── Data split ────────────────────────────────────────────────────────────────
class SplitRequest(BaseModel):
    seed: Optional[int] = 42
    unseen_pct: float = Field(default=0.50, ge=0.0, le=1.0)
    learn_pct:  float = Field(default=0.20, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_percentages(self):
        if self.unseen_pct + self.learn_pct > 1.0:
            raise ValueError("unseen_pct + learn_pct must not exceed 1.0")
        return self


@protected_api.post("/split")
def split_data(req: SplitRequest):
    input_docs = list_input_docs()
    gt_ids     = list_gt_doc_ids()

    # match input docs to GT by doc_id
    pairs = []
    for fname in input_docs:
        doc_id = fname.replace(".json", "")
        gt     = get_gt_for_doc(doc_id)
        if gt:
            pairs.append({"filename": fname, "doc_id": doc_id, "gt": gt})

    n = len(pairs)
    if n == 0:
        # no matched pairs — use all input docs without GT (for pipeline testing)
        for fname in input_docs:
            pairs.append({"filename": fname, "doc_id": fname.replace(".json",""), "gt": {}})
        n = len(pairs)

    if n == 0:
        raise HTTPException(status_code=400, detail="No documents found in input folder")

    rng = random.Random(req.seed)
    rng.shuffle(pairs)

    n_unseen = round(n * req.unseen_pct)
    n_learn  = round(n * req.learn_pct)
    n_val    = max(0, n - n_unseen - n_learn)

    for i, p in enumerate(pairs):
        if   i < n_unseen:             p["set"] = "unseen"
        elif i < n_unseen + n_learn:   p["set"] = "learn"
        else:                          p["set"] = "val"

    return {
        "total": n, "unseen": n_unseen, "learn": n_learn, "val": n_val,
        "pairs": pairs,
    }


@protected_api.get("/stages")
def list_stages():
    return {"stages": list(IMPROVABLE_STAGES.keys())}


# ── Score batch (single-stage) ────────────────────────────────────────────────
class RunPipelineRequest(BaseModel):
    filename: str
    doc_id:   str = ""


@protected_api.post("/run-pipeline")
def run_pipeline(req: RunPipelineRequest):
    """Run the full hybrid pipeline on one document."""
    safe_name = safe_filename(req.filename, allowed_suffix=".json")
    input_doc = read_input_doc(safe_name)
    if not input_doc:
        raise HTTPException(status_code=404, detail=f"Document not found: {safe_name}")
    doc_id = req.doc_id or safe_name.replace(".json", "")
    try:
        return run_tagging_pipeline(input_doc, KM_DIR, call_fab_agent, doc_id=doc_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {exc}") from exc


@protected_api.post("/clear-pipeline-cache")
def clear_cache_endpoint():
    clear_pipeline_cache()
    return {"cleared": True}


class ScoreBatchRequest(BaseModel):
    pairs:     list = Field(default_factory=list)
    km_stage:  str  = "km_01z_specific_topic_reconciler"
    km_json:   str  = ""
    gt_column: str  = ""

    @field_validator("km_stage")
    @classmethod
    def validate_km_stage(cls, value: str) -> str:
        if value not in IMPROVABLE_STAGES:
            raise ValueError(f"Unknown km_stage: {value}")
        return value


class ImproveKMRequest(BaseModel):
    current_km:   str
    km_stage:     str   = "km_01z_specific_topic_reconciler"
    loop_num:     int   = Field(default=1, ge=1)
    learn_score:  float = 0.0
    target_score: float = 80.0
    n_learn_docs: int   = Field(default=0, ge=0)
    failures:     list  = Field(default_factory=list)
    all_results:  list  = Field(default_factory=list)
    gt_column:    str   = "SpecificTopic"

    @field_validator("km_stage")
    @classmethod
    def validate_km_stage(cls, value: str) -> str:
        if value not in IMPROVABLE_STAGES:
            raise ValueError(f"Unknown km_stage: {value}")
        return value


class SaveVersionRequest(BaseModel):
    label:       str = ""
    km_json:     str = ""
    km_stage:    str = ""
    val_score:   Optional[float] = None
    precision:   Optional[float] = None
    recall:      Optional[float] = None
    final_score: Optional[float] = None
    run_id:      str = ""
    loop_num:    int = 0
    run_status:  str = "running"


class MarkRunStatusRequest(BaseModel):
    run_id: str = ""
    status: str = "completed"


@protected_api.post("/score-batch")
def score_batch(req: ScoreBatchRequest):
    if not req.pairs:
        raise HTTPException(status_code=400, detail="No document pairs provided")

    eval_mod = load_eval_module()
    evaluate = eval_mod.evaluate
    evaluate_detailed = getattr(eval_mod, "evaluate_detailed", None)

    km_filename = IMPROVABLE_STAGES[req.km_stage]
    if req.km_json.strip():
        try:
            km_obj = json.loads(req.km_json)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid km_json: {exc}") from exc
    else:
        km_obj = load_km(km_filename)

    if not km_obj:
        raise HTTPException(status_code=400, detail=f"Knowledge model not found for stage: {req.km_stage}")

    gt_col = req.gt_column or GT_COLUMN_FOR_STAGE.get(req.km_stage, "SpecificTopic")
    pipeline_cfg = load_pipeline_config()

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def process_pair(p):
        doc_id = p.get("doc_id", "")
        filename = p.get("filename", "")
        gt_vals = p.get("gt") or get_gt_for_doc(doc_id)
        gt_text = gt_vals.get(gt_col, "") if gt_vals else ""
        ai_output = ""
        error_msg = ""
        method = ""
        score = 0.0
        precision = recall = 0.0
        debug: dict = {}

        try:
            input_doc = read_input_doc(filename) if filename else {}
            if not input_doc:
                error_msg = f"Document not found or empty: {filename}"
            elif km_obj:
                scored = score_document_for_stage(
                    input_doc,
                    KM_DIR,
                    call_fab_agent,
                    req.km_stage,
                    km_obj,
                    doc_id=doc_id,
                    config=pipeline_cfg,
                )
                ai_output = scored.get("ai_output", "")
                method = scored.get("method", "")
                error_msg = scored.get("error", "")
                debug = {
                    "upstream_methods": scored.get("upstream_methods", {}),
                    "families_ok": scored.get("families_ok", 0),
                    "family_count": scored.get("family_count", 0),
                }

                score_input = "" if str(ai_output).startswith("ERROR:") else ai_output
                score = float(evaluate(score_input, gt_text))

                if evaluate_detailed and score_input:
                    detail = evaluate_detailed(ai_output, gt_text)
                    precision = detail.get("precision", 0)
                    recall = detail.get("recall", 0)
        except Exception as exc:
            error_msg = str(exc)
            ai_output = f"ERROR: {exc}"
            method = "error"
            log.exception("score_batch process_pair failed for %s", doc_id or filename)

        return {
            "doc_id":    doc_id,
            "filename":  filename,
            "ai_output": ai_output,
            "gt_output": gt_text,
            "score":     round(score, 2),
            "precision": round(precision, 2),
            "recall":    round(recall, 2),
            "set":       p.get("set", ""),
            "error":     error_msg,
            "method":    method,
            "debug":     debug,
        }

    results = []
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = {ex.submit(process_pair, p): p for p in req.pairs}
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                pair = futures.get(future, {})
                log.exception("score_batch future failed for %s", pair.get("doc_id", "?"))
                results.append({
                    "doc_id":    pair.get("doc_id", ""),
                    "filename":  pair.get("filename", ""),
                    "ai_output": f"ERROR: {exc}",
                    "gt_output": "",
                    "score":     0.0,
                    "precision": 0.0,
                    "recall":    0.0,
                    "set":       pair.get("set", ""),
                    "error":     str(exc),
                    "method":    "error",
                    "debug":     {},
                })

    scores = [r["score"] for r in results]
    precs = [r["precision"] for r in results]
    recs = [r["recall"] for r in results]
    avg_score = round(sum(scores) / len(scores), 2) if scores else 0.0
    avg_prec = round(sum(precs) / len(precs), 2) if precs else 0.0
    avg_rec = round(sum(recs) / len(recs), 2) if recs else 0.0
    failures = [r for r in results if r["score"] < 50 or r.get("error")]

    return {
        "results":       results,
        "average_score": avg_score,
        "avg_precision": avg_prec,
        "avg_recall":    avg_rec,
        "failures":      failures,
        "failure_count": len(failures),
        "pipeline": {
            "use_rule_extraction": pipeline_cfg.use_rule_extraction,
            "use_rule_router": pipeline_cfg.use_rule_router,
            "use_esrs_lookup": pipeline_cfg.use_esrs_lookup,
            "use_pipeline_cache": False,
        },
    }


# ── Improve KM ────────────────────────────────────────────────────────────────
@protected_api.post("/improve-km")
def improve_km(req: ImproveKMRequest):
    # build failure summary
    example_lines = []
    for i, r in enumerate(req.all_results[:5]):
        ai  = str(r.get("ai_output", ""))[:300]
        gt  = str(r.get("gt_output", ""))[:300]
        s   = r.get("score", 0)
        example_lines.append(
            f"• [{i+1}] F1: {s:.1f}%\n"
            f"  Predicted: {ai}\n"
            f"  Ground truth: {gt}"
        )
    examples_str = "\n".join(example_lines) or "No examples captured."

    try:
        km_obj = json.loads(req.current_km)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid current_km JSON: {exc}") from exc

    if not isinstance(km_obj, dict):
        raise HTTPException(status_code=400, detail="current_km must be a JSON object")

    prompt = f"""You are an expert prompt engineer specialising in ESG/regulatory document tagging and classification.

Pipeline stage being improved: {req.km_stage}
GT column being evaluated: {req.gt_column}

This KM was tested on {req.n_learn_docs} documents and scored {req.learn_score:.1f}% F1 (target: {req.target_score}%).

Failure modes and examples (predicted vs ground truth):
{examples_str}

Current knowledge model (full JSON):
{req.current_km[:4000]}

Your task (TYPE 2 — TAGGING KNOWLEDGE MODEL IMPROVEMENT):
- Analyse the failure examples to find the actual pattern behind mis-classifications.
- Improve the knowledge model's rules (yes_when/no_when conditions, evidence_signals, routing/reconciliation logic) to reduce those failure modes.
- Do NOT change the fundamental task, and do NOT change or remove the "output_contract" field or any other original top-level key — only refine the rules inside it.
- Return ONLY the complete improved knowledge model as a single JSON object, starting with {{ and ending with }}. No preamble, no explanation, no markdown code fences."""

    try:
        raw = call_fab_improve_agent(prompt)
        raw = re.sub(r"```json|```", "", raw).strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            raw = match.group()

        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("Improved KM must be a JSON object")

            km_filename = IMPROVABLE_STAGES[req.km_stage]
            km_path = safe_path(KM_DIR, km_filename)
            backup_km_file(km_path)
            km_path.write_text(json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8")
            improved_km = json.dumps(parsed)
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=f"Improve agent returned invalid KM JSON: {exc}") from exc

        return {"improved_km": improved_km, "km_stage": req.km_stage}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Improve agent failed: {e}") from e


# ── Versions ──────────────────────────────────────────────────────────────────
@protected_api.post("/save-version")
def save_version(req: SaveVersionRequest):
    versions = _load_versions()
    versions.append({
        "label":       req.label,
        "km_json":     req.km_json,
        "km_stage":    req.km_stage,
        "val_score":   req.val_score,
        "precision":   req.precision,
        "recall":      req.recall,
        "final_score": req.final_score,
        "run_id":      req.run_id,
        "loop_num":    req.loop_num,
        "run_status":  req.run_status,
        "saved_at":    time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    _save_versions(versions)
    return {"saved": True}


@protected_api.get("/versions")
def get_versions():
    return {"versions": _load_versions()}


@protected_api.get("/versions/download")
def download_versions(run_id: str = ""):
    versions = _load_versions()
    if run_id:
        versions = [v for v in versions if v.get("run_id") == run_id]
    payload = json.dumps(versions, indent=2).encode("utf-8")
    filename = f"tagforge-versions-{run_id or 'all'}.json"
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@protected_api.post("/mark-run-status")
def mark_run_status(req: MarkRunStatusRequest):
    versions = _load_versions()
    for v in versions:
        if v.get("run_id") == req.run_id:
            v["run_status"] = req.status
    _save_versions(versions)
    return {"updated": True}


@protected_api.post("/clear-versions")
def clear_versions():
    _save_versions([])
    return {"cleared": True}


# ── GT preview ────────────────────────────────────────────────────────────────
@protected_api.get("/gt-preview")
def gt_preview(doc_id: str = ""):
    if doc_id:
        return {"doc_id": doc_id, "gt": get_gt_for_doc(doc_id)}
    gt = load_gt_csv()
    sample = list(gt.items())[:10]
    return {"total": len(gt), "sample": [{"doc_id": k, "gt": v} for k, v in sample]}


app.include_router(public_api)
app.include_router(protected_api)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)