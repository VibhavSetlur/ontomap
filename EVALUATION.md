# Evaluating ontomap — what the metrics actually mean

A short, opinionated guide to what `hit@K`, `frac_recovered`, `confidence_band`,
`top1_margin`, and the per-prediction `ec_match_level` mean — and when each
one is the right thing to read.

This matters because **most real-world inputs to ontomap have no human-curated
gold standard**. Asking "what's the hit@10?" on a novel input is meaningless —
there's nothing to hit against. The right question is "what does the
confidence look like, and should I trust the top-1?".

---

## 1. Three kinds of test set

Always ask which one you're in before quoting a number.

### A. TRUE GOLD — a human biochemist labelled the reactions
The reactions assigned to each query gene are correct (modulo human error).
Example: `gold_curated_morgan_price` — 31 Acidovorax 3H11 genes curated by
Morgan Price during her fitness-browser study.

**`hit@K`, `frac_recovered@K`, and `MRR@K` are real accuracy measures.**
You may report them as ontomap's true accuracy.

### B. SILVER — a high-quality automated annotator
RAST, KEGG, BAKTA. The labels are usually right but the annotator has its own
failure modes (e.g., RAST over-propagates via EC class).

**`hit@K` here is "agreement with the silver annotator" — NOT accuracy.**
A `hit@10 = 92%` against RAST means ontomap and RAST agree on at least one
reaction for 92% of RAST-annotated genes. Either could be wrong.

### C. AGREEMENT — comparison with another prediction tool
Examples: glm4ec, prokka, kofamscan, dram. These are also predictions.

**`hit@K` here is a tool-vs-tool similarity benchmark.** Useful for
seeing where two prediction tools converge or diverge. Not accuracy.

### D. NOVEL — no ground truth available
The largest case in practice. Your gene has a description but nobody has
assigned a reaction by hand or by another tool. Examples:
- "hypothetical protein"
- "membrane protein"
- a newly-sequenced organism with no curation

**`hit@K` is undefined.** Use the per-prediction confidence fields instead.

---

## 2. The metrics, defined

For a query with gold reaction set `G` and pipeline top-K predictions `P_K`:

| metric | definition | range | reads as |
|--------|------------|-------|----------|
| **`hit@K`** | `1` if `P_K ∩ G ≠ ∅` else `0`, averaged across queries | 0–1 | "did we surface ≥1 correct reaction in top-K?" |
| **`frac_recovered@K`** | `|P_K ∩ G| / |G|`, averaged across queries | 0–1 | "what fraction of the gold reactions did we recover?" |
| **`MRR@K`** | `1 / rank_of_first_hit` (0 if no hit ≤K), averaged | 0–1 | "how high did we rank the first correct reaction?" |
| **`recall@K`** | synonym of `hit@K` in our codebase | 0–1 | same |

`hit@K` is the headline. `frac_recovered@K` matters when a gene has multiple
gold reactions (e.g., multifunctional enzymes) and you want to know whether
you recovered them all. `MRR@K` is more sensitive to ranking order than `hit@K`.

---

## 3. The per-prediction confidence outputs (v1.3.0+)

For each prediction in the returned `MapResult.reaction_meta[rxn_id]` you get:

### `ec_match_level` (every prediction)

| value | meaning |
|-------|---------|
| `2` | query EC exactly matches an EC in the candidate's `ec_numbers` |
| `1` | query EC is a prefix of (or prefixed by) an EC in the candidate's `ec_numbers` — e.g. query `1.10.3` matches candidate `1.10.3.10` |
| `0` | no EC overlap |

Useful for: **filtering downstream reactions to only those whose EC matches
the query EC**. A `level=0` top-1 on a query that DID have an EC means
the candidate's `ec_numbers` field is empty (corpus metadata gap, not pipeline
failure).

### `confidence_band` (top-1 only)

| value | trigger | typical usage |
|-------|---------|---------------|
| **`high`** | `fused_score ≥ 0.90` AND `margin ≥ 0.05` | safe to use top-1 directly |
| **`medium`** | `fused_score ≥ 0.90` OR (`fused_score ≥ 0.70` AND `margin ≥ 0.05`) | likely correct; consider top-3 |
| **`low`** | otherwise | novel or ambiguous; consider top-10 or skip |

