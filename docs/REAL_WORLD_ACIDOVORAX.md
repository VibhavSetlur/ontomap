# Acidovorax-style fixture walkthrough

This is a reproducible **template** for an Acidovorax-style annotation table, not a claim that private or unavailable Acidovorax data is included. Substitute a table you are licensed to use and retain its source/provenance.

Expected columns are `gene`, `source`, `ontology_term`, `description`, and `reactions`. Aggregate redundant source rows into map-ready descriptions and a provenance sidecar:

```bash
ontomap aggregate-tsv --input annotations.tsv --output descriptions.tsv \
  --provenance descriptions.provenance.jsonl --dedup global
```

Then choose a workflow. Legacy reaction mapping uses descriptions to retrieve ModelSEED reactions (acquire ModelSEED separately):

```bash
ontomap map --method reaction --text-input descriptions.tsv \
  --id-column id --text-column description --output reaction_predictions.json
```

Text-to-GO mapping uses the same text column but a different method and target:

```bash
ontomap map --method go-text --text-input descriptions.tsv \
  --id-column id --text-column description --method-version 1.0.0 --output go_predictions.jsonl
```

Keep `descriptions.provenance.jsonl`, command versions, input hashes, method/version provenance, and external-data licenses with the outputs. Reaction candidates and GO candidates are not interchangeable; review them in the appropriate biological context. See [usage](USAGE.md) and [installation](INSTALL.md).
