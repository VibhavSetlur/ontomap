# FINETUNE — how to fine-tune SapBERT-LoRA on custom data

This document explains how to reproduce the LoRA adapters bundled in
`ontomap/weights/lora/{sso,ko}/lora_adapter/` and how to train a new
adapter on your own data. The reference implementation lives at
`/scratch/vsetlur/ontology-mapping/workspace/17_sapbert_lora/scripts/`.

For what the bundled adapters were trained on, see [`DATA.md`](DATA.md).

---

## 1. Input data format

The training script
(`workspace/17_sapbert_lora/scripts/17c_train_lora.py`) does NOT consume a
single TSV/JSONL — it expects three workspace-style artefacts:

| artefact | what it contains | how to build |
|---|---|---|
| `data/splits/{direction}_meta.json` | `{labels: {src_id: source_label_str}, ec3: {src_id: ec3_or_EC_NA}, gold_size: {src_id: n}}` | `17a_build_splits.py` |
| `data/splits/{direction}_{A,B,C}.json` | `{train: [[src_id, rxn_id], ...], val: [...], test: [...]}` | `17a_build_splits.py` |
| `data/output/hard_negatives_{direction}_{A,B,C}.jsonl` | One JSON line per train pair: `{src, gold, negatives: [rxn_id × 8]}` | `17b_mine_hard_negatives.py` |

If you want to fine-tune on a **fresh dataset**, the simplest path is to
emit those three files directly. For one-off custom data the schema is
just:

**`{direction}_meta.json`**
```json
{
  "labels": {
    "MYID:0001": "phosphoribosyltransferase (EC 2.4.2.18)",
    "MYID:0002": "ribose-5-phosphate isomerase A (EC 5.3.1.6)"
  },
  "ec3":      { "MYID:0001": "2.4.2", "MYID:0002": "5.3.1" },
  "gold_size":{ "MYID:0001": 1,       "MYID:0002": 2 }
}
```

**`{direction}_{split}.json`**
```json
{
  "train": [["MYID:0001", "rxn00123"], ["MYID:0002", "rxn00456"]],
  "val":   [["MYID:0003", "rxn00789"]],
  "test":  [["MYID:0004", "rxn01000"]]
}
```

**`hard_negatives_{direction}_{split}.jsonl`** (one line per train pair):
```json
{"src": "MYID:0001", "gold": "rxn00123", "negatives": ["rxn02000","rxn02001","rxn02002","rxn02003","rxn02004","rxn02005","rxn02006","rxn02007"]}
```

The training script reads these three files; the target side is rendered
on-the-fly via `ontomap.multi_axis.render_target_axes` against the bundled
ModelSEED corpus, so every `rxn_id` must exist in
`data/modelseed_corpus/reactions.tsv`.

> Convenience: if you have a flat TSV with `source_id`, `source_label`,
> `target_reaction_id`, `target_ec` (optional, can be parsed from label),
> the easiest path is to write the 3 split JSONs above with a 5-line
> Python script, then run `17b_mine_hard_negatives.py` to get the hard
> negatives. The mining script depends on cached SapBERT embeddings from
> workspace step 01 — for custom data, either re-encode your source IDs
> with base SapBERT into the same `.npz` format
> (`{ids, name_emb, ec_emb, eq_emb, pw_emb}`), or pad negatives with
> uniform random samples and skip the cosine filter.

---

## 2. Environment

The project uses a conda environment (`ontology-mapping`) with the
pinned dependencies in `/scratch/vsetlur/ontology-mapping/environment/requirements.txt`.
The minimum the training script needs:

```bash
conda create -n ontomap-train python=3.11 -y
conda activate ontomap-train

pip install \
  "torch>=2.2"                    \
  "transformers>=4.45"            \
  "sentence-transformers>=3.0"    \
  "peft>=0.13"                    \
  "accelerate>=1.0"               \
  "datasets>=2.16"                \
  "faiss-cpu>=1.8"                \
  "numpy>=1.26"                   \
  "pandas>=2.0"
```

GPU training also needs a CUDA-enabled `torch` build:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

`ontomap` itself must be importable for `ontomap.data` and
`ontomap.multi_axis`:

```bash
cd ontomap
pip install -e .
```

---

## 3. Training script

The reference trainer is
**`/scratch/vsetlur/ontology-mapping/workspace/17_sapbert_lora/scripts/17c_train_lora.py`**.
Helper scripts:

| script | role |
|---|---|
| `17a_build_splits.py` | Build the three frozen 80/10/10 splits per direction. |
| `17b_mine_hard_negatives.py` | Mine 8 hard negatives per train pair (top-100 SapBERT pool, drop EC-3 siblings, cosine ≥ 0.4 floor). |
| `17c_train_lora.py` | Train one (direction, split) LoRA adapter. |
| `17d_evaluate.py` | Embed test sources + full ModelSEED universe under the adapter, run the swept multi-axis pipeline, compute hits@k / MRR / Bpref / EC-soft@10 + bootstrap CI. |
| `17e_figures_and_summary.py` | Write `outputs/reports/17_results_summary.md` + figures. |

