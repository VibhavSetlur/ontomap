# DATA — training data for the bundled SapBERT-LoRA adapters

This document describes the data used to train the LoRA adapters bundled at
`ontomap/weights/lora/{sso,ko}/lora_adapter/`. The adapters shipped in
`ontomap` are the **Split-C (EC-3-disjoint) checkpoints from workspace step
17** — the most rigorous of the three splits trained. Full training code is
preserved under
`/scratch/vsetlur/ontology-mapping/workspace/17_sapbert_lora/scripts/`.

> **For EVALUATION data** (what was used to *test* ontomap rather than train
> it) and what `hit@K` means for inputs without a gold standard, see
> [`EVALUATION.md`](EVALUATION.md). The short version:
> - The only **true gold** in the campaign was `gold_curated_morgan_price`
>   (31 human-curated genes from Henry's Acidovorax 3H11 dump).
> - "RAST silver" sources (~743 genes/source) are useful but they're
>   automated annotations, not curation.
> - Other-annotator sources (prokka, glm4ec, kofamscan, ...) are
>   tool-vs-tool agreement, NOT accuracy.
> - The bulk of the 8 588 free-text inputs from the dump are **novel** —
>   they have no gold at all. For those, use `confidence_band` from the
>   `MapResult.reaction_meta` field, NOT `hit@K`.

For redistribution, licenses, and SHA-256 manifests of bundled artifacts see
[`weights/LICENSES.md`](weights/LICENSES.md) and
[`weights/MANIFEST.txt`](weights/MANIFEST.txt).

---

## 1. Three training data sources

| dataset | file | rows | what it is |
|---|---|---:|---|
| KBase SSO → ModelSEED gold | `inputs/raw_data/SSO_reactions.json` (also bundled at `data/dictionaries/SSO_reactions.json`) | **2,124** SSO IDs · **3,717** (sso, rxn) pairs (3,695 after dropping obsolete ModelSEED reactions) | Curated map from SEED Subsystem Ontology terms to ModelSEED reaction IDs. |
| KEGG KO → ModelSEED gold (KEGG release 95.0) | `inputs/raw_data/kegg_95_0_ko_seed.tsv` (also bundled at `data/dictionaries/kegg_95_0_ko_seed.tsv`) | **4,754** KO IDs · **11,016** (ko, rxn) pairs after expansion | Tab-separated: `ko_id`, `seed_ids` (semicolon-separated ModelSEED rxn IDs), `definition` (KEGG ortholog name + EC numbers in brackets), `kegg_ids` (KEGG R-numbers). |
| ModelSEED Biochemistry corpus (target universe) | `inputs/raw_data/modelseed/{reactions,compounds}.tsv` + `inputs/raw_data/modelseed/Aliases/Unique_ModelSEED_Reaction_{Aliases,ECs,Pathways,Names}.txt` | **43,775** reactions · **33,993** compounds | The target ID universe + EC numbers, pathways, and alternative names used to render the target side of each training pair. |

### Source-label dictionaries (used to render the `source` text of each pair)

| dictionary | file | entries | role |
|---|---|---:|---|
| SSO term dictionary | `inputs/raw_data/SSO_dictionary.json` (`data/dictionaries/SSO_dictionary.json`) | OBO-format ontology (`term_hash` of SSO entries) | Maps `SSO:XXXXXXXXX` → SEED subsystem name string for the source-side encoder input. |
| KO term dictionary | `inputs/raw_data/KO_dictionary.json` (`data/dictionaries/KO_dictionary.json`) | **22,530** KO terms (only ~4,754 are in the gold) | Maps `K#####` → KEGG ortholog name. KO gold rows fall back to `definition` column from the TSV when `KO_dictionary.json` has no entry. |

### Provenance / URLs / citations

- **KBase SSO** — `cb_annotation_ontology_api` repo at
  <https://github.com/cb-craft/cb_annotation_ontology_api>. SSO is the SEED
  Subsystem Ontology used by RAST. Citation: Overbeek et al., *The SEED and
  the Rapid Annotation of microbial genomes using Subsystems Technology
  (RAST).* NAR 2014.
- **KEGG KO 95.0** — Kanehisa Labs at <https://www.kegg.jp/kegg/ko.html>.
  The `kegg_95_0_ko_seed.tsv` mapping was obtained via KBase, snapshotting
  KEGG release **95.0** for reproducibility. Citation: Kanehisa & Goto,
  *KEGG: Kyoto Encyclopedia of Genes and Genomes.* NAR 2000.
- **ModelSEED Biochemistry** — <https://modelseed.org/> · GitHub
  <https://github.com/ModelSEED/ModelSEEDDatabase>. Citation: Henry et al.,
  *High-throughput generation, optimization and analysis of genome-scale
  metabolic models.* Nature Biotechnology 2010.

---

## 2. Licenses

| dataset | license | redistribution |
|---|---|---|
| KBase SSO (`SSO_dictionary.json`, `SSO_reactions.json`) | **CC0** (KBase) | free, no restrictions |
| KEGG KO (`KO_dictionary.json`) and KO→ModelSEED gold (`kegg_95_0_ko_seed.tsv`) | **KEGG academic-use** (KO term names) / KBase **CC0** for the curated mapping table itself | KEGG term names follow KEGG academic-use policy; cite KEGG when publishing mapping outputs that reference KO IDs |
| ModelSEED reactions / compounds / aliases | **CC0** | free, no restrictions |
| Bundled LoRA adapters (`weights/lora/{sso,ko}/`) | **MIT** (same as `ontomap`) | free, no restrictions |
| Bundled SapBERT base weights | **MIT** (cambridgeltl/SapBERT-from-PubMedBERT-fulltext) | free |
| Bundled MedCPT reranker | **NIH research-use** | NOT for commercial use; swap for an MIT cross-encoder before commercial deployment |

See [`weights/LICENSES.md`](weights/LICENSES.md) for the canonical table.

---

## 3. Positive-pair construction

For each direction (SSO and KO):

1. Read the curated gold file (`SSO_reactions.json` or
   `kegg_95_0_ko_seed.tsv`). Each source ID has one or more ModelSEED
   reaction IDs.
2. Drop pairs whose target reaction is **obsolete** (`is_obsolete` flag set
   in `modelseed/reactions.tsv`). This removed 22 SSO pairs (3,717 → 3,695)
   and a comparable share of KO pairs.
3. Render the source-side string via
   `ontomap.multi_axis.render_source_axes`:
   - `NAME` axis = dictionary `name` (SSO subsystem name or KO ortholog
     name, falling back to the KEGG `definition` for KOs missing in
     `KO_dictionary.json`).
   - `EC` axis = EC numbers parsed from the label via `parse_ec_from_text`.
4. Render the target-side string via
   `ontomap.multi_axis.render_target_axes` for the matched ModelSEED
   reaction:
   - `NAME` axis = primary reaction name (+ alt names from
     `Unique_ModelSEED_Reaction_Names.txt`).
   - `EC` axis = EC numbers from `ec_numbers` column +
     `Unique_ModelSEED_Reaction_ECs.txt`.
   - `EQUATION` and `PATHWAY` axes also rendered but **not** used for LoRA
     training (the LoRA was deliberately trained on `NAME` ↔ `NAME` and `EC`
     ↔ `EC` only; the multi-axis FAISS pipeline still uses cached base
     SapBERT embeddings for the `EQUATION` and `PATHWAY` corpus axes).

One positive pair per `(source, target_reaction)`. See
`workspace/17_sapbert_lora/scripts/17a_build_splits.py` lines 41–101.

---

## 4. Negative-pair sampling

Per training pair, **7 hard negatives** (named `negative_1 … negative_7`)
plus **in-batch negatives** via `BatchSamplers.NO_DUPLICATES` from
`sentence_transformers`. Hard negatives are mined offline by
`workspace/17_sapbert_lora/scripts/17b_mine_hard_negatives.py`:

1. **Pool** — top-100 retrievals per source from the cached SapBERT swept
   pipeline at
   `workspace/15_ec_extraction_filter/outputs/tables/15_top100_intervention_{sso,ko}.jsonl`.
2. **Drop near-duplicates of gold** — strip the candidate if its normalised
   equation string equals gold's normalised equation.
3. **Drop EC-3 siblings of gold** — strip the candidate if its EC-3 prefix
   set intersects gold's EC-3 prefix set (sources with EC unknown skip this
   filter).
