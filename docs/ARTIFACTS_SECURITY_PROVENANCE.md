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