End-to-end reproduce:

```bash
source /scratch/vsetlur/anaconda3/etc/profile.d/conda.sh
conda activate ontology-mapping
cd /scratch/vsetlur/ontology-mapping

python workspace/17_sapbert_lora/scripts/17a_build_splits.py
python workspace/17_sapbert_lora/scripts/17b_mine_hard_negatives.py

for d in sso ko; do
  for s in A B C; do
    CUDA_VISIBLE_DEVICES=0 \
      python workspace/17_sapbert_lora/scripts/17c_train_lora.py \
        --direction $d --split $s --epochs 3 --batch 64
  done
done

CUDA_VISIBLE_DEVICES=0 python workspace/17_sapbert_lora/scripts/17d_evaluate.py
CUDA_VISIBLE_DEVICES=0 python workspace/17_sapbert_lora/scripts/17e_figures_and_summary.py
```

For just the shipped Split-C adapters (the ones bundled in `ontomap`):

```bash
for d in sso ko; do
  CUDA_VISIBLE_DEVICES=0 \
    python workspace/17_sapbert_lora/scripts/17c_train_lora.py \
      --direction $d --split C --epochs 3 --batch 64
done
```

---

## 4. Hyperparameters (the actual values used)

Extracted from
`workspace/17_sapbert_lora/scripts/17c_train_lora.py` and the
`train_config.json` files saved alongside each adapter.

### Base model
- `cambridgeltl/SapBERT-from-PubMedBERT-fulltext` (loaded via
  `SentenceTransformer`).

### LoRA config (`peft.LoraConfig`)
| param | value |
|---|---|
| `r` (rank) | **16** |
| `lora_alpha` | **32** |
| `lora_dropout` | **0.05** |
| `target_modules` | `["query", "key", "value", "dense"]` |
| `bias` | `"none"` |
| `task_type` | `"FEATURE_EXTRACTION"` |

Trainable params ≈ **1.18 M** (~0.27% of the 437 M base, exact ratio
logged at runtime by `17c_train_lora.py:248–251`).

### Trainer
(`SentenceTransformerTrainingArguments` in `17c_train_lora.py:284–301`)
| param | value |
|---|---|
| `num_train_epochs` | **3** (flat; the plan allowed 3–5 with early stop, the run used 3 for predictable wall-clock) |
| `per_device_train_batch_size` | **64** |
| `per_device_eval_batch_size` | 64 |
| `learning_rate` | **2e-5** |
| `warmup_ratio` | **0.1** |
| `weight_decay` | **0.01** |
| `bf16` | True |
| `batch_sampler` | `BatchSamplers.NO_DUPLICATES` |
| `eval_strategy` | `"epoch"` |
| `save_strategy` | `"no"` (LoRA adapter saved manually at end) |
| `seed` | **17** |

### Loss
- **Primary loss**: `MultipleNegativesRankingLoss` (MNRL) on each row
  `[anchor=src_NAME, positive=tgt_NAME, negative_1, …, negative_7]`,
  combined with in-batch negatives via `BatchSamplers.NO_DUPLICATES`.
- **Auxiliary loss**: a second `MultipleNegativesRankingLoss` on
  `(src_EC_text, tgt_EC_text)` pairs only (no mined hard negatives — uses
  in-batch negatives). Plugged into `SentenceTransformerTrainer` via the
  multi-loss dict pattern (`{"primary": …, "aux_ec": …}`).
- Plan called for `0.3` weight on the aux loss; current code sums two MNRL
  instances equally — see `17c_train_lora.py:304–310`.

---

## 5. Wall-clock on 1× H100

From `workspace/17_sapbert_lora/README.md`:

| stage | wall-clock |
|---|---|
| SSO LoRA train (3 splits) | ~6 min |
| KO LoRA train (3 splits) | ~17 min |
| evaluation | ~3 min |
| figures + summary | ~1 min |
| **end-to-end (6-cell grid)** | **~30 min** |

A single (direction, split) cell: ~2 min for SSO Split-C
(2,834 pairs × 3 epochs), ~6 min for KO Split-C
(8,929 pairs × 3 epochs).

---

## 6. Evaluating a freshly-trained checkpoint

The reference evaluator
(`workspace/17_sapbert_lora/scripts/17d_evaluate.py`) provides two
load-helpers and an `encode_with_model` shim:

```python
# load_base_model() / load_lora_model(adapter_dir) / encode_with_model(model, texts)
# defined in workspace/17_sapbert_lora/scripts/17d_evaluate.py

from importlib.util import spec_from_file_location, module_from_spec
spec = spec_from_file_location(
    "step17_evaluate",
    "/scratch/vsetlur/ontology-mapping/workspace/17_sapbert_lora/scripts/17d_evaluate.py",
)
step17_evaluate = module_from_spec(spec); spec.loader.exec_module(step17_evaluate)

# load base SapBERT and your freshly-trained adapter
model = step17_evaluate.load_lora_model(
    Path("workspace/17_sapbert_lora/outputs/adapters/sapbert-lora-sso-splitC")
)
# encode_with_model returns L2-normalised float32 numpy
embs = step17_evaluate.encode_with_model(
    model,
    ["phosphoribosyltransferase (EC 2.4.2.18)"],
    batch_size=256,
)
```

