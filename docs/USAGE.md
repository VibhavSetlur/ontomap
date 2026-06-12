# ontomap — usage guide

Three input modes, one frozen pipeline, one output schema. Pick the mode that matches your data.

## 1. Curated SSO/KO id input

Use when you already have SSO or KO ontology ids — e.g. from a RAST/KBase pipeline that emitted SSO terms, or from a KEGG KO assignment step. The id is looked up in the bundled SSO/KO dictionary to retrieve the canonical name + EC + synonyms, which are then fed to the LoRA encoder.

```bash
# single
ontomap map --sso SSO:000000027 --top-k 5
ontomap map --ko  K10046         --top-k 5

# batch (CSV/TSV/JSON/JSONL/Parquet/TXT — id column auto-detected from
# {id, sso_id, ko_id, source_id, query_id, input_id})
ontomap map --input my_ids.csv --direction sso \
            --output predictions.sssom.tsv
```

## 2. Free-text description input *(production workflow for real-world annotation dumps)*

Use when the source has no ontology id — RAST/BAKTA/dram/glm4ec/prokka/kofamscan dumps, GenBank annotations, manually-curated function names, etc. The description text bypasses the dictionary entirely; any embedded `EC X.Y.Z[.W]` substring is auto-extracted into the EC axis so the LoRA encoder sees both the cleaned name (NAME axis) and the EC class hierarchy (EC axis).

```bash
# single free-text query
ontomap map --text "Enoyl-CoA hydratase (EC 4.2.1.17)" --top-k 5
# → expects rxn02167 (enoyl-CoA hydration) at or near rank 1

# batch from a TSV — description column auto-detected from
# {description, desc, text, function, function_name, annotation, label, name, product}
ontomap map --text-input my_genes.tsv \
            --id-column gene --text-column annotation \
            --output predictions.json
```

**Direction:** SSO LoRA is the default for free-text (descriptive function names). KO LoRA is better when the text is structured like a KEGG ortholog assignment (`--direction ko`). For mixed input, run both directions and pick whichever returns the higher fused-score per row.

## 3. Multi-source annotation TSV → ontomap-ready file

Real-world genome-annotation dumps are 10–14× redundant: every gene gets a row per source (RAST, BAKTA, dram, glm4ec, prokka, kofamscan, fitness_browser_desc, fitness_browser_rast, GO, COG, EC, gold_curated_morgan_price, …). The `aggregate-tsv` subcommand collapses that into a unique-description file ready for the pipeline, with a JSONL sidecar preserving the source/gene/reaction provenance for downstream re-attach.

Canonical input shape:

```tsv
gene	source	ontology_term	description	reactions
Ac3H11_1	RAST_berdl	SSO:000023839	Transcriptional regulator, AraC family
Ac3H11_1	bakta_berdl		AraC family transcriptional regulator
Ac3H11_1	prokka		HTH-type transcriptional activator RhaR
Ac3H11_100	glm4ec	EC:4.2.1.17		MSRXN:rxn02167;MSRXN:rxn03245
```

### Aggregate then map

```bash
# 1. Aggregate
ontomap aggregate-tsv \
    --input  acidovorax_3H11_annotation_reactions_dump.tsv \
    --output clean_descriptions.tsv \
    --provenance clean_descriptions.provenance.jsonl \
    --dedup global         # 'global' = one row per unique description
                           # 'per-gene' = one row per (gene, unique description)
# By default rows whose description matches "hypothetical protein" / empty /
# "putative protein" / "unknown function" / etc. are dropped. Pass --keep-trivial
# to include them.

# 2. Map
ontomap map --text-input clean_descriptions.tsv \
            --id-column id --text-column description \
            --output predictions.json --top-k 10
```

### Re-attach the existing source reactions for gold-overlap validation

The provenance sidecar tells you which descriptions already had a reaction proposed by a source annotator (glm4ec / dram / RAST / fitness_browser / kofamscan / GO / EC / gold_curated_morgan_price). Treat these as a partial gold standard:

