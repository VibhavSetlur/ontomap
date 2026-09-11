# Asset licensing and attribution

OntoMap source code is distributed under the repository [LICENSE](../LICENSE). Model and data assets may carry additional upstream terms; confirm those terms before redistribution, commercial use, or deployment outside the intended research context.

- **ModelSEED records are external, acquire-only inputs.** They are not included in this repository. Obtain them from upstream with `scripts/build_corpus.py`, retain the upstream license/attribution, and do not treat this repository as permission to redistribute their corpus.
- **Runtime model assets** (including encoder/tokenizer dependencies) retain their upstream licenses. `ontomap fetch-models` and `weights/MANIFEST.txt` identify the installed assets; verify terms at their authoritative upstream sources.
- **GO artifacts** under `ontomap/artifacts/` are public-safe derived artifacts with manifests and provenance. They contain no raw private Filipe extracts or Henry data; their benchmark scores are descriptive and not calibrated probabilities.
- **KEGG/KO identifiers and other external ontology references** may have their own citation or reuse requirements. Preserve identifiers and provenance in derived outputs and consult the source policy when publishing or redistributing.

No license text in this guide grants access to credentials, private workbooks, restricted records, or third-party material. See [operations](../docs/OPERATIONS.md) for safe data handling and artifact verification.
