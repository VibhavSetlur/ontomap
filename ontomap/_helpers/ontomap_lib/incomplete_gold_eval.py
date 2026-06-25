"""Evaluation under incomplete gold standards.

Adds three metrics on top of the existing `evaluate.py`:

1. `bpref` — Buckley & Voorhees, designed for incomplete relevance judgments.
   Only counts judged docs in the ranking; robust to missing labels.
2. `fraction_of_gold_recovered@k` — recall@k computed over the *known* gold,
   reported alongside hits@k to address Philippe's concern that a binary
   "≥1 of gold in top-N" metric overstates performance when the gold is
   conservative.
3. `soft_hits_at_k_ec` — counts a candidate as a hit if its EC matches any
   gold reaction's EC at level >= 3 (ec_hierarchy_match >= 0.75). This is a
   biochemically-motivated "near-miss" credit.

Plus LLM-as-judge utility (`judge_top1_miss`) for manual-audit-on-a-sample.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Sequence

import numpy as np


def bpref(retrieved: Sequence[str], relevant: set[str], non_relevant: set[str]) -> float:
    """Buckley & Voorhees bpref.

    bpref = (1/R) * sum_{r in retrieved relevant docs}
                       (1 - |non-relevant docs ranked above r within first R| / R)

    Where R = number of judged relevant docs. Docs not in `relevant` and not in
    `non_relevant` are *unjudged* and ignored in the sum (this is the property
    that makes bpref tolerant of incomplete judgments).
    """
    R = len(relevant)
    if R == 0:
        return 0.0
    nr_above = 0
    score = 0.0
    nr_seen = 0
    for doc in retrieved:
        if doc in relevant:
            # cap nr_seen at R per spec
            penalty = min(nr_seen, R) / R
            score += 1.0 - penalty
        elif doc in non_relevant:
            nr_seen += 1
    return score / R


def fraction_of_gold_recovered_at_k(retrieved: Sequence[str], gold: Sequence[str], k: int) -> float:
    """How many of the known gold mappings appear in the top-k?
    Identical to recall@k but renamed for Philippe's language.
    """
    if not gold:
        return 0.0
    return len(set(retrieved[:k]) & set(gold)) / len(set(gold))


def soft_hit_at_k_ec(
    retrieved: Sequence[str],
    gold: Sequence[str],
    k: int,
    cand_ecs: dict[str, list[str]],
    gold_ecs_union: list[str],
    ec_hierarchy_fn,
    min_match: float = 0.75,
) -> int:
    """Returns 1 if any of retrieved[:k] is a 'near-miss': either it IS a gold,
    or its EC matches a gold reaction's EC at >= min_match (default 0.75 = 3-level).
    """
    if not gold:
        return 0
    gold_set = set(gold)
    for r in retrieved[:k]:
        if r in gold_set:
            return 1
        cand_ec = cand_ecs.get(r) or []
        if cand_ec and gold_ecs_union and ec_hierarchy_fn(cand_ec, gold_ecs_union) >= min_match:
            return 1
    return 0


# ---------- judge prompt template ----------

JUDGE_PROMPT = """You are an enzymology expert auditing an automated ontology mapper.

Source term (from SSO/KO ontology):
  ID:     {src_id}
  Name:   {src_name}
  EC:     {src_ec}

Mapper's TOP-1 prediction (a ModelSEED reaction):
  ID:       {pred_id}
  Name:     {pred_name}
  EC:       {pred_ec}
  Equation: {pred_equation}
  Pathway:  {pred_pathway}

Curated gold standard for this source term (zero or more ModelSEED reactions):
  Gold IDs:    {gold_ids}
  Gold names:  {gold_names}

The mapper's TOP-1 is NOT in the gold set. Decide whether the top-1 prediction
is nevertheless biochemically valid (e.g., same enzymatic family, same
reaction-type, same pathway). Possible verdicts:

  PLAUSIBLE_SIBLING — same enzymatic activity / EC family / pathway-neighbor;
                      gold-set incompleteness is the cause, not mapper error.
  TRUE_MISS         — the prediction is mechanistically unrelated.
  UNSURE            — insufficient information.

Return JSON only:
  {{"verdict": "PLAUSIBLE_SIBLING|TRUE_MISS|UNSURE", "rationale": "1-2 sentence reason"}}
"""


def stratified_sample(
    per_query: list[dict],
    sample_size: int = 50,
    miss_filter: bool = True,
    seed: int = 17,
) -> list[dict]:
    """Sample queries stratified by role-type bucket and gold-size bucket.
    If miss_filter, restrict to queries where p@1 == 0 (top-1 was not in gold)
    and hits@10 == 0 (not even a top-10 hit) — the strict miss subset where the
    gold-incompleteness hypothesis matters most.
    """
    import random
    rng = random.Random(seed)
    eligible = per_query
    if miss_filter:
        eligible = [q for q in per_query if q.get("p@1", 0) == 0 and q.get("hits@10", 0) == 0]
    if len(eligible) <= sample_size:
        return eligible
    # very simple stratification by gold_bucket
    buckets: dict[str, list[dict]] = defaultdict(list)
    for q in eligible:
        buckets[q.get("gold_bucket", "?")].append(q)
    out: list[dict] = []
    per_bucket = max(1, sample_size // max(len(buckets), 1))
    for k in sorted(buckets.keys()):
        out.extend(rng.sample(buckets[k], min(per_bucket, len(buckets[k]))))
        if len(out) >= sample_size:
            break
    return out[:sample_size]
