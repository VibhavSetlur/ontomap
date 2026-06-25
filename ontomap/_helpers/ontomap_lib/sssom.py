"""SSSOM TSV serializer.

Emits mappings in the Simple Standard for Sharing Ontological Mappings format
(https://mapping-commons.github.io/sssom/). Other tools in the OBO ecosystem
(KBase, Mondo, OAK) consume SSSOM TSV directly.

For confidence/predicate semantics see ADR-004 in DECISIONS.md.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable


SSSOM_HEADER_PREFIX = """# curie_map:
#   SSO: "https://kbase.us/sso/"
#   MSRXN: "https://modelseed.org/biochem/reactions/"
#   KO: "https://www.kegg.jp/entry/"
#   EC: "https://enzyme.expasy.org/EC/"
#   semapv: "https://w3id.org/semapv/vocab/"
#   skos: "http://www.w3.org/2004/02/skos/core#"
# license: https://creativecommons.org/publicdomain/zero/1.0/
# mapping_set_id: ontomap-mapping-{set_id}
# mapping_set_description: "{description}"
# mapping_tool: ontomap
# mapping_tool_version: 0.0.0
# subject_source: {subject_source}
# object_source: MSRXN
# mapping_date: {date}
"""


SSSOM_COLUMNS = [
    "subject_id",
    "subject_label",
    "predicate_id",
    "object_id",
    "object_label",
    "mapping_justification",
    "confidence",
    "subject_match_field",
    "match_string",
    "comment",
]


def _predicate_for_confidence(conf: float) -> str:
    """Pick a SKOS predicate based on confidence."""
    if conf >= 0.85:
        return "skos:exactMatch"
    if conf >= 0.65:
        return "skos:closeMatch"
    return "skos:relatedMatch"


def normalize_rxn_id(rxn_id: str) -> str:
    """Convert raw rxn ID into a SSSOM-compatible CURIE."""
    if rxn_id.startswith("MSRXN:"):
        return rxn_id
    return f"MSRXN:{rxn_id}"


def write_sssom(
    rows: Iterable[dict],
    path: Path,
    set_id: str,
    description: str,
    subject_source: str,
    date: str,
) -> None:
    """Write a list of mapping rows to a SSSOM TSV file with header preamble.

    Each row dict should have keys from SSSOM_COLUMNS (missing values are blank).
    Header preamble carries curie_map and metadata per the SSSOM spec.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        f.write(SSSOM_HEADER_PREFIX.format(
            set_id=set_id,
            description=description,
            subject_source=subject_source,
            date=date,
        ))
        writer = csv.DictWriter(f, fieldnames=SSSOM_COLUMNS, delimiter="\t")
        writer.writeheader()
        for r in rows:
            row = {c: r.get(c, "") for c in SSSOM_COLUMNS}
            if "confidence" in row and isinstance(row["confidence"], float):
                row["confidence"] = f"{row['confidence']:.4f}"
            writer.writerow(row)


def build_mapping_rows(
    queries: list[dict],
    subject_label_fn,
    object_label_fn,
    *,
    top_k: int = 1,
    min_confidence: float = 0.0,
    subject_id_field: str = "sso_id",
    score_field: str = "scores_field",  # comma-separated list of floats
    candidate_field: str = "candidates_field",  # comma-separated list of object IDs
    justification: str = "semapv:SemanticSimilarityThresholdMatching",
    score_strategy: str = "cosine",   # "cosine" or "percentile"
) -> list[dict]:
    """Convert per-query records into SSSOM rows.

    score_strategy:
      - "cosine": use raw scores (BioLORD bi-encoder, range ~0-1).
      - "percentile": rank-normalize the top-1 scores across the dataset to
        [0, 1] before applying predicate thresholds. Use this for
        cross-encoder logits which span wide ranges and aren't directly
        comparable to cosine thresholds.
    """
    # First pass: collect top-1 scores for percentile normalization
    parsed_queries = []
    for q in queries:
        sid = q[subject_id_field]
        candidates = q[candidate_field]
        scores = q[score_field]
        if isinstance(candidates, str):
            candidates = [c for c in candidates.split(";") if c]
        if isinstance(scores, str):
            scores = [float(s) for s in scores.split(";") if s]
        parsed_queries.append({"sid": sid, "candidates": candidates, "scores": scores})

    if score_strategy == "percentile":
        top1s = sorted(q["scores"][0] for q in parsed_queries if q["scores"])
        n = len(top1s)
        def _norm(raw):
            if not top1s:
                return 0.0
            # bisect to find rank
            lo, hi = 0, n
            while lo < hi:
                mid = (lo + hi) // 2
                if top1s[mid] < raw:
                    lo = mid + 1
                else:
                    hi = mid
            return lo / max(n - 1, 1)
    else:
        _norm = lambda x: x  # noqa: E731

    out = []
    for q in parsed_queries:
        sid = q["sid"]
        candidates = q["candidates"]
        scores = q["scores"]
        if not candidates:
            continue
        for rank in range(min(top_k, len(candidates))):
            cid = candidates[rank]
            raw_score = scores[rank] if rank < len(scores) else 0.0
            norm_score = _norm(raw_score)
            if norm_score < min_confidence:
                continue
            predicate = _predicate_for_confidence(norm_score)
            out.append({
                "subject_id": sid,
                "subject_label": subject_label_fn(sid),
                "predicate_id": predicate,
                "object_id": normalize_rxn_id(cid),
                "object_label": object_label_fn(cid),
                "mapping_justification": justification,
                "confidence": float(norm_score),
                "subject_match_field": "rdfs:label+derived_context",
                "match_string": "",
                "comment": (f"rank={rank+1}; ontomap-v0.0.0; raw_score={raw_score:.4f}"
                            if score_strategy == "percentile"
                            else f"rank={rank+1}; ontomap-v0.0.0"),
            })
    return out
