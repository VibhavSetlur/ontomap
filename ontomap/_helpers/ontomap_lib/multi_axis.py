"""Multi-axis embedding and re-ranking.

Each source/target item is encoded into multiple vectors (one per semantic axis):

Source-side (SSO role or KO term):
    NAME    — cleaned function label (EC tags stripped)
    EC      — EC number expanded with class-hierarchy text

Target-side (ModelSEED reaction):
    NAME       — reaction name (+ top-5 synonyms)
    EC         — EC number expanded with class-hierarchy text
    EQUATION   — reaction equation in named compounds
    PATHWAY    — top-10 pathway names from ModelSEED Aliases

Retrieval uses NAME-vs-NAME FAISS. Re-ranking forms a weighted sum of
pairwise axis similarities plus a symbolic EC-hierarchy match.

Why this is different from exp004 facet ablation:
    exp004 added context *inside* a single embedding string; the encoder
    was forced to compress all signals into one direction. Here each axis
    keeps its own direction; weights at re-rank decide how much each
    contributes for each query.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

from . import data
from .embed import build_index, encode_texts


# ---------- EC class hierarchy ----------

EC_CLASS_NAMES = {
    "1": "Oxidoreductase",
    "2": "Transferase",
    "3": "Hydrolase",
    "4": "Lyase",
    "5": "Isomerase",
    "6": "Ligase",
    "7": "Translocase",
}

# A coarse second-level enrichment (intentionally short; full enzyme nomenclature
# would be 300+ entries — for the embedding axis we just need *some* family signal).
EC_SUBCLASS_HINTS = {
    "1.1": "acting on CH-OH group of donors",
    "1.2": "acting on aldehyde or oxo group",
    "1.3": "acting on CH-CH group of donors",
    "1.4": "acting on CH-NH2 group of donors",
    "1.5": "acting on CH-NH group of donors",
    "1.6": "acting on NADH or NADPH",
    "1.7": "acting on other nitrogenous compounds",
    "1.8": "acting on sulfur group of donors",
    "1.10": "acting on diphenols",
    "1.11": "peroxidases",
    "1.13": "acting on single donor with O2",
    "1.14": "acting on paired donors with O2",
    "1.17": "acting on CH or CH2 groups",
    "2.1": "transferring one-carbon groups, methyltransferase",
    "2.2": "transferring aldehyde or ketone groups",
    "2.3": "acyltransferase",
    "2.4": "glycosyltransferase",
    "2.5": "transferring alkyl or aryl groups",
    "2.6": "transferring nitrogenous groups, aminotransferase",
    "2.7": "transferring phosphorus-containing groups, kinase",
    "2.8": "transferring sulfur-containing groups",
    "3.1": "acting on ester bonds, esterase",
    "3.2": "glycosylase",
    "3.3": "acting on ether bonds",
    "3.4": "acting on peptide bonds, peptidase",
    "3.5": "acting on C-N bonds other than peptide",
    "3.6": "acting on acid anhydrides",
    "4.1": "carbon-carbon lyase, decarboxylase",
    "4.2": "carbon-oxygen lyase, hydro-lyase, dehydratase",
    "4.3": "carbon-nitrogen lyase, ammonia-lyase",
    "4.4": "carbon-sulfur lyase",
    "4.6": "phosphorus-oxygen lyase, cyclase",
    "5.1": "racemase, epimerase",
    "5.2": "cis-trans isomerase",
    "5.3": "intramolecular oxidoreductase",
    "5.4": "intramolecular transferase, mutase",
    "5.5": "intramolecular lyase",
    "6.1": "forming carbon-oxygen bonds, aminoacyl-tRNA ligase",
    "6.2": "forming carbon-sulfur bonds",
    "6.3": "forming carbon-nitrogen bonds",
    "6.4": "forming carbon-carbon bonds, carboxylase",
    "6.5": "forming phosphoric ester bonds",
    "7.1": "translocating hydrons",
    "7.2": "translocating inorganic cations",
    "7.3": "translocating inorganic anions",
    "7.4": "translocating amino acids and peptides",
    "7.5": "translocating carbohydrates",
    "7.6": "translocating other compounds",
}


def expand_ec_text(ec: str) -> str:
    """Render an EC number as a hierarchical text block.

    Example: '4.2.1.138' →
        'EC 4.2.1.138 4.2.1.- 4.2.-.- 4.-.-.- carbon-oxygen lyase hydro-lyase dehydratase Lyase'
    """
    if not ec:
        return ""
    parts = ec.split(".")
    if len(parts) < 1:
        return ec
    bits = [f"EC {ec}"]
    if len(parts) >= 4:
        bits.append(f"{parts[0]}.{parts[1]}.{parts[2]}.-")
    if len(parts) >= 3:
        bits.append(f"{parts[0]}.{parts[1]}.-.-")
        sub = EC_SUBCLASS_HINTS.get(f"{parts[0]}.{parts[1]}")
        if sub:
            bits.append(sub)
    bits.append(f"{parts[0]}.-.-.-")
    cls = EC_CLASS_NAMES.get(parts[0])
    if cls:
        bits.append(cls)
    return " ".join(bits)


def ec_hierarchy_match(src_ecs: list[str], tgt_ecs: list[str]) -> float:
    """Return the max symbolic agreement between any src EC and any tgt EC.

    Score: 1.0 = exact 4-level match, 0.75 = 3-level, 0.5 = 2-level, 0.25 = 1-level, 0 = different.
    """
    if not src_ecs or not tgt_ecs:
        return 0.0
    best = 0.0
    for s in src_ecs:
        s_parts = s.split(".")
        for t in tgt_ecs:
            t_parts = t.split(".")
            match = 0
            for i in range(min(4, len(s_parts), len(t_parts))):
                if s_parts[i] == "-" or t_parts[i] == "-":
                    break
                if s_parts[i] == t_parts[i]:
                    match += 1
                else:
                    break
            best = max(best, match / 4.0)
    return best


# ---------- text rendering per axis ----------

EC_INLINE_RE = re.compile(r"\s*\(?EC[:\s]*\d+\.\d+\.\d+\.[\d\-]+\)?", re.IGNORECASE)


def clean_name(name: str) -> str:
    """Strip inline EC numbers and trailing brackets from a name."""
    if not name:
        return ""
    cleaned = re.sub(r"\s*\[\s*EC[^\]]*\]", "", name)
    cleaned = EC_INLINE_RE.sub("", cleaned)
    # remove any leftover empty bracket pairs
    cleaned = re.sub(r"\s*\[\s*\]", "", cleaned)
    cleaned = re.sub(r"\s*\(\s*\)", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned or name


def render_source_axes(label: str) -> dict[str, str]:
    """Render a source term (SSO role name / KO definition) to per-axis text.

    `label` is the raw name string. For KOs this includes definition + brackets.
    For multifunctional roles (' / ' or ' @ ') we keep the joined name on NAME
    axis — components are handled by the encoder via subword tokenization.
    """
    cleaned = clean_name(label)
    ecs = data.parse_ec_from_text(label)
    ec_text = " ; ".join(expand_ec_text(e) for e in ecs) if ecs else ""
    return {
        "NAME": cleaned,
        "EC": ec_text,
        "_ecs_raw": ecs,
    }


def render_target_axes(
    rxn_row: dict,
    ec_list: list[str] | None,
    pathways: list[str] | None,
    alt_names: list[str] | None,
) -> dict[str, str]:
    name = (rxn_row.get("name") or "").strip()
    inline_ecs = data.parse_ec_from_text(rxn_row.get("ec_numbers") or "")
    all_ecs = list(dict.fromkeys((ec_list or []) + inline_ecs))
    ec_text = " ; ".join(expand_ec_text(e) for e in all_ecs) if all_ecs else ""

    name_axis = name or rxn_row["id"]
    if alt_names:
        uniq_alts = [n for n in alt_names if n and n.lower() != name.lower()][:5]
        if uniq_alts:
            name_axis = name_axis + " ; " + " ; ".join(uniq_alts)

    equation = (rxn_row.get("definition") or "").strip()
    if equation in {"null", "None"}:
        equation = ""

    pathway_axis = ""
    if pathways:
        uniq = list(dict.fromkeys(pathways))[:10]
        pathway_axis = " ; ".join(uniq)

    return {
        "NAME": name_axis,
        "EC": ec_text,
        "EQUATION": equation,
        "PATHWAY": pathway_axis,
        "_ecs_raw": all_ecs,
    }


# ---------- batch builders ----------

@dataclass
class SourceAxisIndex:
    ids: list[str]
    name_emb: np.ndarray   # (N, D) normalized
    ec_emb: np.ndarray
    ecs_raw: list[list[str]]


@dataclass
class TargetAxisIndex:
    ids: list[str]
    name_emb: np.ndarray
    ec_emb: np.ndarray
    eq_emb: np.ndarray
    pw_emb: np.ndarray
    ecs_raw: list[list[str]]
    name_faiss: object   # IndexFlatIP


def build_source_axes(items: dict[str, str], model_name: str = "biolord") -> SourceAxisIndex:
    """items: {id: raw_label}"""
    ids = list(items.keys())
    rendered = [render_source_axes(items[i]) for i in ids]
    names = [r["NAME"] for r in rendered]
    ecs = [r["EC"] or r["NAME"] for r in rendered]   # fall back to name so empty EC isn't a zero vector
    ecs_raw = [r["_ecs_raw"] for r in rendered]
    name_emb = encode_texts(names, model_name=model_name)
    ec_emb = encode_texts(ecs, model_name=model_name)
    return SourceAxisIndex(ids=ids, name_emb=name_emb, ec_emb=ec_emb, ecs_raw=ecs_raw)


def build_target_axes(model_name: str = "biolord") -> TargetAxisIndex:
    reactions = data.load_modelseed_reactions()
    ecs = data.load_modelseed_reaction_ecs()
    pathways = data.load_modelseed_reaction_pathways()
    alt_names = data.load_modelseed_reaction_names()

    ids: list[str] = []
    names: list[str] = []
    ec_texts: list[str] = []
    eq_texts: list[str] = []
    pw_texts: list[str] = []
    ecs_raw: list[list[str]] = []

    for rxn_id, row in reactions.items():
        if row.get("is_obsolete") in ("1", "true", "True"):
            continue
        rendered = render_target_axes(row, ecs.get(rxn_id), pathways.get(rxn_id), alt_names.get(rxn_id))
        ids.append(rxn_id)
        names.append(rendered["NAME"])
        ec_texts.append(rendered["EC"] or rendered["NAME"])
        eq_texts.append(rendered["EQUATION"] or rendered["NAME"])
        pw_texts.append(rendered["PATHWAY"] or rendered["NAME"])
        ecs_raw.append(rendered["_ecs_raw"])

    name_emb = encode_texts(names, model_name=model_name, batch_size=128)
    ec_emb = encode_texts(ec_texts, model_name=model_name, batch_size=128)
    eq_emb = encode_texts(eq_texts, model_name=model_name, batch_size=128)
    pw_emb = encode_texts(pw_texts, model_name=model_name, batch_size=128)

    return TargetAxisIndex(
        ids=ids,
        name_emb=name_emb,
        ec_emb=ec_emb,
        eq_emb=eq_emb,
        pw_emb=pw_emb,
        ecs_raw=ecs_raw,
        name_faiss=build_index(name_emb),
    )


# ---------- retrieval + re-ranking ----------

DEFAULT_WEIGHTS = {
    # source-axis × target-axis pairwise weights
    "nn": 1.0,   # name-name (anchor; dominates retrieval too)
    "ne": 0.20,  # name-ec
    "nq": 0.15,  # name-equation
    "np": 0.10,  # name-pathway
    "en": 0.20,  # ec-name
    "ee": 0.30,  # ec-ec
    "eq": 0.10,  # ec-equation
    "ep": 0.05,  # ec-pathway
    "ech": 0.40, # symbolic EC hierarchy match (0..1)
}


def rerank_one(
    src_name_v: np.ndarray,
    src_ec_v: np.ndarray,
    src_ecs_raw: list[str],
    cand_idx: np.ndarray,
    target: TargetAxisIndex,
    weights: dict[str, float],
) -> np.ndarray:
    """Return reranked scores (length len(cand_idx))."""
    t_name = target.name_emb[cand_idx]
    t_ec = target.ec_emb[cand_idx]
    t_eq = target.eq_emb[cand_idx]
    t_pw = target.pw_emb[cand_idx]

    s_nn = t_name @ src_name_v
    s_ne = t_ec @ src_name_v
    s_nq = t_eq @ src_name_v
    s_np = t_pw @ src_name_v
    s_en = t_name @ src_ec_v
    s_ee = t_ec @ src_ec_v
    s_eq = t_eq @ src_ec_v
    s_ep = t_pw @ src_ec_v

    score = (
        weights["nn"] * s_nn +
        weights["ne"] * s_ne +
        weights["nq"] * s_nq +
        weights["np"] * s_np +
        weights["en"] * s_en +
        weights["ee"] * s_ee +
        weights["eq"] * s_eq +
        weights["ep"] * s_ep
    )

    if weights.get("ech", 0) and src_ecs_raw:
        ec_terms = np.array([
            ec_hierarchy_match(src_ecs_raw, target.ecs_raw[i])
            for i in cand_idx
        ], dtype=np.float32)
        score = score + weights["ech"] * ec_terms

    return score


def retrieve_and_rerank(
    source: SourceAxisIndex,
    target: TargetAxisIndex,
    top_k_retrieve: int = 100,
    top_k_out: int = 10,
    weights: dict[str, float] | None = None,
) -> dict[str, list[tuple[str, float]]]:
    """Run multi-axis retrieve + rerank for every source item."""
    weights = weights or DEFAULT_WEIGHTS
    # batch retrieve via FAISS
    sims, cand_idx = target.name_faiss.search(source.name_emb, top_k_retrieve)
    out: dict[str, list[tuple[str, float]]] = {}
    for i, sid in enumerate(source.ids):
        ci = cand_idx[i]
        scores = rerank_one(
            source.name_emb[i],
            source.ec_emb[i],
            source.ecs_raw[i],
            ci,
            target,
            weights,
        )
        # sort
        order = np.argsort(-scores)[:top_k_out]
        out[sid] = [(target.ids[int(ci[int(o)])], float(scores[int(o)])) for o in order]
    return out


# ---------- weight sweep ----------

def coordinate_descent_weights(
    source: SourceAxisIndex,
    target: TargetAxisIndex,
    gold: dict[str, list[str]],
    initial_weights: dict[str, float] | None = None,
    metric: str = "hits@10",
    rounds: int = 2,
    grid: tuple[float, ...] = (0.0, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0),
    top_k_retrieve: int = 100,
) -> tuple[dict[str, float], float]:
    """Simple coordinate descent over weight dict. Returns (best_weights, best_score)."""
    weights = dict(initial_weights or DEFAULT_WEIGHTS)
    eval_ids = [sid for sid in source.ids if sid in gold and gold[sid]]
    print(f"sweep over {len(eval_ids)} queries with gold")

    def score(w):
        preds = retrieve_and_rerank(source, target, top_k_retrieve=top_k_retrieve, top_k_out=10, weights=w)
        if metric == "hits@10":
            hits = sum(
                1 for sid in eval_ids
                if any(p[0] in set(gold[sid]) for p in preds[sid][:10])
            )
            return hits / len(eval_ids)
        elif metric == "hits@1":
            hits = sum(
                1 for sid in eval_ids
                if preds[sid] and preds[sid][0][0] in set(gold[sid])
            )
            return hits / len(eval_ids)
        elif metric == "mrr":
            total = 0.0
            for sid in eval_ids:
                gset = set(gold[sid])
                for rank, (cid, _) in enumerate(preds[sid], 1):
                    if cid in gset:
                        total += 1.0 / rank
                        break
            return total / len(eval_ids)
        raise ValueError(metric)

    best = score(weights)
    print(f"baseline weights → {metric}={best:.4f}")
    for r in range(rounds):
        improved = False
        for key in ["nn", "ee", "ech", "ne", "ee", "nq", "np", "en", "eq", "ep"]:
            base = weights[key]
            best_v = base
            for v in grid:
                if v == base:
                    continue
                weights[key] = v
                s = score(weights)
                if s > best + 1e-4:
                    best = s
                    best_v = v
                    improved = True
                    print(f"  round {r} {key}={v} → {metric}={s:.4f}")
            weights[key] = best_v
        if not improved:
            print(f"converged after round {r}")
            break
    return weights, best
