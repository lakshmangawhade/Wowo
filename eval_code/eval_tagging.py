# eval_tagging.py — default evaluation script for TagForge
# Exposes: evaluate(ai_output, gt_output) -> float (0-100)
# Also exposes: evaluate_detailed(ai_output, gt_output) -> dict
#
# ai_output and gt_output are semicolon-separated label strings,
# e.g. "Product Safety; Consumer Protection Laws"

import re


def _normalise(text: str) -> set[str]:
    """Split on ';' or ',', lowercase, strip whitespace."""
    parts = re.split(r"[;,]", text or "")
    return {p.strip().lower() for p in parts if p.strip()}


def evaluate(ai_output: str, gt_output: str) -> float:
    """
    Token-level F1 between predicted and ground-truth label sets.
    Returns 0–100.
    """
    pred = _normalise(ai_output)
    gold = _normalise(gt_output)
    if not gold:
        return 100.0 if not pred else 0.0
    if not pred:
        return 0.0
    tp = len(pred & gold)
    if tp == 0:
        return 0.0
    precision = tp / len(pred)
    recall    = tp / len(gold)
    f1 = 2 * precision * recall / (precision + recall)
    return round(f1 * 100, 2)


def evaluate_detailed(ai_output: str, gt_output: str) -> dict:
    """
    Returns full breakdown: precision, recall, F1, TP, FP, FN.
    """
    pred = _normalise(ai_output)
    gold = _normalise(gt_output)
    tp = len(pred & gold)
    fp = len(pred - gold)
    fn = len(gold - pred)
    precision = tp / len(pred) if pred else 0.0
    recall    = tp / len(gold) if gold else 1.0
    f1 = (2 * precision * recall / (precision + recall)
          if (precision + recall) > 0 else 0.0)
    return {
        "score":     round(f1 * 100, 2),
        "precision": round(precision * 100, 2),
        "recall":    round(recall * 100, 2),
        "f1":        round(f1 * 100, 2),
        "tp":        tp,
        "fp":        fp,
        "fn":        fn,
        "pred_labels": sorted(pred),
        "gold_labels": sorted(gold),
        "correct":     sorted(pred & gold),
        "missed":      sorted(gold - pred),
        "extra":       sorted(pred - gold),
    }