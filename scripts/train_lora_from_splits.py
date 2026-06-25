#!/usr/bin/env python3
"""Reproduce the bundled SapBERT-LoRA adapters from the bundled training splits.

This is the script that makes capability 2 (the SSO/KO -> ModelSEED reaction
Pipeline) **fully reproducible from a clone** — no maintainer hand-off needed.

Everything it consumes ships in the repo:
  - training pairs:   data/splits/{sso,ko}_C.json   (Split-C train/val/test)
  - source labels:    data/splits/{sso,ko}_meta.json (id -> "Name (EC ...)")
  - target texts:     data/modelseed_corpus/         (ModelSEED reactions)
  - base encoder:     weights/sapbert/               (download_models.py)

It writes the same adapter layout the runtime loads:
  weights/lora/{sso,ko}/lora_adapter/   + train_config.json + val_metrics.json

Recipe (frozen to match the shipped v1.x adapters — see
weights/lora/{dir}/train_config.json):
  base   = cambridgeltl/SapBERT-from-PubMedBERT-fulltext
  LoRA   = r16, alpha32, dropout0.05, target_modules [query,key,value,dense]
  train  = MultipleNegativesRankingLoss, lr 2e-5, batch 64, 3 epochs, seed 17
  split  = C (EC-3-disjoint held-out)

Usage:
  python scripts/train_lora_from_splits.py                 # both sso + ko
  python scripts/train_lora_from_splits.py --direction sso # one direction
  python scripts/train_lora_from_splits.py --evaluate      # + held-out hit@K

Takes ~3-6 min/direction on 1x H100, ~30-60 min on CPU.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPLITS_DIR = REPO_ROOT / "data" / "splits"
LORA_DIR = REPO_ROOT / "weights" / "lora"
SAPBERT_DIR = REPO_ROOT / "weights" / "sapbert"
BASE_MODEL_ID = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext"

# Frozen recipe — mirrors the shipped adapters' train_config.json.
RECIPE = dict(
    r=16,
    alpha=32,
    dropout=0.05,
    target_modules=["query", "key", "value", "dense"],
    lr=2e-5,
    batch_size=64,
    epochs=3,
    warmup_ratio=0.1,
    seed=17,
    split="C",
)


def _load_split(direction: str) -> dict:
    p = SPLITS_DIR / f"{direction}_C.json"
    if not p.exists():
        raise SystemExit(
            f"FATAL: {p} not found. The training splits ship in data/splits/; "
            f"a partial clone is missing them. See SETUP_ASSETS.md."
        )
    return json.loads(p.read_text())


def _load_labels(direction: str) -> dict[str, str]:
    p = SPLITS_DIR / f"{direction}_meta.json"
    if not p.exists():
        raise SystemExit(f"FATAL: {p} not found (source labels). See SETUP_ASSETS.md.")
    return json.loads(p.read_text()).get("labels", {})


def _build_target_texts() -> dict[str, str]:
    """Render the candidate text for every ModelSEED reaction (NAME + EC axis)."""
    sys.path.insert(0, str(REPO_ROOT / "ontomap" / "_helpers"))
    from ontomap_lib import data as omdata  # type: ignore
    from ontomap_lib.multi_axis import render_target_axes  # type: ignore

    rxn = omdata.load_modelseed_reactions()
    rxn_ecs = omdata.load_modelseed_reaction_ecs()
    rxn_paths = omdata.load_modelseed_reaction_pathways()
    rxn_names = omdata.load_modelseed_reaction_names()
    out: dict[str, str] = {}
    for rid, row in rxn.items():
        ax = render_target_axes(row, rxn_ecs.get(rid), rxn_paths.get(rid), rxn_names.get(rid))
        out[rid] = f"{ax['NAME']} | EC {ax['EC']}"
    return out


def train_direction(direction: str, evaluate: bool) -> None:
    print(f"\n{'=' * 60}\n  Training {direction.upper()} LoRA (Split-{RECIPE['split']})\n{'=' * 60}")

    if not SAPBERT_DIR.exists():
        raise SystemExit(
            f"FATAL: {SAPBERT_DIR} not found. Run `python scripts/download_models.py` first."
        )

    split = _load_split(direction)
    labels = _load_labels(direction)
    tgt_text = _build_target_texts()
    print(f"  {len(tgt_text):,} ModelSEED reaction texts indexed")

    # Build (anchor=source label, positive=reaction text) examples.
    train_examples, missing_src, missing_tgt = [], 0, 0
    for sid, rid in split["train"]:
        src = labels.get(sid)
        if not src:
            missing_src += 1
            continue
        tgt = tgt_text.get(rid)
        if not tgt:
            missing_tgt += 1
            continue
        train_examples.append({"anchor": src, "positive": tgt})
    print(
        f"  {len(train_examples):,} train pairs "
        f"({missing_src} missing source label, {missing_tgt} missing target text)"
    )
    if not train_examples:
        raise SystemExit("FATAL: no usable training pairs.")

    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model
    from sentence_transformers import SentenceTransformer, losses
    from sentence_transformers.trainer import SentenceTransformerTrainer
    from sentence_transformers.training_args import SentenceTransformerTrainingArguments

    print(f"\n  loading base encoder from {SAPBERT_DIR}")
    model = SentenceTransformer(str(SAPBERT_DIR))
    bert = model._first_module().auto_model
    lora_cfg = LoraConfig(
        r=RECIPE["r"],
        lora_alpha=RECIPE["alpha"],
        lora_dropout=RECIPE["dropout"],
        target_modules=RECIPE["target_modules"],
        bias="none",
        task_type="FEATURE_EXTRACTION",
    )
    peft_model = get_peft_model(bert, lora_cfg)
    model._first_module().auto_model = peft_model
    n_train = sum(p.numel() for p in peft_model.parameters() if p.requires_grad)
    n_total = sum(p.numel() for p in peft_model.parameters())
    print(f"  trainable params: {n_train:,} / {n_total:,} ({n_train / n_total * 100:.2f}%)")

    train_ds = Dataset.from_list(train_examples)
    loss = losses.MultipleNegativesRankingLoss(model)

    out_parent = LORA_DIR / direction
    out_adapter = out_parent / "lora_adapter"
    out_adapter.mkdir(parents=True, exist_ok=True)

    args = SentenceTransformerTrainingArguments(
        output_dir=str(out_parent / "_trainer_tmp"),
        num_train_epochs=RECIPE["epochs"],
        per_device_train_batch_size=RECIPE["batch_size"],
        learning_rate=RECIPE["lr"],
        warmup_ratio=RECIPE["warmup_ratio"],
        bf16=torch.cuda.is_available(),
        save_strategy="no",
        logging_steps=50,
        seed=RECIPE["seed"],
        report_to=[],
    )
    trainer = SentenceTransformerTrainer(model=model, args=args, train_dataset=train_ds, loss=loss)
    print("\n  training …")
    t0 = time.time()
    trainer.train()
    train_s = time.time() - t0
    print(f"  trained in {train_s:.1f}s")

    # Save adapter + tokenizer (runtime loads tokenizer from the adapter dir).
    peft_model.save_pretrained(str(out_adapter))
    model._first_module().tokenizer.save_pretrained(str(out_adapter))
    print(f"  ✓ adapter saved to {out_adapter}")

    # Record the exact recipe so the artifact is self-documenting.
    (out_parent / "train_config.json").write_text(
        json.dumps(
            {
                "direction": direction,
                "split": RECIPE["split"],
                "epochs": RECIPE["epochs"],
                "batch_size": RECIPE["batch_size"],
                "lr": RECIPE["lr"],
                "seed": RECIPE["seed"],
                "base_model": BASE_MODEL_ID,
                "lora": {
                    "r": RECIPE["r"],
                    "alpha": RECIPE["alpha"],
                    "dropout": RECIPE["dropout"],
                    "target_modules": RECIPE["target_modules"],
                },
                "n_train": len(train_examples),
                "reproduced_by": "scripts/train_lora_from_splits.py",
                "train_seconds": round(train_s, 1),
            },
            indent=2,
        )
    )

    if evaluate:
        _evaluate(direction, model, split, labels, tgt_text, out_parent)

    # clean trainer tmp
    import shutil

    shutil.rmtree(out_parent / "_trainer_tmp", ignore_errors=True)


def _evaluate(direction, model, split, labels, tgt_text, out_parent) -> None:
    print("\n  evaluating on held-out test fold (cosine retrieval over full corpus) …")
    import numpy as np

    test_pairs = [(labels.get(s, s), r) for s, r in split["test"] if labels.get(s)]
    if not test_pairs:
        print("  (no test pairs)")
        return
    target_ids = list(tgt_text.keys())
    target_texts = [tgt_text[t] for t in target_ids]
    src_emb = model.encode(
        [s for s, _ in test_pairs], batch_size=256, normalize_embeddings=True, convert_to_numpy=True
    )
    tgt_emb = model.encode(
        target_texts, batch_size=256, normalize_embeddings=True, convert_to_numpy=True
    )
    sims = src_emb @ tgt_emb.T
    hits = {1: 0, 5: 0, 10: 0}
    mrr = 0.0
    for i, (_, gold) in enumerate(test_pairs):
        order = np.argsort(-sims[i])[:100]
        for rank, idx in enumerate(order, start=1):
            if target_ids[idx] == gold:
                for K in hits:
                    if rank <= K:
                        hits[K] += 1
                mrr += 1.0 / rank
                break
    n = len(test_pairs)
    metrics = {
        f"test_{direction}_cosine_accuracy@1": hits[1] / n,
        f"test_{direction}_cosine_accuracy@5": hits[5] / n,
        f"test_{direction}_cosine_accuracy@10": hits[10] / n,
        f"test_{direction}_cosine_mrr@100": mrr / n,
        "n_test": n,
    }
    print(
        f"  hit@1={hits[1] / n:.4f}  hit@5={hits[5] / n:.4f}  "
        f"hit@10={hits[10] / n:.4f}  MRR={mrr / n:.4f}  (n={n})"
    )
    (out_parent / "val_metrics.json").write_text(json.dumps(metrics, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--direction",
        choices=["sso", "ko", "both"],
        default="both",
        help="which adapter(s) to (re)train (default: both)",
    )
    ap.add_argument(
        "--evaluate",
        action="store_true",
        help="also score the held-out test fold (hit@1/5/10 + MRR) after training",
    )
    args = ap.parse_args()

    directions = ["sso", "ko"] if args.direction == "both" else [args.direction]
    for d in directions:
        train_direction(d, args.evaluate)

    print(
        "\n✓ Done. Verify with:\n"
        "    ontomap info\n"
        "    ontomap map --text 'Enoyl-CoA hydratase (EC 4.2.1.17)'"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
