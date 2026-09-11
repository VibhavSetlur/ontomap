# Examples

The examples demonstrate the legacy reaction pipeline and require its configured local runtime assets and external ModelSEED data. Start with the offline GO quickstart in the repository [README](../README.md) when validating a fresh clone.

After setting up `.venv`, configuring `ONTOMAP_MODELSEED`, and acquiring permitted assets, run examples from the repository root:

```bash
.venv/bin/python examples/quickstart.py
.venv/bin/python examples/01_text_input.py
.venv/bin/python examples/02_ec_augment.py
.venv/bin/python examples/03_batch_csv.py
.venv/bin/python examples/04_varied_inputs.py
.venv/bin/python examples/05_sqlite_output.py
.venv/bin/python examples/06_map_published_model.py
```

`quickstart.sh` is a broader operator demo and writes temporary results under `/tmp`; review it before use. The scripts are examples, not a source of private data or a replacement for the current command reference. See [README](../README.md), [reference](../docs/REFERENCE.md), and [operations](../docs/OPERATIONS.md) for current command, asset, output, and provenance requirements.
