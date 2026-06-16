# Setting up ontomap weights + data

The `weights/` and `data/` subtrees ship as **layout-only** in this repo
because the actual binary blobs (~2 GB) live elsewhere. Reconstitute them
once after cloning.

## 1. Model weights — HuggingFace cache

```bash
pip install huggingface_hub
huggingface-cli download cambridgeltl/SapBERT-from-PubMedBERT-fulltext
huggingface-cli download ncbi/MedCPT-Cross-Encoder
```

After the download, run:

```bash
python scripts/link_weights.py
```

This creates the symlinks under `weights/sapbert/` and `weights/medcpt/`
pointing into your HF cache.

## 2. ModelSEED corpus + dictionaries

Download the latest ModelSEED reactions.tsv:

```bash
curl -L -o data/modelseed_corpus/reactions.tsv \
  https://raw.githubusercontent.com/ModelSEED/ModelSEEDDatabase/master/Biochemistry/reactions.tsv

curl -L -o data/modelseed_corpus/compounds.tsv \
  https://raw.githubusercontent.com/ModelSEED/ModelSEEDDatabase/master/Biochemistry/compounds.tsv
```

SSO / KO dictionaries are derived from KBase + KEGG; pre-built copies are
shipped via the project's `inputs/raw_data/` folder (request access).

**For `ontomap.modelmap`** (compound/reaction model mapping, 1.5+), put the
same two TSVs under `data/modelseed/` (the location its resolver checks):

```bash
mkdir -p data/modelseed
ln -sf "$PWD/data/modelseed_corpus/compounds.tsv" data/modelseed/compounds.tsv
ln -sf "$PWD/data/modelseed_corpus/reactions.tsv" data/modelseed/reactions.tsv
```

Then `map_model_to_sqlite(model_json)` works with no `modelseed_dir=` arg
(resolution order: explicit arg → `$ONTOMAP_MODELSEED` → `data/modelseed/`).

## 3. LoRA adapters

The trained LoRA adapters (~6 split-pairs × ~16 MB) live in the project
workspace at `workspace/17_sapbert_lora/outputs/adapters/`. Symlink them in:

```bash
python scripts/link_lora_adapters.py
```

## 4. Pre-encoded corpus embeddings

These are cached after first run; or regenerate:

```bash
python scripts/encode_corpus.py --output data/embeddings/
```

This takes ~30 s on an H100.

## 5. Verify

```bash
ontomap info     # prints all asset paths + checksums
ontomap version  # 1.1.0
ontomap map --text "Enoyl-CoA hydratase (EC 4.2.1.17)"
```