4. **Drop weak negatives** — strip candidates whose cosine similarity to
   the source NAME embedding is **< 0.4** (these are uninformative).
5. **Cap** at the first **8** survivors per pair, of which the trainer
   consumes the first 7 (`n_neg=7` in `17c_train_lora.py:253`).

Mining outcomes (from `data/output/hard_neg_summary.json`):

| direction | split | train pairs | full-8 negs | < 8 negs (padded with uniform sample) |
|-----------|-------|------------:|------------:|--------------------------------------:|
| SSO | A | 2,956 | 2,939 | 17 |
| SSO | B | 2,901 | 2,880 | 21 |
| SSO | C | 2,834 | 2,816 | 18 |
| KO  | A | 8,813 | 8,675 | 138 |
| KO  | B | 8,784 | 8,643 | 141 |
| KO  | C | 8,929 | 8,762 | 167 |

When a pair has fewer than 7 hard negatives, the training script pads with
uniform random samples from the train target universe (excluding gold).

> **Deviation from the pre-registered plan**: MedCPT margin filtering for
> hard negatives was *not* applied — only the gold-equation-duplicate,
> EC-3-sibling, and cosine ≥ 0.4 filters above. The adversarial KO
> sibling-margin loss was likewise omitted. The Split-C result is strong
> enough without them. See
> `workspace/17_sapbert_lora/README.md#deviations-from-the-pre-registered-plan`.

