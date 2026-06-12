"""Phase 4 — evaluate every (direction, split) cell.

Workflow per cell:
  1. Load LoRA adapter, embed test-fold sources and the full ModelSEED
     reaction universe (NAME + EC axes only — EQUATION + PATHWAY axes use
     the cached base SapBERT embeddings since the LoRA was only trained on
     NAME and EC pairs).
  2. Run multi-axis re-rank with the *frozen* swept weights from
     workspace/01_multi_axis_embeddings/outputs/reports/sapbert_swept.json.
  3. Compute hits@{1,5,10,20}, MRR, Bpref, EC-soft@10.
  4. Re-run the same pipeline with the *baseline* (no-LoRA) NAME/EC
     embeddings to score the head-to-head on the same test fold.
  5. Bootstrap 1000-resample 95% CI on Δhits@10. One-sided p-value (LoRA>baseline).

Outputs:
  outputs/tables/17_eval_by_split.csv
  outputs/tables/17_per_query_{direction}_{split}.jsonl
  outputs/reports/17_eval_details.json
"""

from __future__ import annotations

import csv
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

# Bundled ontomap_lib (formerly the project's `src/ontomap` library, now
# vendored under `ontomap/_helpers/ontomap_lib/`) is added to sys.path by
# `ontomap/_helpers/__init__.py`. Importing under the renamed namespace
# avoids the name collision with the outer `ontomap` distribution package.
from ontomap_lib import data as omdata  # type: ignore
from ontomap_lib.multi_axis import (  # type: ignore
    render_source_axes,
    render_target_axes,
    ec_hierarchy_match,
)
from ontomap_lib.evaluate import score_one_query  # type: ignore
from ontomap_lib.incomplete_gold_eval import bpref, soft_hit_at_k_ec  # type: ignore


ROOT = Path("/scratch/vsetlur/ontology-mapping")
STEP = ROOT / "workspace/17_sapbert_lora"
ADAPTERS = STEP / "outputs/adapters"
EMB_BASE = ROOT / "data/embeddings/multi_axis_sapbert"

