# ontomap

**Ontology mapping for metabolic modeling — onto ModelSEED. Self-contained, no LLM at runtime.**

**Version**: 1.6.1 — see [CHANGELOG.md](CHANGELOG.md). New to the repo? Hand it to
Claude Code — [`CLAUDE.md`](CLAUDE.md) is a complete setup-and-run runbook.

ontomap has **two capabilities**:

| | what | input | output | assets |
|---|---|---|---|---|
| **1. Model mapping** (`ontomap.modelmap`, v1.5+) | line up a whole published model's **compounds + reactions** with ModelSEED | a metabolic model (COBRA JSON) | ModelSEED **compound & reaction** ids (rich SQLite) | public (SapBERT + ModelSEED tables) — **runs from a clone** |
| **2. Annotation → reaction** (`ontomap.Pipeline`, 1.x core) | map a gene's **function** to ModelSEED reactions | SSO/KO id or free text | ModelSEED **reactions** | LoRA adapters + SSO/KO dictionaries — **ship in the repo** (adapters also reproducible from the bundled splits) |

```
Model mapping (1): SapBERT synonym embedding + exact index + reaction-network rerank (compounds)
                   SapBERT name embedding + stoichiometric compound-set overlap (reactions, active corpus)
Reaction pipeline (2): SapBERT-LoRA → multi-axis FAISS top-100 → MedCPT fused rerank → +EC-priority → top-K
```

## 60-second start

```bash
git clone https://github.com/VibhavSetlur/ontomap.git && cd ontomap
pip install -e .
bash scripts/setup.sh          # reconstructs every asset (public + bundled), idempotent
```

`scripts/setup.sh` makes **both** capabilities work from a clone — no maintainer
hand-off. It fetches the SapBERT/MedCPT encoders + ModelSEED tables (public),
computes the cached embeddings, and ensures the LoRA adapters are present
(they ship in git; if absent it retrains them from the bundled splits). For
model mapping only (skips the reaction-pipeline assets) pass
`--skip-reaction-pipeline`.

```bash
# capability 1 — map a whole model's compounds + reactions
ontomap map-model --model your_model.json --output mapping.sqlite
# capability 2 — map an annotation / SSO / KO to ModelSEED reactions
ontomap map --text "Enoyl-CoA hydratase (EC 4.2.1.17)"
```
```python
from ontomap import map_model_to_sqlite
map_model_to_sqlite("your_model.json", path="mapping.sqlite")   # top-100 candidates per query (default)
```
The DB is **self-contained** (denormalized ModelSEED metadata) — query it directly:
```sql
SELECT * FROM compound_top_n WHERE rank = 1;   -- best compound call per metabolite
SELECT * FROM reaction_top_n WHERE rank = 1;   -- best reaction call per reaction
```
Full method, schema, accuracy, and limitations: [`docs/COMPOUND_REACTION_MAPPING.md`](docs/COMPOUND_REACTION_MAPPING.md).

### Model-mapping accuracy (held-out silver gold, A. baylyi/ADP1; names + network only)
| entity | n | hit@1 | hit@5 | hit@10 | throughput |
|--------|---|-------|-------|--------|-----------|
| compounds | 694 | 0.934 | 0.996 | 0.996 | 220 q/s |
| reactions | 850 | 0.818 | 0.956 | 0.966 | 123 q/s |

---

Everything below documents **capability 2** (the SSO/KO/RAST → reaction pipeline).

## Inputs accepted (capability 2 — reaction pipeline)

```python
from ontomap import Pipeline
pipe = Pipeline.from_pretrained(direction="sso")

pipe.map(name="Aldehyde dehydrogenase", ec="1.2.1.3")    # name + EC
pipe.map(name="Aldehyde dehydrogenase")                   # name only
pipe.map(ec="1.2.1.3")                                    # EC only
pipe.map(name="...", ec="...", tags=["putative","partial"])  # with tags
pipe.map(name="...", ec="...", notes="from Acidovorax 3H11") # with notes
```

