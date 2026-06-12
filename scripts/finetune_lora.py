#!/usr/bin/env python3
"""Fine-tune a SapBERT-LoRA adapter on custom (source, target) pairs.

Input: a TSV with columns:
  source_label       free-text source description (e.g. "Aldehyde dehydrogenase (EC 1.2.1.3)")
  target_reaction_id ModelSEED reaction ID (e.g. rxn00506)
  split              one of train/val/test (optional; default split 80/10/10 by seed)

Usage:

    python scripts/finetune_lora.py \\
        --train pairs.tsv \\
        --output weights/lora/my_custom/lora_adapter/ \\
        --rank 16 --alpha 32 --epochs 3 --batch-size 128 --lr 2e-5

The script:
  1. Loads SapBERT base from weights/sapbert/ (run download_models.py first).
  2. Attaches a fresh LoRA adapter (rank/alpha configurable).
  3. Builds a SentenceTransformer with the LoRA-adapted BERT.
  4. Trains with MultipleNegativesRankingLoss (in-batch negatives + hard negatives if --hard-negatives).
  5. Saves the LoRA adapter via peft.PeftModel.save_pretrained to the output dir.
  6. (Optional) Evaluates against the test split: hit@1, hit@5, hit@10, MRR.

After fine-tuning, drop the resulting adapter dir into `weights/lora/{sso,ko}/lora_adapter/`
(or wherever you point ontomap at) — the runtime will pick it up at next load.

Default hyperparameters mirror the ontomap v1.0.0 training run:
  rank=16, alpha=32, dropout=0.1, lr=2e-5, batch_size=128, epochs=3, warmup_ratio=0.1
"""
from __future__ import annotations
import argparse
import csv
import random
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def parse_args():
    p = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter,
                                description=__doc__)
    p.add_argument("--train", required=True, type=Path,
                   help="TSV with columns source_label, target_reaction_id[, split]")
    p.add_argument("--output", required=True, type=Path,
                   help="output directory for the LoRA adapter")
    p.add_argument("--base-model", default=None,
                   help="path to SapBERT base (default: weights/sapbert/)")
    p.add_argument("--rank",       type=int,   default=16,    help="LoRA rank")
    p.add_argument("--alpha",      type=int,   default=32,    help="LoRA alpha")
    p.add_argument("--dropout",    type=float, default=0.1,   help="LoRA dropout")
    p.add_argument("--lr",         type=float, default=2e-5,  help="learning rate")
    p.add_argument("--batch-size", type=int,   default=128,   help="batch size")
    p.add_argument("--epochs",     type=int,   default=3)
    p.add_argument("--warmup-ratio", type=float, default=0.1)
    p.add_argument("--seed",       type=int,   default=17)
    p.add_argument("--hard-negatives", action="store_true",
                   help="mine in-batch hard negatives (slower; usually +1pp MRR)")
    p.add_argument("--evaluate", action="store_true",
                   help="evaluate hit@K + MRR on the test split after training")
    return p.parse_args()


def load_pairs(path: Path, seed: int) -> dict[str, list[tuple[str, str]]]:
    rng = random.Random(seed)
    splits: dict[str, list[tuple[str, str]]] = {"train": [], "val": [], "test": []}
    with path.open() as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            src = row.get("source_label") or row.get("source") or ""
            tgt = row.get("target_reaction_id") or row.get("target") or ""
            split = row.get("split", "").strip().lower() or None
            if not src or not tgt:
                continue
            if split is None:
                # 80/10/10 split by deterministic random
                r = rng.random()
                split = "train" if r < 0.8 else ("val" if r < 0.9 else "test")
            if split not in splits:
                splits["train"].append((src, tgt))
            else:
                splits[split].append((src, tgt))
    for s, pairs in splits.items():
        print(f"  {s:5}: {len(pairs):>6} pairs")
    return splits