SWEPT = json.loads(
    (ROOT / "workspace/01_multi_axis_embeddings/outputs/reports/sapbert_swept.json").read_text()
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _l2_normalize(arr: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(arr, axis=-1, keepdims=True)
    n[n == 0] = 1.0
    return arr / n


def encode_with_model(model, texts: list[str], batch_size: int = 256) -> np.ndarray:
    embs = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return embs.astype("float32")


def build_corpus_text():
    """Return aligned (rxn_ids, name_texts, ec_texts, eq_texts, pw_texts, ecs_raw)."""
    reactions = omdata.load_modelseed_reactions()
    rxn_ecs = omdata.load_modelseed_reaction_ecs()
    rxn_paths = omdata.load_modelseed_reaction_pathways()
    rxn_names = omdata.load_modelseed_reaction_names()

    ids: list[str] = []
    name_texts: list[str] = []
    ec_texts: list[str] = []
    eq_texts: list[str] = []
    pw_texts: list[str] = []
    ecs_raw: list[list[str]] = []
    for rid, row in reactions.items():
        if row.get("is_obsolete") in ("1", "true", "True"):
            continue
        rendered = render_target_axes(
            row, rxn_ecs.get(rid), rxn_paths.get(rid), rxn_names.get(rid)
        )
        ids.append(rid)
        name_texts.append(rendered["NAME"] or rid)
        ec_texts.append(rendered["EC"] or rendered["NAME"] or rid)
        eq_texts.append(rendered["EQUATION"] or rendered["NAME"] or rid)
        pw_texts.append(rendered["PATHWAY"] or rendered["NAME"] or rid)
        ecs_raw.append(rendered["_ecs_raw"])
    return ids, name_texts, ec_texts, eq_texts, pw_texts, ecs_raw


def load_base_cache():
    """Load (corpus_ids, name_emb, ec_emb, eq_emb, pw_emb, ecs_raw) from the
    cached base SapBERT multi-axis embeddings."""
    arr = np.load(EMB_BASE / "target_sapbert.npz")
    ids = arr["ids"].tolist()
    name = arr["name_emb"]
    ec = arr["ec_emb"]
    eq = arr["eq_emb"]
    pw = arr["pw_emb"]
    ecs_raw_strings = arr["ecs_raw"].tolist()
    ecs_raw = [s.split(";") if s else [] for s in ecs_raw_strings]
    return ids, name, ec, eq, pw, ecs_raw


def build_corpus_ecs_raw_from_disk(corpus_ids: list[str]) -> list[list[str]]:
    """ECs per reaction from the live data, aligned to a given corpus_ids order."""
    rxn_ecs = omdata.load_modelseed_reaction_ecs()
    reactions = omdata.load_modelseed_reactions()
    out: list[list[str]] = []
    for rid in corpus_ids:
        row = reactions.get(rid, {})
        inline = omdata.parse_ec_from_text(row.get("ec_numbers") or "")
        alias = rxn_ecs.get(rid, [])
        out.append(list(dict.fromkeys(inline + alias)))
    return out


def encode_corpus_lora(model_lora, corpus_text, base_arrays):
    """Use LoRA only for NAME and EC axes; reuse cached base embeddings for
    EQUATION + PATHWAY (the LoRA wasn't trained on these axes)."""
    ids, name_texts, ec_texts, _eq_texts, _pw_texts, ecs_raw = corpus_text
    base_ids, base_name, base_ec, base_eq, base_pw, _base_ecs = base_arrays
    assert ids == base_ids, "Corpus order mismatch between live render and cache"
    name_emb = encode_with_model(model_lora, name_texts)
    ec_emb = encode_with_model(model_lora, ec_texts)
    return name_emb, ec_emb, base_eq, base_pw, ecs_raw


def encode_sources(model, src_ids: list[str], src_labels: dict[str, str]):
    name_texts, ec_texts, ecs_raw = [], [], []
    for sid in src_ids:
        ax = render_source_axes(src_labels.get(sid, sid))
        name_texts.append(ax["NAME"] or sid)
        ec_texts.append(ax["EC"] or ax["NAME"] or sid)
        ecs_raw.append(ax["_ecs_raw"])
    name_emb = encode_with_model(model, name_texts)
    ec_emb = encode_with_model(model, ec_texts)
    return name_emb, ec_emb, ecs_raw


def multi_axis_score(
    src_name, src_ec, src_ecs_raw,
    cand_idx,
    tgt_name, tgt_ec, tgt_eq, tgt_pw,
    tgt_ecs_raw, weights,
) -> np.ndarray:
    t_name = tgt_name[cand_idx]
    t_ec = tgt_ec[cand_idx]
    t_eq = tgt_eq[cand_idx]
    t_pw = tgt_pw[cand_idx]

    s_nn = t_name @ src_name
    s_ne = t_ec @ src_name
    s_nq = t_eq @ src_name
    s_np = t_pw @ src_name
    s_en = t_name @ src_ec
    s_ee = t_ec @ src_ec
    s_eq = t_eq @ src_ec
    s_ep = t_pw @ src_ec

    score = (
        weights["nn"] * s_nn + weights["ne"] * s_ne + weights["nq"] * s_nq +
        weights["np"] * s_np + weights["en"] * s_en + weights["ee"] * s_ee +
        weights["eq"] * s_eq + weights["ep"] * s_ep
    )
    if weights.get("ech", 0) and src_ecs_raw:
        ec_terms = np.array([
            ec_hierarchy_match(src_ecs_raw, tgt_ecs_raw[i])
            for i in cand_idx
        ], dtype=np.float32)
        score = score + weights["ech"] * ec_terms
    return score


def run_one_pipeline(
    src_name, src_ec, src_ecs_list,
    tgt_name, tgt_ec, tgt_eq, tgt_pw,
    tgt_ecs_raw, corpus_ids,
    weights,
    top_k_retrieve: int = 100,
    top_k_out: int = 20,
):
    """Run multi-axis retrieve+rerank for a batch of sources.
    Returns list of [(rxn_id, score), ...] per source.
    """
    import faiss

    dim = tgt_name.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(tgt_name)
    _, cand_idx = index.search(src_name, top_k_retrieve)
    out: list[list[tuple[str, float]]] = []
    for i in range(src_name.shape[0]):
        ci = cand_idx[i]
        scores = multi_axis_score(
            src_name[i], src_ec[i], src_ecs_list[i],
            ci,
            tgt_name, tgt_ec, tgt_eq, tgt_pw,
            tgt_ecs_raw, weights,
        )
        order = np.argsort(-scores)[:top_k_out]
        out.append([(corpus_ids[int(ci[int(o)])], float(scores[int(o)])) for o in order])
    return out


def load_lora_model(adapter_dir: Path):
    """Load SapBERT + a fine-tuned LoRA adapter from disk."""
    from peft import PeftModel
    from sentence_transformers import SentenceTransformer
    base = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext"
    model = SentenceTransformer(base)
    bert = model._first_module().auto_model
    adapter_path = adapter_dir / "lora_adapter"
    peft_model = PeftModel.from_pretrained(bert, str(adapter_path))
    peft_model.eval()
    model._first_module().auto_model = peft_model
    return model


def load_base_model():
    from sentence_transformers import SentenceTransformer
    base = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext"
    model = SentenceTransformer(base)
    return model


def bootstrap_ci(
    per_query_lora: list[int],
    per_query_base: list[int],
    n_boot: int = 1000,
    seed: int = 17,
) -> tuple[float, float, float, float]:
    """Bootstrap 95% CI on (mean_lora - mean_base) and one-sided p-value (LoRA>base).
    Returns (delta, ci_low, ci_high, p_value).
    """
    rng = np.random.default_rng(seed)
    a = np.array(per_query_lora, dtype=np.float32)
    b = np.array(per_query_base, dtype=np.float32)
    n = len(a)
    delta = float(a.mean() - b.mean())
    deltas = np.zeros(n_boot, dtype=np.float32)
    for i in range(n_boot):
        idx = rng.integers(0, n, n)
        deltas[i] = a[idx].mean() - b[idx].mean()
    lo, hi = np.percentile(deltas, [2.5, 97.5])
    # one-sided p: P(delta <= 0)
    p = float(np.mean(deltas <= 0))
    return delta, float(lo), float(hi), p


def evaluate_cell(
    direction: str,
    split: str,
    base_arrays,
    corpus_text,
) -> dict:
    logging.info("--- Eval cell %s split %s ---", direction, split)
    weights = SWEPT[f"{direction}_swept_weights"]

    splits = json.loads((STEP / f"data/splits/{direction}_{split}.json").read_text())
    meta = json.loads((STEP / f"data/splits/{direction}_meta.json").read_text())
    src_labels = meta["labels"]

    # Test fold gold: aggregate gold rxn list per source from EVERY fold,
    # so partial credit isn't penalised against a single test pair.
    full_gold: dict[str, set[str]] = defaultdict(set)
    for fold in ("train", "val", "test"):
        for s, r in splits[fold]:
            full_gold[s].add(r)
    test_src = sorted({s for s, _ in splits["test"]})
    # Gold per test source = union of every rxn this source has in any fold
    gold_per_src = {s: sorted(full_gold[s]) for s in test_src}
    # Per-source EC list (from rxn ECs) for EC-soft@10
    corpus_ids, _, _, _, _, ecs_raw = corpus_text
    rid_to_pos = {rid: i for i, rid in enumerate(corpus_ids)}
    gold_ecs_union: dict[str, list[str]] = {}
    for s, rxns in gold_per_src.items():
        ec_union = []
        for r in rxns:
            pos = rid_to_pos.get(r)
            if pos is not None:
                ec_union.extend(ecs_raw[pos])
        gold_ecs_union[s] = list(dict.fromkeys(ec_union))
    # Candidate ECs map (per rxn)
    cand_ecs = {rid: ecs_raw[i] for i, rid in enumerate(corpus_ids)}
    # Non-relevant set for bpref: every rxn NOT in this source's full gold
    # (drawn implicitly from the retrieved ranking; we just need the gold set).

    # ---- Baseline (cached SapBERT) ----
    base_ids, base_name, base_ec, base_eq, base_pw, base_ecs_raw = base_arrays
    # base_ecs_raw came from .npz; use the live ones (more reliable):
    tgt_ecs_raw = ecs_raw

    src_name_base = []
    src_ec_base = []
    src_ecs_list = []
    # base source embeddings from cache
    arr = np.load(EMB_BASE / f"{direction}_source_sapbert.npz")
    src_cache_ids = arr["ids"].tolist()
    src_to_pos = {sid: i for i, sid in enumerate(src_cache_ids)}
    base_src_name_full = arr["name_emb"]
    base_src_ec_full = arr["ec_emb"]
    ecs_raw_src_full = [s.split(";") if s else [] for s in arr["ecs_raw"].tolist()]
    for sid in test_src:
        pos = src_to_pos.get(sid)
        if pos is None:
            src_name_base.append(np.zeros(base_src_name_full.shape[1], dtype=np.float32))
            src_ec_base.append(np.zeros(base_src_ec_full.shape[1], dtype=np.float32))
            src_ecs_list.append([])
        else:
            src_name_base.append(base_src_name_full[pos])
            src_ec_base.append(base_src_ec_full[pos])
            src_ecs_list.append(ecs_raw_src_full[pos])
    src_name_base = np.stack(src_name_base).astype("float32")
    src_ec_base = np.stack(src_ec_base).astype("float32")

    logging.info("Running baseline pipeline for %d test sources...", len(test_src))
    base_results = run_one_pipeline(
        src_name_base, src_ec_base, src_ecs_list,
        base_name, base_ec, base_eq, base_pw,
        tgt_ecs_raw, corpus_ids, weights,
    )

    # ---- LoRA ----
    adapter_dir = ADAPTERS / f"sapbert-lora-{direction}-split{split}"
    logging.info("Loading LoRA from %s", adapter_dir)
    model_lora = load_lora_model(adapter_dir)
    # Sources (LoRA encodes test sources only)
    src_name_lora, src_ec_lora, src_ecs_list_lora = encode_sources(
        model_lora, test_src, src_labels,
    )
    # Corpus NAME + EC under LoRA; EQUATION + PATHWAY reuse base cache
    logging.info("Embedding full ModelSEED corpus under LoRA (NAME + EC)...")
    tgt_name_lora, tgt_ec_lora, tgt_eq_lora, tgt_pw_lora, _ = encode_corpus_lora(
        model_lora, corpus_text, base_arrays,
    )
    lora_results = run_one_pipeline(
        src_name_lora, src_ec_lora, src_ecs_list_lora,
        tgt_name_lora, tgt_ec_lora, tgt_eq_lora, tgt_pw_lora,
        tgt_ecs_raw, corpus_ids, weights,
    )

    # ---- Score both ----
    rows = []
    per_q_hits10 = {"base": [], "lora": []}
    out_lines = []
    for i, sid in enumerate(test_src):
        gold = gold_per_src[sid]
        ec_union = gold_ecs_union.get(sid, [])

        base_ret = [r for r, _ in base_results[i]]
        lora_ret = [r for r, _ in lora_results[i]]

        b = score_one_query(base_ret, gold)
        l = score_one_query(lora_ret, gold)
        # Bpref: relevant = gold, non-relevant = anything in top-K that isn't gold
        b["bpref"] = bpref(base_ret, set(gold), set(base_ret) - set(gold))
        l["bpref"] = bpref(lora_ret, set(gold), set(lora_ret) - set(gold))
        b["ec_soft@10"] = soft_hit_at_k_ec(
            base_ret, gold, 10, cand_ecs, ec_union, ec_hierarchy_match,
        )
        l["ec_soft@10"] = soft_hit_at_k_ec(
            lora_ret, gold, 10, cand_ecs, ec_union, ec_hierarchy_match,
        )
        per_q_hits10["base"].append(b["hits@10"])
        per_q_hits10["lora"].append(l["hits@10"])

        out_lines.append(json.dumps({
            "src": sid,
            "gold": gold,
            "base_top20": base_ret,
            "lora_top20": lora_ret,
            "base_metrics": b,
            "lora_metrics": l,
        }))

    per_q_path = STEP / f"outputs/tables/17_per_query_{direction}_{split}.jsonl"
    per_q_path.parent.mkdir(parents=True, exist_ok=True)
    per_q_path.write_text("\n".join(out_lines))

    # Aggregate
    def agg(keyname: str) -> dict[str, float]:
        n = max(len(out_lines), 1)
        keys = ("hits@1", "hits@5", "hits@10", "hits@20", "mrr", "bpref", "ec_soft@10")
        rec = {}
        for k in keys:
            v = 0.0
            for line in out_lines:
                rec_q = json.loads(line)[f"{keyname}_metrics"]
                v += rec_q[k]
            rec[k] = v / n
        return rec

    base_agg = agg("base")
    lora_agg = agg("lora")
    delta, lo, hi, p = bootstrap_ci(per_q_hits10["lora"], per_q_hits10["base"])

    cell = {
        "direction": direction,
        "split": split,
        "n_test": len(test_src),
        "baseline": base_agg,
        "lora": lora_agg,
        "delta_hits10": delta,
        "ci_low": lo,
        "ci_high": hi,
        "p_value": p,
    }
    logging.info(
        "%s %s: base hits@10=%.4f, lora hits@10=%.4f, delta=%.4f [%.4f, %.4f], p=%.3f",
        direction, split,
        base_agg["hits@10"], lora_agg["hits@10"],
        delta, lo, hi, p,
    )
    return cell


def write_csv(cells: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "direction", "split", "n_test", "model",
        "hits@1", "hits@5", "hits@10", "hits@20",
        "mrr", "bpref", "ec_soft@10",
        "delta_hits10_vs_baseline", "ci_low", "ci_high", "p_value",
    ]
    rows = []
    for c in cells:
        for tag in ("baseline", "lora"):
            row = {
                "direction": c["direction"],
                "split": c["split"],
                "n_test": c["n_test"],
                "model": tag,
            }
            for k in ("hits@1", "hits@5", "hits@10", "hits@20", "mrr", "bpref", "ec_soft@10"):
                row[k] = round(c[tag][k], 4)
            if tag == "lora":
                row["delta_hits10_vs_baseline"] = round(c["delta_hits10"], 4)
                row["ci_low"] = round(c["ci_low"], 4)
                row["ci_high"] = round(c["ci_high"], 4)
                row["p_value"] = round(c["p_value"], 4)
            else:
                row["delta_hits10_vs_baseline"] = ""
                row["ci_low"] = ""
                row["ci_high"] = ""
                row["p_value"] = ""
            rows.append(row)
    with out_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    logging.info("Loading ModelSEED corpus text + cached base embeddings...")
    corpus_text = build_corpus_text()
    base_arrays = load_base_cache()
    assert corpus_text[0] == base_arrays[0], "Corpus ID mismatch — re-cache."

    cells = []
    for direction in ("sso", "ko"):
        for split in ("A", "B", "C"):
            cell = evaluate_cell(direction, split, base_arrays, corpus_text)
            cells.append(cell)

    out_csv = STEP / "outputs/tables/17_eval_by_split.csv"
    write_csv(cells, out_csv)
    logging.info("Wrote %s", out_csv)
    (STEP / "outputs/reports/17_eval_details.json").write_text(
        json.dumps(cells, indent=2)
    )


if __name__ == "__main__":
    main()
