# Artifacts, security, and provenance

Each artifact manifest contains SHA-256 checksums and is verified before load. Filipe GO is a public-safe derived joblib
with training summary/configuration and accepted metrics; no raw data, private provenance, credentials, database, or Henry data is packaged.

## ModelSEED is acquire-only

No ModelSEED corpus record is distributed in this repository. `scripts/build_corpus.py` acquires an ignored external cache from
`ModelSEEDDatabase` commit `194ac8afe48f8a606c0dd07ba3c7af10c02ba2fd`, records source URLs and SHA-256 for every file in a local
manifest, and cites the upstream CC BY 4.0 license at
`https://raw.githubusercontent.com/ModelSEED/ModelSEEDDatabase/master/LICENSE`. The cache contains external records and is never
proof that a pre-existing local corpus matches that revision. Runtime selection requires `--modelseed-dir` or `ONTOMAP_MODELSEED`;
ordinary GO inference does not read or download it.


## GO promotion and rollback

`ontomap/artifacts/filipe-go-height-lte-1-dedup-v1/` is the immutable, manifest-verified `go-text@4.0.0` default. It records distinct model/config/split/metric checksums, filter ID `go-height-lte-1-v1`, dedup protocol, benchmark identity, compatibility, and provenance. GO **height** means distance to the furthest descendant: supplied rows with `height <= 1` were retained before entity joining, candidate selection, training, and deterministic deduplicated splitting; `height >= 2` rows were excluded. This is a training-only choice—runtime predictions are never height-filtered and use the filtered training vocabulary. `go-text@2.0.0` (prior depth model) and `go-text@3.0.0` (prior inverted-height model) are explicit immutable rollback versions; their weights are not replaced. All versions map arbitrary local text without identifiers, database access, or network access. Scores are uncalibrated held-out retrieval scores and do not establish transfer to Henry.
