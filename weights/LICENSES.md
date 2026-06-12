# Bundled model + data licenses

Every artifact bundled in `ontomap/weights/` and `ontomap/data/` inherits its
upstream license. `ontomap` itself (code, schemas, CLI) is MIT.

| artifact | upstream | license | citation |
|---|---|---|---|
| `weights/sapbert/` (base SapBERT, 440 MB) | [cambridgeltl/SapBERT-from-PubMedBERT-fulltext](https://huggingface.co/cambridgeltl/SapBERT-from-PubMedBERT-fulltext) | MIT | Liu F, Shareghi E, Meng Z, Basaldella M, Collier N. *Self-Alignment Pretraining for Biomedical Entity Representations.* NAACL 2021. arXiv:2010.11784. |
| `weights/lora/{sso,ko}/` (project LoRA adapters, ~11 MB each) | this project (step 17) | MIT (same as ontomap) | Setlur 2026 — trained on Split-C EC-3-disjoint fold via MNRL + 7 hard negatives mined with MedCPT. |
| `weights/medcpt/` (MedCPT Cross-Encoder, 440 MB) | [ncbi/MedCPT-Cross-Encoder](https://huggingface.co/ncbi/MedCPT-Cross-Encoder) | **NIH research-use** (not for commercial use) | Jin Q, Kim W, Chen Q, Comeau DC, Yeganova L, Wilbur WJ, Lu Z. *MedCPT: Contrastive Pre-trained Transformers with Large-scale PubMed Search Logs for Zero-shot Biomedical Information Retrieval.* Bioinformatics 2023. doi:10.1093/bioinformatics/btad651 |
| `weights/swept_weights.json` (multi-axis swept weights) | this project (step 01) | MIT | Setlur 2026 — coordinate descent on the full gold set, validated by step 08 4-fold CV (<0.2 pp generalisation gap). |
| `data/embeddings/*.npz` (~387 MB SapBERT corpus embeddings) | this project | MIT (derived) | Cached `cambridgeltl/SapBERT-from-PubMedBERT-fulltext` embeddings of the ModelSEED corpus — inherits SapBERT MIT for the model, CC0 for the source data. |
| `data/modelseed_corpus/` (~37 MB reactions, compounds, aliases) | [ModelSEED Biochemistry](https://modelseed.org/) | CC0 | Henry et al. *High-throughput generation, optimization and analysis of genome-scale metabolic models.* Nature Biotechnology 2010. |
| `data/dictionaries/SSO_dictionary.json` (~5 MB) | [KBase cb_annotation_ontology_api](https://github.com/cb-craft/cb_annotation_ontology_api) | CC0 | RAST / SEED Subsystem Ontology (SSO). |
| `data/dictionaries/KO_dictionary.json` (~4 MB) | [KEGG Orthology](https://www.kegg.jp/kegg/ko.html) via KBase | KEGG academic-use license | Kanehisa & Goto. *KEGG: Kyoto Encyclopedia of Genes and Genomes.* Nucleic Acids Research 2000. |
| `data/dictionaries/SSO_reactions.json` (gold, 2,124 entries) | KBase | CC0 | curated SSO → ModelSEED reaction map used as ground truth in steps 04, 14, 17, 23, 25. |
| `data/dictionaries/kegg_95_0_ko_seed.tsv` (gold, 4,754 entries) | KBase | CC0 | curated KO → ModelSEED reaction map used as ground truth. |

## Implications for redistribution

- The `ontomap` codebase + LoRA adapters + multi-axis weights + cached SapBERT embeddings are **MIT** and freely redistributable.
- **MedCPT is the constraint** — NIH allows research use but not commercial redeployment of the model. If you intend to ship `ontomap` in a commercial product, replace MedCPT with an MIT-licensed cross-encoder (e.g., MS MARCO MiniLM-CE) and re-run step 18's fusion-weight sweep on Split-C.
- KEGG terms in the KO dictionary follow KEGG's academic-use policy. Mapping outputs ARE derivative works of KEGG when they reference KO ids — cite KEGG when publishing.
- ModelSEED, SSO, and the curated gold mappings are CC0 → no restrictions.

## Manifest

See `MANIFEST.txt` in this directory for SHA-256 + size of every bundled file. Verify a fresh copy:

```bash
cd ontomap && sha256sum -c weights/MANIFEST.txt   # standard *nix
# or
python -m ontomap.info --verify-manifest
```