```bash
ontomap map --name "Aldehyde dehydrogenase" --ec 1.2.1.3
ontomap map --ec 1.2.1.3                                    # EC alone
ontomap map --text "Aldehyde dehydrogenase (EC 1.2.1.3)"   # legacy text form
ontomap map --sso SSO:000000027                            # SSO id
ontomap map --input ids.csv --direction sso                # batch
```

## What the output means (READ before quoting any number)

Per prediction (v1.3.0+), `MapResult.reaction_meta[rxn_id]` includes:
- `ec_match_level` ∈ {0,1,2} — no / prefix / exact EC match with query
- `confidence_band` (top-1 only) ∈ {high, medium, low}
- `top1_margin` (top-1 only) — `fused_score(rank=1) − fused_score(rank=2)`

For inputs WITH a true gold standard → `hit@K` is real accuracy.
For inputs WITHOUT a gold (most real user data) → use `confidence_band`
+ `fused_score`. **See [EVALUATION.md](EVALUATION.md) for the full metric
taxonomy: gold vs silver vs other-annotator agreement vs novel.**

## Benchmarks (1× H100 NVL)

| eval set | type | n | hit@10 | mean latency |
|----------|------|---|--------|---------------|
| Morgan-Price gold | **TRUE GOLD** | 31 | **100%** | 39 ms/q |
| RAST silvers (multi-gold) | SILVER agreement | 600 | 92.0% | 39 ms/q |
| Full Acidovorax 3H11 dump | mixed + novel | 8 588 | n/a (most are novel) | 39 ms/q, 25.3 qps |

→ All user targets (top-1=70%, top-10=93%, top-50=100%) met on the
only true gold available. Silver-set gaps reflect both ontomap and
silver-label uncertainty (RAST over-propagates via EC class).

**Provenance**: 12 Research-OS experiments (steps 31–42) document why
this is the best pipeline — see the parent project's
`workspace/MASTER_SUMMARY.md`. Tested 11 reranker alternatives + 6
meta-ensembles + top-200 retrieval + 78 EC patches — none beats MedCPT
at hit@20.


- **Inputs:** three modes —
  - **SSO/KO id** (single flag or file of ids in CSV/TSV/JSON/JSONL/Parquet/TXT)
  - **free-text description** (e.g. `"Enoyl-CoA hydratase (EC 4.2.1.17)"` — bypasses the dictionary, extracts EC numbers from the text)
  - **multi-source annotation TSV** (`ontomap aggregate-tsv` dedups a RAST/BAKTA/dram/glm4ec/… vault dump into a clean per-description file ready for the pipeline)
- **Outputs:** any of — JSON · JSONL · CSV · TSV · Parquet · **SSSOM-TSV** (bio-ontology standard) · **SQLite** (3-table normalised schema) · **directory** (per-query JSON + manifest).
- **Hardware:** runs on any ≥ 8 GB GPU; CPU fallback works (~10× slower).
- **Footprint:** **~1.23 GB fully bundled** — every weight, every cached embedding, every ModelSEED corpus file lives inside `ontomap/`. No `fetch-models` call needed.

## What's in the folder

```
ontomap/
├── README.md           this file
├── INSTALL.md          install + share + air-gap notes
├── pyproject.toml      pip-installable, console-script entry-point `ontomap`
├── ontomap/            python package (~6 kLoC: pipeline, io, cli, bench, info)
├── tests/              13 smoke tests (`pytest -m smoke`)
├── examples/           quickstart.sh · quickstart.py · sample_ids.csv
├── docs/               extended usage notes
│
├── weights/            (≈ 859 MB) — all model weights
│   ├── sapbert/        cambridgeltl/SapBERT-from-PubMedBERT-fulltext @ pinned SHA
│   ├── medcpt/         ncbi/MedCPT-Cross-Encoder @ pinned SHA
│   ├── lora/{sso,ko}/  this project's Split-C LoRA adapters (~11 MB each)
│   ├── swept_weights.json   multi-axis swept weights (frozen step 01)
│   ├── MANIFEST.txt    SHA-256 + size for every bundled file
│   └── LICENSES.md     upstream license per artifact (read before redistribution)
│
└── data/               (≈ 473 MB) — every input the pipeline reads
    ├── embeddings/                  cached SapBERT embeddings (skip re-encoding)
    │   ├── target_sapbert.npz       ~351 MB · ModelSEED NAME/EC/EQUATION/PATHWAY
    │   ├── sso_source_sapbert.npz   ~11 MB
    │   └── ko_source_sapbert.npz    ~25 MB
    ├── dictionaries/                source ontology dictionaries
    │   ├── SSO_dictionary.json      ~5 MB · RAST/BAKTA SSO terms
    │   ├── KO_dictionary.json       ~4 MB · KEGG Orthology
    │   ├── SSO_reactions.json       2 124 curated SSO → ModelSEED (gold, for reproducibility)
    │   └── kegg_95_0_ko_seed.tsv    4 754 curated KO → ModelSEED (gold)
    └── modelseed_corpus/            ~37 MB · 36 197 reactions + compounds + aliases
```