---

## 5. Train / val / test splits

Three split protocols were built **per direction** with `seed=17`, all
**80 / 10 / 10** train / val / test. Code:
`workspace/17_sapbert_lora/scripts/17a_build_splits.py`. Frozen artefacts at
`workspace/17_sapbert_lora/data/splits/{sso,ko}_{A,B,C}.json`.

| split | stratification | leakage protection | use |
|---|---|---|---|
| **A** — random-pair, stratified | Random shuffle on `(source, reaction)` pairs, stratified on **source gold-set-size bucket** (`1`, `2–5`, `6–10`, `11+`). | None — sources and EC families can appear in both train and test. | Optimistic upper bound (random-pair fold). |
| **B** — source-disjoint | Group-split on **source ID** (each SSO/KO ID lives in exactly one fold). | No source appears in two folds — measures generalisation to unseen IDs. | Mid-strict sanity gate (`A−B > 5 pp` ⇒ source leakage). |
| **C** — EC-3-disjoint | Group-split on the source's **EC-3-digit prefix** (e.g., `2.7.1`). Sources with EC unknown fall back to source-disjoint within the `EC_NA` group. | No EC-3 family appears in two folds — measures generalisation to unseen enzyme sub-classes. | **Strictest split** — adoption gate (`Δhits@10 ≥ +1 pp on Split-C` with bootstrap CI > 0 ⇒ adopt LoRA). |

### Per-split counts

From `data/splits/{sso,ko}_{A,B,C}.json` (counts are `(source, reaction)`
pairs; unique source / target counts shown in parentheses).

**SSO** (2,110 sources after dropping obsolete-only sources; sources with
no valid rxn dropped):

| split | train pairs (src / tgt) | val pairs (src / tgt) | test pairs (src / tgt) |
|---|---:|---:|---:|
| A | **2,956** (1,790 / 1,786) | **369** (321 / 339) | **370** (313 / 335) |
| B | **2,901** (1,688 / 1,738) | **363** (211 / 332) | **431** (211 / 364) |
| C | **2,834** (1,629 / 1,672) | **447** (246 / 327) | **414** (235 / 293) |

**KO** (4,754 sources):

| split | train pairs (src / tgt) | val pairs (src / tgt) | test pairs (src / tgt) |
|---|---:|---:|---:|
| A | **8,813** (4,194 / 5,323) | **1,101** (910 / 982) | **1,102** (923 / 992) |
| B | **8,784** (3,803 / 5,326) | **1,200** (475 / 1,092) | **1,032** (476 / 933) |
| C | **8,929** (3,990 / 5,258) | **915** (308 / 533) | **1,172** (456 / 747) |

### Why three splits

The 3-split design is a **leakage-detection sanity gate**, not just three
independent benchmarks. The pre-registered adoption rule
(`H-pipeline-3-A`) is:

> Adopt LoRA only if Δhits@10 on **Split-C** is ≥ +1 pp on BOTH SSO and KO
> with bootstrap 95% CI > 0.

Pre-registered STOP signals: `Δ@A − Δ@B > 5 pp` ⇒ source leakage,
`Δ@B − Δ@C > 5 pp` ⇒ EC-family leakage. Both passed for both
directions — see `workspace/17_sapbert_lora/conclusions.md`.

### Which split ships in `ontomap`

The bundled adapters at `weights/lora/{sso,ko}/lora_adapter/` are the
**Split-C** checkpoints (`workspace/17_sapbert_lora/outputs/adapters/sapbert-lora-{sso,ko}-splitC/lora_adapter/`).
They were trained on:

- **SSO Split-C train**: 2,834 pairs (`n_train_primary=2834`,
  `n_train_aux=1923`).
- **KO Split-C train**: 8,929 pairs (`n_train_primary=8929`,
  `n_train_aux=7221`).

Held-out test-set headline (from `workspace/17_sapbert_lora/README.md`):
SSO Split-C **+8.5 pp** hits@10 (95% CI [+5.1, +12.3]), KO Split-C
**+5.9 pp** (95% CI [+3.5, +8.3]).

---

## 6. Auxiliary EC contrastive dataset

A second dataset is built per training row when both source and target have
non-empty EC strings. It contains only `(source_EC_text, target_EC_text)`
positive pairs (no mined hard negatives) and is fed to a second copy of
`MultipleNegativesRankingLoss` with **in-batch negatives only**, fused with
the primary loss via the multi-loss dict pattern in
`SentenceTransformerTrainer` (loss weight on the aux head is determined by
the dataset size ratio in practice; the plan called for weight 0.3 and the
script uses two `MultipleNegativesRankingLoss` instances summed equally —
see `17c_train_lora.py:279–310`).

Aux sizes for the Split-C checkpoints shipped in `ontomap`:
- SSO: 1,923 aux pairs (out of 2,834 primary)
- KO: 7,221 aux pairs (out of 8,929 primary)
