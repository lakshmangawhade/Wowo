# loops.py — TagForge loop state management
from __future__ import annotations
import json
import time
from dataclasses import dataclass, field, asdict
from typing import Optional
@dataclass
class LoopResult:
    loop:          int
    learn_score:   float      # avg F1 on learn set
    val_score:     float      # avg F1 on val set
    km_stage:      str        # which KM stage was improved
    km_json:       str        # the current KM JSON text
    failure_count: int   = 0
    precision:     float = 0.0
    recall:        float = 0.0
    timestamp:     float = field(default_factory=time.time)
    def delta(self, prev: Optional["LoopResult"]) -> Optional[float]:
        if prev is None:
            return None
        return round(self.val_score - prev.val_score, 2)
    def to_dict(self):
        return asdict(self)
@dataclass
class RunState:
    km_versions:   list[dict]      = field(default_factory=list)
    loop_results:  list[dict]      = field(default_factory=list)
    best_loop_idx: int             = 0
    final_score:   Optional[float] = None
    target_score:  float           = 80.0
    max_loops:     int             = 5
    km_stage:      str             = "km_01z_specific_topic_reconciler"
    def best_result(self) -> Optional[dict]:
        if not self.loop_results:
            return None
        return self.loop_results[self.best_loop_idx]
    def best_km(self) -> str:
        best = self.best_result()
        if best:
            return best["km_json"]
        if self.km_versions:
            return self.km_versions[0]["km"]
        return ""
    def record_loop(self, result: LoopResult):
        d = result.to_dict()
        if not self.loop_results:
            self.loop_results.append(d)
            self.best_loop_idx = 0
            return
        prev_best_score = self.loop_results[self.best_loop_idx]["val_score"]
        self.loop_results.append(d)
        if result.val_score >= prev_best_score:
            self.best_loop_idx = len(self.loop_results) - 1
    def to_report(self) -> dict:
        return {
            "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "config": {
                "target_score": self.target_score,
                "max_loops":    self.max_loops,
                "km_stage":     self.km_stage,
            },
            "loop_results": [
                {
                    "loop":          r["loop"],
                    "learn_score":   r["learn_score"],
                    "val_score":     r["val_score"],
                    "failure_count": r["failure_count"],
                    "precision":     r.get("precision", 0),
                    "recall":        r.get("recall", 0),
                    "km_stage":      r["km_stage"],
                }
                for r in self.loop_results
            ],
            "best_loop_idx": self.best_loop_idx,
            "final_score":   self.final_score,
            "best_km":       self.best_km(),
        }
def format_failures(failures: list[dict], max_show: int = 15) -> str:
    lines = []
    for i, f in enumerate(failures[:max_show]):
        lines.append(
            f"• [{i+1}] doc: {f.get('doc_id', '?')} "
            f"— F1: {f.get('score', 0):.1f}% "
            f"| Predicted: {f.get('ai_output', '')[:50]} "
            f"| GT: {f.get('gt_output', '')[:50]}"
        )
    if len(failures) > max_show:
        lines.append(f"  … and {len(failures) - max_show} more failures")
    return "\n".join(lines) if lines else "No failure cases captured."