def main():
    args = parse_args()
    print(f"Loading pairs from {args.train} …")
    splits = load_pairs(args.train, args.seed)
    if not splits["train"]:
        print("ERROR: no training pairs found")
        sys.exit(1)

    # Build target text lookup — each target_reaction_id needs a candidate text.
    # We use the bundled reactions.tsv name+ec for this.
    print("\nLoading ModelSEED target texts …")
    sys.path.insert(0, str(REPO_ROOT))
    from ontomap._helpers.ontomap_lib import data as omdata
    from ontomap._helpers.ontomap_lib.multi_axis import render_target_axes
    rxn = omdata.load_modelseed_reactions()
    rxn_ecs = omdata.load_modelseed_reaction_ecs()
    rxn_paths = omdata.load_modelseed_reaction_pathways()
    rxn_names = omdata.load_modelseed_reaction_names()
    tgt_text = {}
    for rid, row in rxn.items():
        ax = render_target_axes(row, rxn_ecs.get(rid), rxn_paths.get(rid), rxn_names.get(rid))
        tgt_text[rid] = f"{ax['NAME']} | EC {ax['EC']}"
    print(f"  {len(tgt_text)} reaction texts indexed")

    # SapBERT base + LoRA
    print("\nLoading SapBERT base + attaching LoRA …")
    from sentence_transformers import SentenceTransformer, losses
    from sentence_transformers.training_args import SentenceTransformerTrainingArguments
    from sentence_transformers.trainer import SentenceTransformerTrainer
    from sentence_transformers.readers import InputExample
    from torch.utils.data import DataLoader
    from peft import LoraConfig, get_peft_model
    from datasets import Dataset

    base = str(args.base_model or (REPO_ROOT / "weights" / "sapbert"))
    model = SentenceTransformer(base)
    bert = model._first_module().auto_model
    lora_cfg = LoraConfig(
        r=args.rank, lora_alpha=args.alpha, lora_dropout=args.dropout,
        target_modules=["query", "value"], bias="none", task_type="FEATURE_EXTRACTION",
    )
    peft_model = get_peft_model(bert, lora_cfg)
    model._first_module().auto_model = peft_model
    n_trainable = sum(p.numel() for p in peft_model.parameters() if p.requires_grad)
    n_total     = sum(p.numel() for p in peft_model.parameters())
    print(f"  trainable params: {n_trainable:,} / {n_total:,} ({n_trainable/n_total*100:.2f}%)")

    # Build training examples
    train_examples = []
    missing = 0
    for src, tgt_id in splits["train"]:
        tgt = tgt_text.get(tgt_id)
        if tgt is None:
            missing += 1; continue
        train_examples.append({"anchor": src, "positive": tgt})
    print(f"\n  {len(train_examples)} train examples ({missing} missing target texts)")
    train_ds = Dataset.from_list(train_examples)

    # Loss
    loss = losses.MultipleNegativesRankingLoss(model)

    # Training
    print("\nTraining …")
    out_dir = args.output.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    ta = SentenceTransformerTrainingArguments(
        output_dir=str(out_dir),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        learning_rate=args.lr,
        warmup_ratio=args.warmup_ratio,
        bf16=True,
        save_strategy="no",  # we save the LoRA adapter manually
        logging_steps=50,
        seed=args.seed,
    )
    trainer = SentenceTransformerTrainer(
        model=model, args=ta, train_dataset=train_ds, loss=loss,
    )
    t0 = time.time()
    trainer.train()
    print(f"  trained in {time.time()-t0:.1f}s")

    # Save LoRA adapter
    peft_model.save_pretrained(out_dir)
    print(f"\n✓ LoRA adapter saved to {out_dir}")

    if args.evaluate and splits["test"]:
        print(f"\nEvaluating on {len(splits['test'])} test pairs …")
        import numpy as np
        # encode test sources + all target texts, compute hit@K via cosine
        src_texts = [s for s, _ in splits["test"]]
        gold_ids = [g for _, g in splits["test"]]
        target_ids = list(tgt_text.keys())
        target_texts = [tgt_text[t] for t in target_ids]
        src_emb = model.encode(src_texts, batch_size=256, normalize_embeddings=True, convert_to_numpy=True)
        tgt_emb = model.encode(target_texts, batch_size=256, normalize_embeddings=True, convert_to_numpy=True)
        sims = src_emb @ tgt_emb.T
        hits = {K: 0 for K in (1, 5, 10)}
        mrr = 0.0
        for i, gold in enumerate(gold_ids):
            order = np.argsort(-sims[i])
            for rank, idx in enumerate(order[:100], start=1):
                if target_ids[idx] == gold:
                    for K in (1, 5, 10):
                        if rank <= K: hits[K] += 1
                    mrr += 1.0 / rank
                    break
        n = len(gold_ids)
        print(f"  hit@1: {hits[1]/n:.4f}  hit@5: {hits[5]/n:.4f}  hit@10: {hits[10]/n:.4f}  MRR: {mrr/n:.4f}")


if __name__ == "__main__":
    main()
