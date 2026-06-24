# Setting up ontomap weights + data

The `weights/` and `data/` subtrees ship as **layout-only** in this repo
because the actual binary blobs (~2 GB) live elsewhere. Reconstitute them
once after cloning.

## 1. Model weights — HuggingFace cache

One script downloads SapBERT + MedCPT and symlinks them under
`weights/sapbert/` and `weights/medcpt/`:

```bash
pip install huggingface_hub
python scripts/download_models.py    # downloads + links both encoders, idempotent
```

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

The trained LoRA adapters (~11 MB each, sso + ko split-C) power the
annotation → reaction Pipeline. In a maintainer checkout they are vendored as
real files under `weights/lora/{sso,ko}/`. On a fresh clone where they live in a
sibling research workspace, link them in (idempotent; no-op if already real):

```bash
python scripts/link_lora_adapters.py
# or point at an explicit source:
# ONTOMAP_LORA_SSO=/path/to/sso-adapter ONTOMAP_LORA_KO=/path/to/ko-adapter \
#   python scripts/link_lora_adapters.py
```

They are **not** in the public GitHub repo (gitignored). Request them from the
maintainer if you don't have a workspace copy.

## 4. Pre-encoded corpus embeddings

The runtime loads one cache, `data/embeddings/target_sapbert.npz`. It is
vendored in a maintainer checkout; regenerate it (e.g. after a ModelSEED corpus
refresh) with:

```bash
python scripts/regen_embeddings.py
```

This re-encodes the ModelSEED corpus with SapBERT (~30 s on an H100) and writes
`target_sapbert.npz` with the exact keys the runtime reads
(`ids, name_emb, ec_emb, eq_emb, pw_emb, ecs_raw`); it self-checks the result
before finishing. Add `--include-source-caches` only for split-eval research
(the runtime never loads source caches — it encodes sources fresh per query).

## 5. Verify

```bash
ontomap info     # prints all asset paths + a real-file health check
ontomap version  # 1.6.0
ontomap map --text "Enoyl-CoA hydratase (EC 4.2.1.17)"
```
