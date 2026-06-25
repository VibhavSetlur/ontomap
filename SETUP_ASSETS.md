# Setting up ontomap weights + data

**TL;DR — one command does everything:**

```bash
cd ontomap
pip install -e .
bash scripts/setup.sh     # reconstructs every asset from public sources + bundled gold inputs
ontomap info              # health-check
ontomap map --text "Enoyl-CoA hydratase (EC 4.2.1.17)"
```

After `setup.sh` finishes, **both capabilities work from a clone with no
maintainer hand-off**. This document explains what each step does, in case you
want to run them individually or regenerate one asset.

## What ships in git vs. what's regenerated

`scripts/setup.sh` is idempotent: it only fetches/builds what's missing.

| Asset | In git? | How it's obtained | Size |
|---|---|---|---|
| `weights/lora/{sso,ko}/` (trained adapters) | **yes** | committed; also reproducible (below) | ~21 MB |
| `data/dictionaries/` (SSO/KO terms + gold maps) | **yes** | committed gold inputs | ~9.5 MB |
| `data/splits/` (train/val/test pairs) | **yes** | committed; the data the LoRA is trained on | ~3.4 MB |
| `weights/swept_weights.json` | **yes** | committed (frozen step-01 weights) | tiny |
| `weights/sapbert/`, `weights/medcpt/` | no | `scripts/download_models.py` (HuggingFace) | ~880 MB |
| `data/modelseed/`, `data/modelseed_corpus/` | no | `scripts/build_corpus.py` (ModelSEED GitHub) | ~37 MB |
| `data/embeddings/target_sapbert.npz` | no | `scripts/regen_embeddings.py` (computed locally) | ~278 MB |

The big regenerable binaries stay out of git to keep the clone lean; everything
small and hard-to-recreate (the gold dictionaries, the training splits, the
trained adapters) is committed so the pipeline is self-contained.

## Run the steps individually

### 1. Model weights — SapBERT + MedCPT (HuggingFace)

```bash
pip install huggingface_hub
python scripts/download_models.py    # downloads + links both encoders, idempotent
```

### 2. ModelSEED corpus + tables

```bash
# both modelmap tables (data/modelseed/) AND the reaction-pipeline corpus
# (data/modelseed_corpus/ incl. the Aliases/ EC/pathway/name tables):
python scripts/build_corpus.py --patches
```

The SSO/KO dictionaries + gold maps already ship in `data/dictionaries/` — no
download needed.

### 3. LoRA adapters (reaction pipeline)

The adapters ship in git under `weights/lora/{sso,ko}/`. If they are ever
missing (partial clone) or you want to **reproduce them from scratch**, retrain
from the bundled splits — no external data required:

```bash
python scripts/train_lora_from_splits.py            # both sso + ko
python scripts/train_lora_from_splits.py --evaluate # + held-out hit@K
```

This uses `data/splits/{sso,ko}_C.json` (the Split-C train/val/test pairs) and
`data/splits/{sso,ko}_meta.json` (source labels) with the frozen recipe
(SapBERT base, LoRA r16/α32, target_modules [query,key,value,dense], lr 2e-5,
batch 64, 3 epochs, seed 17). ~3–6 min/direction on a GPU. The result is the
adapter layout the runtime loads: `weights/lora/{dir}/lora_adapter/`.

> Note: `scripts/finetune_lora.py` is the **general-purpose** fine-tuner — point
> it at your OWN `(source_label, target_reaction_id)` TSV to train a custom
> adapter. `train_lora_from_splits.py` is the one that reproduces *these*
> published adapters from the bundled splits.

### 4. Pre-encoded corpus embeddings

```bash
python scripts/regen_embeddings.py
```

Re-encodes the ModelSEED corpus with SapBERT (~30 s on an H100) and writes
`data/embeddings/target_sapbert.npz` with the exact keys the runtime reads
(`ids, name_emb, ec_emb, eq_emb, pw_emb, ecs_raw`); it self-checks before
finishing. The output is deterministic — regenerating it yields a bit-identical
cache. Add `--include-source-caches` only for split-eval research (the runtime
never loads source caches — it encodes sources fresh per query).

### 5. Verify

```bash
ontomap info     # prints all asset paths + a real-file health check
ontomap version  # 1.6.1
ontomap map --text "Enoyl-CoA hydratase (EC 4.2.1.17)"
```
