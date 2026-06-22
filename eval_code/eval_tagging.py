# eval_tagging.py — default evaluation script for TagForge
# Exposes: evaluate(ai_output, gt_output) -> float (0-100)
# Also exposes: evaluate_detailed(ai_output, gt_output) -> dict
#
# ai_output and gt_output are semicolon-separated label strings,
# e.g. "Product Safety; Consumer Protection Laws"

import re

FUZZY_THRESHOLD = 0.7


def _split_labels(text: str) -> list[str]:
    parts = re.split(r"[;,]", text or "")
    return [p.strip() for p in parts if p.strip()]


def _label_tokens(label: str) -> set[str]:
    norm = re.sub(r"[_\-]+", " ", (label or "").lower())
    return {t for t in re.split(r"[^\w]+", norm) if len(t) > 1}


def _token_overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    shared = len(a & b)
    return shared / min(len(a), len(b))


def _fuzzy_match_counts(pred_labels: list[str], gold_labels: list[str], threshold: float = FUZZY_THRESHOLD) -> tuple[int, int, int]:
    """Greedy one-to-one fuzzy label matching. Returns (tp, fp, fn)."""
    if not gold_labels:
        return 0, len(pred_labels), 0
    if not pred_labels:
        return 0, 0, len(gold_labels)

    pred_tokens = [_label_tokens(label) for label in pred_labels]
    gold_tokens = [_label_tokens(label) for label in gold_labels]
    used_pred: set[int] = set()
    tp = 0

    for gt in gold_tokens:
        best_idx = -1
        best_score = 0.0
        for idx, pt in enumerate(pred_tokens):
            if idx in used_pred:
                continue
            score = _token_overlap(pt, gt)
            if score >= threshold and score > best_score:
                best_score = score
                best_idx = idx
        if best_idx >= 0:
            tp += 1
            used_pred.add(best_idx)

    fp = len(pred_labels) - len(used_pred)
    fn = len(gold_labels) - tp
    return tp, fp, fn


def _scores_from_counts(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    pred_n = tp + fp
    gold_n = tp + fn
    precision = tp / pred_n if pred_n else 0.0
    recall = tp / gold_n if gold_n else 1.0
    f1 = (2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0)
    return precision, recall, f1


def evaluate(ai_output: str, gt_output: str) -> float:
    """
    Token-overlap fuzzy F1 between predicted and ground-truth label sets.
    Labels match when word-token overlap >= FUZZY_THRESHOLD (default 0.7).
    Returns 0–100.
    """
    pred_labels = _split_labels(ai_output)
    gold_labels = _split_labels(gt_output)
    if not gold_labels:
        return 100.0 if not pred_labels else 0.0
    if not pred_labels:
        return 0.0
    tp, fp, fn = _fuzzy_match_counts(pred_labels, gold_labels)
    _, _, f1 = _scores_from_counts(tp, fp, fn)
    return round(f1 * 100, 2)


def evaluate_detailed(ai_output: str, gt_output: str) -> dict:
    """Returns full breakdown: precision, recall, F1, TP, FP, FN."""
    pred_labels = _split_labels(ai_output)
    gold_labels = _split_labels(gt_output)
    tp, fp, fn = _fuzzy_match_counts(pred_labels, gold_labels)
    precision, recall, f1 = _scores_from_counts(tp, fp, fn)

    pred_tokens = [_label_tokens(label) for label in pred_labels]
    gold_tokens = [_label_tokens(label) for label in gold_labels]
    used_pred: set[int] = set()
    matched_gold: set[int] = set()
    for gi, gt in enumerate(gold_tokens):
        best_idx = -1
        best_score = 0.0
        for idx, pt in enumerate(pred_tokens):
            if idx in used_pred:
                continue
            score = _token_overlap(pt, gt)
            if score >= FUZZY_THRESHOLD and score > best_score:
                best_score = score
                best_idx = idx
        if best_idx >= 0:
            used_pred.add(best_idx)
            matched_gold.add(gi)

    return {
        "score":     round(f1 * 100, 2),
        "precision": round(precision * 100, 2),
        "recall":    round(recall * 100, 2),
        "f1":        round(f1 * 100, 2),
        "tp":        tp,
        "fp":        fp,
        "fn":        fn,
        "pred_labels": pred_labels,
        "gold_labels": gold_labels,
        "correct":     [gold_labels[i] for i in sorted(matched_gold)],
        "missed":      [gold_labels[i] for i in range(len(gold_labels)) if i not in matched_gold],
        "extra":       [pred_labels[i] for i in range(len(pred_labels)) if i not in used_pred],
    }