To get the full hits@k / MRR / Bpref / EC-soft@10 / bootstrap-CI tables
against the cached zero-shot baseline, just rerun
`17d_evaluate.py` after dropping a new adapter into
`outputs/adapters/sapbert-lora-{direction}-split{A,B,C}/`. It auto-loads
every cell present and writes `outputs/tables/17_eval_by_split.csv` plus
per-query JSONL at `outputs/tables/17_per_query_{direction}_{split}.jsonl`.

---

## 7. Loading a new LoRA adapter into `ontomap`

The packaged adapters live at:

```
ontomap/weights/lora/sso/lora_adapter/    # SSO Split-C checkpoint
ontomap/weights/lora/ko/lora_adapter/     # KO  Split-C checkpoint
```

Each `lora_adapter/` is a HuggingFace **PEFT** dump containing:

```
adapter_config.json
adapter_model.safetensors
tokenizer.json
tokenizer_config.json
```

To swap in a fresh adapter, just replace the contents of one of those
folders:

```bash
# example: ship a new SSO adapter trained from workspace step 17
rm -rf ontomap/weights/lora/sso/lora_adapter
cp -r  workspace/17_sapbert_lora/outputs/adapters/sapbert-lora-sso-splitC/lora_adapter \
       ontomap/weights/lora/sso/lora_adapter

# also refresh the audit sidecars
cp workspace/17_sapbert_lora/outputs/adapters/sapbert-lora-sso-splitC/train_config.json \
   ontomap/weights/lora/sso/
cp workspace/17_sapbert_lora/outputs/adapters/sapbert-lora-sso-splitC/val_metrics.json \
   ontomap/weights/lora/sso/
```

Then regenerate the bundle manifest so `ontomap info --verify-manifest`
stays green:

```bash
# TODO: see ontomap repo's bundle script (the one that writes weights/MANIFEST.txt
#       — look for a script named something like `bundle.py` or `make_manifest.py`
#       under ontomap/scripts/ or workspace/40_/41_*/scripts/)
```

After swapping, smoke-test:

```bash
ontomap info
ontomap map --sso SSO:000000027 --top-k 5
pytest -m smoke
```

The pipeline picks the new adapter up automatically — there is no
hard-coded SHA check inside `ontomap.embed`. `ontomap info` will warn if
`adapter_config.base_model_name_or_path` does NOT match
`cambridgeltl/SapBERT-from-PubMedBERT-fulltext`.

---

## 8. Notes on domain transfer (when LoRA generalises well vs. poorly)

Based on the per-split results in
`workspace/17_sapbert_lora/outputs/reports/17_results_summary.md`:

**Generalises well to:**
- Unseen enzyme names within familiar EC sub-classes (Split-B):
  +4.3 pp (SSO) and +5.7 pp (KO) hits@10 over zero-shot SapBERT.
- Unseen EC-3 sub-classes (Split-C): +8.5 pp (SSO), +5.9 pp (KO) — both
  exceed the +1 pp adoption gate with 95% CI > 0.
- Free-text enzyme descriptions with bracketed EC numbers (because the
  EC auxiliary loss aligns the EC sub-space).

**Possible domain-transfer caveats (LoRA may help less or hurt):**
- Reactions whose **target axis** is best matched by `EQUATION` or
  `PATHWAY` rather than `NAME` / `EC`. The shipped LoRA was deliberately
  trained on NAME and EC only — the multi-axis FAISS pipeline still uses
  cached **base** SapBERT for EQUATION and PATHWAY axes during evaluation
  and inference. This is a production-faithful choice but a known under-fit
  per `conclusions.md` caveat 1.
- The pre-registered **50-sample stratified manual audit** for catastrophic
  forgetting was skipped per the step brief. The cosine-drift histogram
  (`outputs/figures/17_embedding_drift.png`) is the proxy: median
  `1 − cos(base, LoRA)` stays small, suggesting LoRA only nudges the
  manifold. A formal audit on out-of-distribution biomedical entities is
  open follow-up work — be cautious if your downstream task is not
  metabolic-reaction mapping.
- Training loss was still decreasing at epoch 3 on every cell. Reported
  Δ values are likely a **lower bound**; longer training (5+ epochs, with
  early stop on val MRR plateau) may deliver more lift.
- The adversarial KO sibling-margin loss from the plan was omitted; Split-C
  Δ on KO is still strong (+5.9 pp), but if you fine-tune on a fresh
  ontology you may want to add a sibling-margin term to reduce the false
  positive rate on EC-3 cousins.