When you receive `ontomap/` (zip / rsync / `cp -RL`), this whole tree is populated and ready to run. **No network access required at runtime.**

## Install

```bash
cd ontomap
pip install -e .                # editable; uses bundled weights + data in place
ontomap info                    # confirms the bundle is intact + tests imports
ontomap map --sso SSO:000000027 # smoke test on a real query
```

If the bundled weights aren't where the package expects them (rare — e.g., you re-laid out the folder), point `ONTOMAP_HOME` at the directory containing `weights/` and `data/`:

```bash
export ONTOMAP_HOME=/path/to/ontomap
```

## Quickstart

```bash
# inside ontomap/ folder
bash examples/quickstart.sh     # 6-step end-to-end demo
# or
python examples/quickstart.py   # programmatic equivalent
```

## CLI reference

```
ontomap map               map SSO/KO id(s) OR free-text description(s) to top-k ModelSEED reactions
ontomap map-model         map a whole model's compounds + reactions to ModelSEED (rich SQLite) [v1.5+]
ontomap aggregate-tsv     aggregate a multi-source annotation TSV (RAST/BAKTA/dram/glm4ec dump shape) into an ontomap-ready descriptions file (+ JSONL provenance sidecar)
ontomap bench             reproducible scaling benchmark (latency / RAM / VRAM at multiple N)
ontomap info              version + weight pins + device + bundle status + smoke-test
ontomap info --verify-manifest   re-hash every bundled file vs MANIFEST.txt
ontomap fetch-models      re-fetch SapBERT + MedCPT from HuggingFace (force-update bundled weights)
ontomap version           print package version
```

### Common `ontomap map` invocations

#### SSO/KO id input (curated ontology lookup)

```bash
# single query, top-5 to stdout (compact JSONL)
ontomap map --sso SSO:000000027 --top-k 5

# single query, full top-100 to a rich JSON file
ontomap map --ko K10046 --output result.json --top-k 100

# batch from CSV (auto-detects id column), SSSOM-TSV output
ontomap map --input ids.csv --direction sso --output results.sssom.tsv

# batch → SQLite (3 tables: queries, predictions, reactions + view)
ontomap map --input ids.csv --direction sso --output results.sqlite
sqlite3 results.sqlite \
  "SELECT * FROM top_n_with_meta WHERE rank <= 3 ORDER BY query_id, rank;"

# batch → directory of per-query JSON files + manifest.json (scales to 10⁵+)
ontomap map --input ids.csv --direction sso --output batch_out/

# pick format explicitly (overrides extension detection)
ontomap map --input ids.csv --direction sso --output results --format parquet
```

#### Free-text description input (production workflow for annotation dumps)

```bash
# single free-text query (any embedded "EC X.Y.Z[.W]" is auto-extracted into the EC axis)
ontomap map --text "Enoyl-CoA hydratase (EC 4.2.1.17)" --top-k 5

# batch from a TSV with a `description` column (auto-detected; --text-column overrides)
ontomap map --text-input my_genes.tsv --output predictions.sssom.tsv

# explicit id + description columns
ontomap map --text-input my_genes.tsv \
            --id-column gene --text-column annotation \
            --output predictions.sqlite
```

#### Multi-source annotation TSV (RAST-vault dump shape)