```python
import json, pandas as pd
prov = [json.loads(l) for l in open("clean_descriptions.provenance.jsonl")]
gold = {p["id"]: p["existing_reactions"] for p in prov if p["existing_reactions"]}

preds = json.load(open("predictions.json"))
hits_at_k = {1: 0, 5: 0, 10: 0}
for p in preds:
    qid = p["query"]["id"]
    if qid not in gold:
        continue
    pred_rxns = [pr["reaction_id"] for pr in p["predictions"]]
    pred_rxns_msrxn = {f"MSRXN:{r}" for r in pred_rxns}
    for k in hits_at_k:
        if pred_rxns_msrxn & set(gold[qid][: len(gold[qid])]) and \
           pred_rxns_msrxn.intersection(set(gold[qid])) & set(f"MSRXN:{r}" for r in pred_rxns[:k]):
            hits_at_k[k] += 1
print(hits_at_k)
```

## Output formats

All three input modes write the same rich schema. Pick the format that fits the downstream consumer:

| format | when to use |
|---|---|
| `--output x.json` | one rich JSON file per batch (good for ≤ 10² queries; human-readable) |
| `--output x.jsonl` | streamable; one rich JSON per line (good for 10³–10⁴ queries) |
| `--output x.sssom.tsv` | bio-ontology standard; pairs cleanly with the [SSSOM toolkit](https://github.com/mapping-commons/sssom-py) |
| `--output x.sqlite` | 3-table normalised schema (queries × predictions × reactions) + a `top_n_with_meta` view — best for analytical queries |
| `--output x.csv` / `x.tsv` | flat table, one row per (query, rank) |
| `--output x.parquet` | columnar; best for pandas / DuckDB pipelines |
| `--output batch_out/` | one JSON file per query under `batch_out/{direction}/<id>.json` + `manifest.json` — best for 10⁵+ queries |

## Picking `--top-k`

- `top_k=5` — for human review; matches the docs/VALIDATION.md headline metric (hits@10).
- `top_k=10` — default; covers ~81% SSO / ~79% KO of curated gold mappings on Split-C EC-3-disjoint.
- `top_k=100` — for downstream LLM re-ranking or for handing the full retrieval list to a domain expert.

## Picking `--direction`

- `--direction sso` — descriptive function names, RAST-style, BAKTA-style, free text with embedded EC. **This is the default for free-text input.** SSO hits@10 = 0.813.
- `--direction ko` — KEGG-orthology-style ids OR text that resembles KO descriptions. KO hits@10 = 0.789.
- Run both and pick the higher-confidence row when the input is mixed.

## Confidence + abstention threshold

The `fused_score` (and the calibrated `confidence` in the SSSOM output) is the right knob:

- **≥ 0.85** → `skos:exactMatch`; auto-accept (~50–60% of queries on non-gold data, per docs/BENCHMARK.md).
- **0.65 – 0.85** → `skos:closeMatch`; route to human review or a downstream LLM rerank.
- **< 0.65** → `skos:relatedMatch`; treat as a candidate-pool only.

The bundled isotonic-regression calibrator backs these thresholds — the raw fused score is replaced with a per-direction probability that "this candidate is the gold mapping" in the SSSOM output.

## Performance expectations

From `docs/BENCHMARK.md` (1× H100 NVL):

- **N = 10**: ~30 s setup + ~100 ms / query → 30 s wall.
- **N = 1,000**: ~140 s wall (~7 q/s; setup amortised).
- **N = 10,000**: extrapolates to ~20 min wall.

On a single mid-range consumer GPU (RTX 3060 / A4000) expect ~150–200 ms / query warm; CPU fallback is ~10× slower (set `--device cpu`).

## See also

- `docs/VALIDATION.md` — gold-set accuracy + ablation table.
- `docs/BENCHMARK.md` — latency / VRAM / throughput at multiple N.
- `docs/REAL_WORLD_ACIDOVORAX.md` — end-to-end walkthrough of the Acidovorax 3H11 annotation dump → reaction predictions case study (this lives in `workspace/27_…/analysis.md` in the upstream project; copy if you need it for an external user).
