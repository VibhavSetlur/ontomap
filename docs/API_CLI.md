# API and CLI

```python
from ontomap.api import map_batch, map_text
result = map_text("DNA repair helicase", method="go-text", version="1.0.0", top_k=20)
results = map_batch(["DNA repair helicase", "ATP synthase assembly"],
                    method="go-text", version="1.0.0", query_ids=["gene-1", "gene-2"], top_k=20)
```

`ontomap map --method go-text --text "DNA repair helicase" --top-k 20` emits JSON including ranked GO IDs, scores, and provenance.
GO accepts text only. The default `--method reaction` preserves the legacy reaction path.

`map_batch` preserves input order, generates `Q1`, `Q2`, ... identifiers when omitted, and applies the same structured validation as `map_text`.
