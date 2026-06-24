# ontomap — guide for Claude Code

You are helping a user set up and run **ontomap** from a fresh clone. This
file tells you exactly how. Read it fully before acting.

## What ontomap is
A self-contained ontology-mapping tool for metabolic modeling with **two
capabilities** (no LLM at runtime):

1. **`ontomap.modelmap`** (v1.5+, **the easy one to run from a clone**) — map a
   whole published metabolic model's **compounds and reactions** (foreign
   namespace) onto **ModelSEED** ids. Needs only public assets (SapBERT +
   ModelSEED tables).
2. **`ontomap.Pipeline`** (the 1.x core) — map a functional **annotation**
   (RAST/SSO/KO id or free text) to ModelSEED **reactions**. Needs extra
   assets (LoRA adapters + SSO/KO dictionaries) that are **not public**.

## Setup (do this first)
```bash
# 1. Environment (Python 3.10–3.12; 3.11 recommended)
conda create -n ontomap python=3.11 -y && conda activate ontomap   # or python -m venv
# 2. Install the package
pip install -e .
# 3. Fetch public assets (SapBERT weights + ModelSEED tables) — idempotent
bash scripts/setup.sh
# 4. Confirm
ontomap version        # 1.6.0
ontomap info           # device + bundle status + smoke test
```
- **GPU optional**: any NVIDIA GPU ≥8 GB makes it ~10× faster; CPU works.
  modelmap uses ~2.5 GB RAM / ~3.8 GB GPU at peak.
- `scripts/setup.sh` downloads SapBERT from HuggingFace and the ModelSEED
  `compounds.tsv`/`reactions.tsv` from GitHub into `data/modelseed/`. If it
  fails, the cause is almost always missing `huggingface_hub` or no network.

## Run capability 1 — map a whole model (recommended)
Input is a COBRA-style JSON: `{"metabolites":[{"id","name",...}],
"reactions":[{"id","name","metabolites":{met_id:coef}}]}`.

```bash
# CLI → rich, self-contained SQLite (compounds + reactions, top-100, scores,
# denormalized ModelSEED metadata, performance, run_metadata, + join views)
ontomap map-model --model your_model.json --output mapping.sqlite

# or raw JSON
ontomap map-model --model your_model.json --output mapping.json --format json
```
```python
from ontomap import CompoundMapper, ReactionMapper, map_model, map_model_to_sqlite
CompoundMapper.from_modelseed().build().map("pimelate")[0]   # -> ('cpd01727', score, signals)
map_model_to_sqlite("your_model.json", path="mapping.sqlite")   # top_k=100 per query by default
```
Inspect the DB: `sqlite3 mapping.sqlite "SELECT * FROM compound_top_n WHERE rank=1 LIMIT 5;"`
(views: `compound_top_n`, `reaction_top_n`). Full schema + accuracy +
caveats: `docs/COMPOUND_REACTION_MAPPING.md`.

## Run capability 2 — annotation → reaction (needs extra assets)
```bash
ontomap map --text "Enoyl-CoA hydratase (EC 4.2.1.17)" --top-k 10
ontomap map --sso SSO:000000027 --direction sso
```
This needs the LoRA adapters + SSO/KO dictionaries + cached embeddings. They
are **not in the public repo** (the `weights/lora/*/lora_adapter` symlinks are
broken on a fresh clone). If the user needs the reaction pipeline, point them
to `SETUP_ASSETS.md` and tell them to request those assets from the maintainer;
otherwise prefer capability 1.

## If the user gives you their own model
1. Make sure it's COBRA-style JSON (metabolites + reactions with a `metabolites`
   stoichiometry dict). If it's SBML/`.mat`, convert with `cobrapy` first.
2. `ontomap map-model --model THEIR_MODEL.json --output mapping.sqlite`
3. Hand them `mapping.sqlite` + explain the `*_top_n` views and the
   confidence signals (`exact_match`/`network_score` for compounds;
   `set_jaccard`/`name_sim` for reactions) for thresholding.

## Key facts to tell the user
- Accuracy (held-out silver gold, ADP1): compounds hit@1 ≈ 0.93 / hit@10 ≈ 1.0;
  reactions hit@1 ≈ 0.82 / hit@10 ≈ 0.97. Strict hit@k is a lower bound (gold
  is "silver"; much residual error is ModelSEED duplicate ids).
- Throughput ≈ 220 compounds/s and 123 reactions/s warm.
- The output DB is **self-contained** — no other files needed to consume it.

## Docs map
- `README.md` — overview + both quickstarts + benchmarks
- `docs/COMPOUND_REACTION_MAPPING.md` — model mapping: method, results, schema, limitations
- `docs/VALIDATION.md` / `docs/BENCHMARK.md` — reaction pipeline accuracy + scaling
- `SETUP_ASSETS.md` / `INSTALL.md` — assets + install
- `CHANGELOG.md` — release history (current: 1.6.0)
