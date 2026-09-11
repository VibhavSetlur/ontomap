# Weight and artifact assets

`weights/` contains the repository's model-asset manifest and permitted checked-in runtime assets. It is not a ModelSEED distribution. Use `weights/MANIFEST.txt` with:

```bash
.venv/bin/ontomap info --verify-manifest
```

The versioned public-safe GO artifacts, manifests, preparation summaries, and metrics are under `ontomap/artifacts/`. Inspect their active selection through the registry rather than selecting files directly:

```bash
.venv/bin/ontomap describe go-text
.venv/bin/ontomap describe go-text --method-version 4.0.0
```

Runtime dependencies that are not present may be acquired with `ontomap fetch-models`. Keep downloaded caches outside source control. For ModelSEED setup, provenance, and deployment restrictions, see [operations](../docs/OPERATIONS.md). Licensing and redistribution conditions are summarized in [LICENSES.md](LICENSES.md).
