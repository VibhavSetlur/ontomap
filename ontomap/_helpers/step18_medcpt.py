"""Step 18 Phase 1 — score top-100 (source, candidate) pairs with MedCPT Cross-Encoder.

Loads `ncbi/MedCPT-Cross-Encoder`, builds query/candidate text via
`render_source_axes` / `render_target_axes`, batches candidates per source,
and writes per-(src, rxn) MedCPT logits to
`data/output/medcpt_scores_{sso,ko}.jsonl`.

Env:
    CUDA_VISIBLE_DEVICES=1
Run:
    python scripts/18a_medcpt_rerank.py --direction sso
    python scripts/18a_medcpt_rerank.py --direction ko
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification

# Bundled ontomap_lib (formerly the project's `src/ontomap` library) is
# added to sys.path by `ontomap/_helpers/__init__.py`. Use the renamed
# namespace to avoid colliding with the outer `ontomap` distribution.
from ontomap_lib import data
from ontomap_lib.multi_axis import render_source_axes, render_target_axes


# Original step-18 standalone-script paths (only consumed by the legacy `main()`
# entry-point further down). `_frozen_runtime.py` does not call `main()`; it
# uses `build_source_text`, `build_candidate_text`, and `score_pairs` only.
# Resolve lazily so the ontomap distributable doesn't error at import time.
_REPO_ROOT_GUESS = Path("/scratch/vsetlur/ontology-mapping")
WORKSPACE = _REPO_ROOT_GUESS / "workspace" / "18_medcpt_top100"
TOP100_DIR = _REPO_ROOT_GUESS / "workspace" / "15_ec_extraction_filter" / "outputs" / "tables"
OUT_DIR = WORKSPACE / "data" / "output"
# Skip mkdir here — the legacy main() can create it on demand. Auto-creating
# under /scratch/... on a fresh shared install would crash on permission errors.

MODEL_NAME = "ncbi/MedCPT-Cross-Encoder"


def build_source_text(direction: str, src_id: str, dict_entry: dict) -> str:
    """Render the source query text for the cross-encoder.

    Uses NAME + EC axes (joined with ' ; ') so the cross-encoder sees both the
    cleaned label and EC class hierarchy.
    """
    label = dict_entry.get("name") or src_id
    axes = render_source_axes(label)
    name_part = axes.get("NAME", "") or label
    ec_part = axes.get("EC", "")
    if ec_part:
        return f"{name_part} ; {ec_part}"
    return name_part


def build_candidate_text(
    rxn_id: str,
    reactions: dict,
    ec_map: dict,
    pw_map: dict,
    alt_names_map: dict,
) -> str:
    """Render candidate reaction text for the cross-encoder.

    Format: NAME ; EC ; EQUATION (drop pathway to keep input short).
    """
    row = reactions.get(rxn_id)
    if row is None:
        return rxn_id
    axes = render_target_axes(row, ec_map.get(rxn_id), pw_map.get(rxn_id), alt_names_map.get(rxn_id))
    name_part = axes.get("NAME", "") or rxn_id
    ec_part = axes.get("EC", "")
    eq_part = axes.get("EQUATION", "")
    parts = [name_part]
    if ec_part:
        parts.append(ec_part)
    if eq_part:
        parts.append(eq_part)
    return " ; ".join(parts)


def load_top100(direction: str) -> list[dict]:
    fn = TOP100_DIR / f"15_top100_intervention_{direction}.jsonl"
    out = []
    with fn.open() as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def score_pairs(
    model,
    tokenizer,
    device,
    query_text: str,
    cand_texts: list[str],
    max_length: int = 512,
) -> list[float]:
    """Score (query, candidate) pairs in a single batch.

    Returns a Python list of logits (one per candidate).
    """
    pairs = [[query_text, c] for c in cand_texts]
    enc = tokenizer(
        pairs,
        truncation=True,
        padding=True,
        return_tensors="pt",
        max_length=max_length,
    )
    enc = {k: v.to(device, non_blocking=True) for k, v in enc.items()}
    with torch.inference_mode():
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            out = model(**enc)
            logits = out.logits.squeeze(-1)
    return logits.float().cpu().tolist()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--direction", choices=["sso", "ko"], required=True)
    ap.add_argument("--batch-size", type=int, default=100, help="candidates per forward pass")
    ap.add_argument("--max-sources", type=int, default=0, help="optional cap for debugging")
    args = ap.parse_args()

    direction = args.direction
    t0 = time.time()
    print(f"[{direction}] loading top-100 cache + dictionaries + ModelSEED reactions ...", flush=True)
    top100 = load_top100(direction)
    print(f"[{direction}]   {len(top100)} sources loaded", flush=True)

    # source dictionary
    if direction == "sso":
        src_dict = data.load_sso_dictionary()
    else:
        # KO dict keyed as 'KO:Kxxxxxx' but top100 may use 'Kxxxxxx' — normalise
        raw = data.load_ko_dictionary()
        src_dict = {}
        for k, v in raw.items():
            short = k.split(":")[-1]
            src_dict[k] = v
            src_dict[short] = v

    # target tables (ModelSEED)
    reactions = data.load_modelseed_reactions()
    ec_map = data.load_modelseed_reaction_ecs()
    pw_map = data.load_modelseed_reaction_pathways()
    alt_names_map = data.load_modelseed_reaction_names()
    print(f"[{direction}]   {len(reactions)} reactions / {len(ec_map)} ec / "
          f"{len(pw_map)} pathway / {len(alt_names_map)} alt-names", flush=True)

    print(f"[{direction}] loading MedCPT Cross-Encoder model ...", flush=True)
    device = torch.device("cuda")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
    model = model.to(device).eval()
    print(f"[{direction}]   model on {next(model.parameters()).device}", flush=True)

    out_fn = OUT_DIR / f"medcpt_scores_{direction}.jsonl"
    print(f"[{direction}] writing scores to {out_fn}", flush=True)

    sources = top100[: args.max_sources] if args.max_sources > 0 else top100
    n_pairs = 0
    n_missing_src = 0
    n_missing_cand = 0

    with out_fn.open("w") as fout:
        for i, entry in enumerate(sources):
            src_id = entry["id"]
            cand_list = entry.get("topk", [])
            if not cand_list:
                continue

            # source text
            src_entry = src_dict.get(src_id)
            if src_entry is None:
                # try without prefix
                stripped = src_id.split(":")[-1]
                src_entry = src_dict.get(stripped)
            if src_entry is None:
                n_missing_src += 1
                query_text = src_id
            else:
                query_text = build_source_text(direction, src_id, src_entry)

            # candidate texts
            cand_texts: list[str] = []
            sapbert_scores: list[float] = []
            rxns: list[str] = []
            for c in cand_list:
                rxn_id = c["rxn"]
                ct = build_candidate_text(rxn_id, reactions, ec_map, pw_map, alt_names_map)
                if ct == rxn_id:
                    n_missing_cand += 1
                cand_texts.append(ct)
                sapbert_scores.append(float(c["score"]))
                rxns.append(rxn_id)

            # batch-score in chunks of batch_size
            medcpt_scores: list[float] = []
            for start in range(0, len(cand_texts), args.batch_size):
                chunk = cand_texts[start : start + args.batch_size]
                logits = score_pairs(model, tokenizer, device, query_text, chunk)
                medcpt_scores.extend(logits)
            n_pairs += len(cand_texts)

            # write row
            scored = [
                {"rxn": rxns[j], "sapbert": sapbert_scores[j], "medcpt": medcpt_scores[j]}
                for j in range(len(cand_texts))
            ]
            fout.write(json.dumps({"id": src_id, "query_text": query_text, "scored": scored}) + "\n")

            if (i + 1) % 200 == 0:
                elapsed = time.time() - t0
                rate = n_pairs / elapsed
                print(f"[{direction}]   {i+1}/{len(sources)} src done | "
                      f"{n_pairs:>8} pairs | {rate:6.1f} pair/s | "
                      f"elapsed {elapsed:6.1f}s", flush=True)

    elapsed = time.time() - t0
    print(f"[{direction}] DONE: {len(sources)} src, {n_pairs} pairs in {elapsed:.1f}s "
          f"(missing src dict entries: {n_missing_src}, missing rxn rows: {n_missing_cand})",
          flush=True)


if __name__ == "__main__":
    main()
