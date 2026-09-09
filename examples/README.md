# OntoMap examples

Examples are runnable from a checkout or installed environment; they do not require a machine-specific path. First follow [installation](../docs/INSTALL.md), activate `.venv`, and run commands from the repository root.

```bash
. .venv/bin/activate
bash examples/quickstart.sh
python examples/01_text_input.py
python examples/02_ec_augment.py
python examples/03_batch_csv.py > batch.sssom.tsv
python examples/04_varied_inputs.py
python examples/05_sqlite_output.py
```

The existing scripts demonstrate the legacy reaction workflow: IDs, descriptions, EC augmentation, batch input, SSSOM, and SQLite. They may require installed/bundled weights; use `ontomap fetch-models` and `ontomap info --verify-manifest` when appropriate.

For the registry text-to-GO workflow, use the CLI directly:

```bash
ontomap map --method go-text --text 'DNA repair helicase' --top-k 5
ontomap map --method go-text --text-input annotations.tsv \
  --id-column gene --text-column product --output go.jsonl
```

See [API and CLI](../docs/API_CLI.md) for options, output formats, and method versions; see [usage](../docs/USAGE.md) for output and provenance guidance.

| File | Demonstrates |
|---|---|
| `quickstart.sh` | legacy CLI tour and output formats |
| `quickstart.py` | legacy programmatic mapping |
| `01_text_input.py` | legacy free-text descriptions |
| `02_ec_augment.py` | legacy EC augmentation |
| `03_batch_csv.py` | legacy batch IDs and SSSOM |
| `04_varied_inputs.py` | legacy description shapes |
| `05_sqlite_output.py` | SQLite output |
| `sample_ids.csv` | illustrative SSO IDs |
