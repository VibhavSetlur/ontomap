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


## Filtered GO promotion and rollback

`ontomap/artifacts/filipe-go-filtered-v1/` is an immutable, manifest-verified filtered model bundle. It records the model, filter (`GO depth >= 2`), benchmark, output schema, and research-bundle provenance versions and checksums. `go-text@2.0.0` is the intentional default; select `go-text@1.0.0` to roll back without replacing either artifact. Both versions map arbitrary local text without identifiers, database access, or network access.
