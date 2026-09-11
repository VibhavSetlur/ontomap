# Public GO benchmark record

`filipe-go-v1.metrics.json` is a checked-in, public-safe metric record for the named artifact. The full source benchmark data is intentionally excluded from runtime and this repository.

Read the artifact manifest and metric record with the registry context:

```bash
.venv/bin/ontomap describe go-text --method-version 1.0.0
```

The metrics describe held-out retrieval for that immutable artifact; scores are not calibrated probabilities and do not establish performance on Henry, private data, or a new deployment population. Current default and rollback registry choices are documented in the repository [README](../../README.md) and [operations guide](../../docs/OPERATIONS.md).
