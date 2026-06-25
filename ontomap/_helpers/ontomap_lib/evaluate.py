"""Evaluation metrics for many-to-many ontology mappings.

Per ADR-007, retrieval metrics use multi-target semantics:
a retrieval is a hit if ANY gold target appears in top-k.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Sequence


def hits_at_k(retrieved: Sequence[str], gold: Sequence[str], k: int) -> int:
    """1 if retrieved[:k] intersects gold, else 0."""
    if not gold:
        return 0
    return int(bool(set(retrieved[:k]) & set(gold)))


def recall_at_k(retrieved: Sequence[str], gold: Sequence[str], k: int) -> float:
    if not gold:
        return 0.0
    return len(set(retrieved[:k]) & set(gold)) / len(set(gold))


def reciprocal_rank(retrieved: Sequence[str], gold: Sequence[str]) -> float:
    """1 / rank of first gold hit (1-indexed), 0 if none."""
    gold_set = set(gold)
    for i, r in enumerate(retrieved, start=1):
        if r in gold_set:
            return 1.0 / i
    return 0.0


def precision_at_1(retrieved: Sequence[str], gold: Sequence[str]) -> int:
    if not retrieved or not gold:
        return 0
    return int(retrieved[0] in set(gold))


def aggregate_metrics(
    per_query: list[dict],
    ks: tuple[int, ...] = (1, 5, 10, 20),
) -> dict[str, float]:
    """Aggregate per-query results into mean metrics."""
    n = max(len(per_query), 1)
    out = {}
    for k in ks:
        out[f"hits@{k}"] = sum(q[f"hits@{k}"] for q in per_query) / n
        out[f"recall@{k}"] = sum(q[f"recall@{k}"] for q in per_query) / n
    out["mrr"] = sum(q["mrr"] for q in per_query) / n
    out["p@1"] = sum(q["p@1"] for q in per_query) / n
    out["n"] = len(per_query)
    return out


def score_one_query(
    retrieved: Sequence[str],
    gold: Sequence[str],
    ks: tuple[int, ...] = (1, 5, 10, 20),
) -> dict:
    row = {
        "mrr": reciprocal_rank(retrieved, gold),
        "p@1": precision_at_1(retrieved, gold),
    }
    for k in ks:
        row[f"hits@{k}"] = hits_at_k(retrieved, gold, k)
        row[f"recall@{k}"] = recall_at_k(retrieved, gold, k)
    return row


def stratified_metrics(
    per_query: list[dict],
    strata_key: str,
    ks: tuple[int, ...] = (1, 5, 10, 20),
) -> dict[str, dict[str, float]]:
    """Group per-query dicts by the value of strata_key, aggregate within each group."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for q in per_query:
        groups[q.get(strata_key, "?")].append(q)
    return {k: aggregate_metrics(v, ks=ks) for k, v in groups.items()}