```bash
# 1. Aggregate — dedup across the 10+ annotation sources per gene; drop "hypothetical protein"-style rows.
#    --dedup global collapses to one row per unique description (cheapest pass).
#    --dedup per-gene keeps one row per (gene, description) — better for downstream re-attach.
ontomap aggregate-tsv \
    --input  acidovorax_3H11_annotation_reactions_dump.tsv \
    --output clean_descriptions.tsv \
    --provenance clean_descriptions.provenance.jsonl \
    --dedup global

# 2. Run the pipeline on the deduplicated descriptions
ontomap map --text-input clean_descriptions.tsv \
            --id-column id --text-column description \
            --output acidovorax_predictions.json
```

### Programmatic

```python
from ontomap import Pipeline

pipe = Pipeline.from_pretrained(direction="sso", device="cuda")

# 1) Curated SSO/KO id
r = pipe.map_one("SSO:000000027", top_k=100)
print(r.top1)                          # (reaction_id, fused_score)
print(r.confidence_calibrated[0])      # isotonic-regression calibrated probability
print(r.reaction_meta[r.top1[0]])      # name, ec_list, equation, pathway
print(r.stage_breakdown_ms)            # encode / retrieve / medcpt / fuse

# 2) Free-text annotation (production workflow)
results = pipe.map_descriptions(
    ["Enoyl-CoA hydratase (EC 4.2.1.17)",
     "ABC transporter substrate-binding protein",
     "LSU rRNA pseudouridine(2457) synthase (EC 5.4.99.20)"],
    ids=["Ac3H11_100", "Ac3H11_2", "Ac3H11_10"],
    top_k=10,
)
print(results[0].top1)                 # (rxn02167, 0.93)  — EC 4.2.1.17 → enoyl-CoA hydration

# 3) Multi-source RAST-vault TSV → ontomap-ready file
from ontomap import aggregate_annotation_tsv
n_descs, n_genes, n_rows = aggregate_annotation_tsv(
    input_path="acidovorax_3H11_annotation_reactions_dump.tsv",
    output_path="clean_descriptions.tsv",
    provenance_path="clean_descriptions.provenance.jsonl",
    dedup_mode="global",
)
```

## Confidence scores

Two scores per prediction:

1. `fused_score` — `σ · lora_norm + (1−σ) · medcpt_norm`. Use for ranking within a query.
2. `confidence_calibrated` — isotonic-regression-calibrated probability per direction. Use for abstention / filtering. *"`confidence = 0.8` ⇒ in held-out validation, candidates with this raw score were the gold mapping 80 % of the time"*.

SSSOM-TSV output also assigns a `predicate` per row:
- `skos:exactMatch` for confidence ≥ 0.85
- `skos:closeMatch` for 0.65 ≤ confidence < 0.85
- `skos:relatedMatch` for < 0.65

## Validation

- **Gold-set accuracy** (Split-C EC-3-disjoint, no LLM): SSO hits@10 = 0.813 · KO = 0.789 · EC-soft@10 ≈ 0.89 both directions. See [docs/VALIDATION.md](docs/VALIDATION.md) and the upstream project's `synthesis/AUDIT.md`.
- **Scaling**: warm-cache p50 latency ≈ 100–130 ms · throughput ≈ 9 q/s on 1× H100 · peak VRAM 6.3 GB and N-independent. See [docs/BENCHMARK.md](docs/BENCHMARK.md) or run `ontomap bench`.
- **Smoke tests**: `pytest -m smoke` — 13 tests covering CLI, IO (all 8 output formats), SQLite schema, directory mode.

## License + citation

Code: MIT. Bundled models inherit upstream licenses — see [weights/LICENSES.md](weights/LICENSES.md). Notable: **MedCPT is NIH research-use only** (not for commercial use); replace with an MIT cross-encoder before any commercial deployment.

```bibtex
@software{ontomap2026,
  title  = {ontomap: frozen pipeline-3 ontology mapping for SSO/KO → ModelSEED reactions},
  author = {Setlur, Vibhav A.},
  year   = {2026},
  url    = {https://github.com/VibhavSetlur/ontology-mapping},
  doi    = {<Zenodo DOI TBD>}
}
```