### `top1_margin` (top-1 only)
Raw `fused_score(rank=1) − fused_score(rank=2)`. The headline contributor to
`confidence_band`. Larger = pipeline is more decisive about its top pick.

---

## 4. When you have NO gold (the common case)

For an arbitrary user input, you cannot compute `hit@K`. Use confidence:

```python
from ontomap import Pipeline
pipe = Pipeline.from_pretrained(direction="sso")
r = pipe.map(name="hypothetical protein", id="g1")

top1_rxn, top1_score = r.predictions[0]
band = r.reaction_meta[top1_rxn].get("confidence_band", "low")
margin = r.reaction_meta[top1_rxn].get("top1_margin", 0.0)

if band == "high":
    accept(top1_rxn)
elif band == "medium":
    show_top_3_to_user(r.predictions[:3])
else:  # "low"
    flag_for_manual_review(r)
```

For batch runs, sort by `top1_score` to triage:

```python
results = pipe.map_descriptions(descriptions, ids=ids)
results.sort(key=lambda r: r.predictions[0][1], reverse=True)
# top ~75% of the sorted list will be confidence_band="high"
# bottom ~5-10% will be confidence_band="low" — likely novel / unanchorable
```

### Production-ready signals for "I have no gold"
| signal | how to read it |
|--------|----------------|
| coverage = `n_returned / n_queried` | should be 1.0; if not, something is wrong |
| mean top-1 `fused_score` | ≥0.85 = pipeline finds confident matches for most queries |
| distribution of `confidence_band` | tells you what fraction will need manual review |
| `ec_match_level` distribution | tells you how often the EC axis agrees with the LoRA-NAME pick |

---

## 5. What the campaign found (numbers in proper context)

### True accuracy (Morgan-Price gold, n=31 Acidovorax 3H11 genes)
| K | hit@K | frac_recovered@K |
|---|-------|-------------------|
| 1 | 77.4% | 0.40 |
| 5 | 96.8% | 0.66 |
| **10** | **100.0%** | **0.75** |
| 20 | 100.0% | 0.80 |
| 50 | 100.0% | 0.87 |

→ All user targets (top-1=70%, top-10=93%, top-50=100%) met on true gold.

### RAST silver agreement (n=600, RAST_berdl/theseed/fitness-browser × 200)
| K | hit@K (RAST agreement) | frac_recovered |
|---|---------------------------|-----------------|
| 1 | 57.5% | 0.46 |
| 10 | 92.0% | 0.82 |
| 50 | 95.8% | 0.92 |
| 100 | 96.0% (structural ceiling) | 0.93 |

→ ontomap and RAST agree on ≥1 reaction for 92% of genes at top-10. The 4-pp
ceiling gap at top-50 reflects either ontomap mistakes OR RAST mistakes;
without true gold for those genes we cannot decide which.

### 8 588-input scale test (NO global gold, mixed per-source agreement)
| metric | value | how to read it |
|--------|-------|----------------|
| coverage | 100% (8 588 / 8 588) | the pipeline always returns top-K |
| mean top-1 fused_score | 0.940 | most queries land on confident matches |
| median top-1 fused_score | 0.955 | half of all queries score >0.95 |
| mean latency | 39 ms / query | production-ready throughput |
| p95 latency | 58 ms | tail latency is bounded |
| throughput | 25.3 qps on 1× H100 | scales linearly with GPU count |

→ This is a **production-readiness** test, not an accuracy test. Headline
numbers like "hit@10 = X% on prokka silver" measure agreement with prokka,
not pipeline accuracy. Use the confidence outputs for per-query trust.

---

## 6. Suggested reporting template

When you publish or hand off ontomap results, use this skeleton:

```
Pipeline: ontomap v1.4.0 (SapBERT-LoRA + MedCPT fused, sigma=0.30 SSO)
Inputs:   N queries, format: <name+EC | name-only | EC-only | mixed>
Test set: <NAME> — <human-curated gold | RAST silver | other-annotator agreement | novel>
Headline: hit@K = X%  (interpretation: <true accuracy | agreement with Y>)
Latency:  <mean / p95> ms / query
Confidence distribution (top-1):
  high   X%
  medium Y%
  low    Z%
Provenance: <parquet path, prov.json sidecar, script path>
```

Anything labelled `hit@K` without specifying which kind of test set is
ambiguous and should be re-labelled before being quoted to an external
audience.
