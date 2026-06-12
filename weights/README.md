# `ontomap/weights/` — bundled model artifacts (≈ 859 MB dereferenced)

This directory is **fully populated** when you receive the `ontomap/` folder
(via zip, tar, or `cp -RL` / `rsync -L`). No `fetch-models` call is required
for production inference. The `ontomap` CLI loads directly from these paths
on import.

## Layout

```
weights/
├── MANIFEST.txt          SHA-256 + size + upstream-source for every file in
│                         this directory + ../data/ — verify with sha256sum -c
├── LICENSES.md           upstream license attribution per artifact (read before
│                         redistributing — MedCPT is research-use only)
├── README.md             this file
│
├── sapbert/              base SapBERT encoder (UMLS-pretrained, 440 MB)
│   ├── config.json
│   ├── model.safetensors
│   ├── tokenizer_config.json
│   ├── vocab.txt
│   └── special_tokens_map.json
│       upstream: cambridgeltl/SapBERT-from-PubMedBERT-fulltext
│       revision SHA: 090663c3ae57bf35ffe4d0d468a2a88d03051a4d  (pinned)
│
├── medcpt/               MedCPT cross-encoder (440 MB)
│   ├── config.json
│   ├── pytorch_model.bin
│   ├── tokenizer.json + tokenizer_config.json + vocab.txt
│   └── special_tokens_map.json
│       upstream: ncbi/MedCPT-Cross-Encoder
│       revision SHA: 71caf65d4927987813984f54c284405a13fcca49  (pinned)
│
├── lora/
│   ├── sso/              SSO direction LoRA adapter (Split-C, ~11 MB)
│   │   ├── lora_adapter/ (subdir with adapter_config.json + adapter_model.safetensors)
│   │   ├── train_config.json    PEFT + MNRL hyperparams used to train it
│   │   └── val_metrics.json     Split-C validation metrics
│   └── ko/               KO direction LoRA adapter (Split-C, ~11 MB)
│       └── (same structure)
│
└── swept_weights.json    frozen multi-axis weights (per direction)
                          from step 01 coordinate descent
                          {nn=1.0, ech=0.75, ne=0.2, nq=0.5, ee=0, ep=0,
                           en=0, eq=0}, validated by step 08 4-fold CV
                          (<0.2 pp generalisation gap).
```

## Sister directory: `ontomap/data/` (≈ 473 MB dereferenced)

```
data/
├── embeddings/                          cached SapBERT corpus + source embeddings
│   ├── target_sapbert.npz               ~351 MB · ModelSEED NAME/EC/EQUATION/PATHWAY
│   ├── sso_source_sapbert.npz           ~11 MB
│   └── ko_source_sapbert.npz            ~25 MB
├── dictionaries/                        source ontology dictionaries (CC0 / KEGG-academic)
│   ├── SSO_dictionary.json              ~5 MB · RAST/BAKTA SSO terms
│   ├── KO_dictionary.json               ~4 MB · KEGG Orthology
│   ├── SSO_reactions.json               2,124 curated SSO → ModelSEED mappings (gold)
│   └── kegg_95_0_ko_seed.tsv            4,754 curated KO → ModelSEED mappings (gold)
└── modelseed_corpus/                    ~37 MB · 36,197 non-obsolete ModelSEED reactions
    ├── reactions.tsv
    ├── compounds.tsv
    └── Aliases/                         per-source-DB alias tables
```

> `ontomap` does **not** require the gold-mapping files (`SSO_reactions.json`,
> `kegg_95_0_ko_seed.tsv`) at inference time — they're bundled for transparency
> so a downstream researcher can reproduce the Split-C benchmark numbers and
> compare new pipeline runs against the same ground truth used in steps 17–26.

## Verification after copy / unzip

```bash
cd ontomap
sha256sum -c weights/MANIFEST.txt          # GNU coreutils
# or via the CLI
ontomap info --verify-manifest
```

The CLI walks every file in `MANIFEST.txt`, re-hashes it, compares, and prints
`OK` / `BAD` per row. Exit code is non-zero on any mismatch.

## How to (re-)fetch from upstream if you want fresh weights

If you want to update the bundled weights to a newer upstream revision:

```bash
# bumps the SapBERT + MedCPT snapshots in the HF cache and re-symlinks
ontomap fetch-models --force
# regenerate the manifest with new SHA-256s
ontomap info --rebuild-manifest
```

The LoRA adapters are project-trained on Split-C — to retrain on different
splits, see `workspace/17_sapbert_lora/scripts/17c_train_lora.py`.
