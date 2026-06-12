# ontomap examples

Runnable examples for the `ontomap` Python package (v1.3.0+). Each script is
self-contained — set `PYTHONPATH` or just run it: every script injects the
ontomap source dir on `sys.path` so it works whether you've `pip install -e`'d
the package or not.

All scripts require the bundled weights under
`/scratch/vsetlur/ontology-mapping/ontomap/weights/`. If you do not have them
locally, run `ontomap fetch-models` first (see `INSTALL.md`).

## Scripts

| file                          | what it shows                                                                                                  |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `quickstart.sh`               | CLI tour — single-query, batch CSV -> SSSOM / SQLite / per-query JSON dir, bundled-weight verification, bench. |
| `quickstart.py`               | Programmatic mirror of `quickstart.sh` — `map_one` + `map_batch` + all four output formats.                    |
| `01_text_input.py`            | Minimal: map 3 free-text annotations; print top-5 per query (`rxn_id`, name, EC, fused_score).                 |
| `02_ec_augment.py`            | v1.2.0 EC-augmented retrieval — same 3 descriptions run twice (`ec_augment=False` vs `True`), diff top-10.     |
| `03_batch_csv.py`             | Bulk path: read `sample_ids.csv`, map SSO ids, stream top-10 SSSOM-TSV to stdout. Shows `map_one` + `map_batch`. |
| `04_varied_inputs.py`         | Free-text input shapes the EC extractor handles: name-only, EC-only, name+EC, name+EC+notes.                   |
| `05_sqlite_output.py`         | `ontomap.io.write_sqlite` — normalised 3-table schema (`queries` / `predictions` / `reactions`) + view.        |
| `sample_ids.csv`              | 6 illustrative SSO ids used by `quickstart.sh` and `03_batch_csv.py`.                                          |

## Running

```bash
# Quickstart CLI tour
bash /scratch/vsetlur/ontology-mapping/ontomap/examples/quickstart.sh

# Individual Python examples (each is self-contained)
python /scratch/vsetlur/ontology-mapping/ontomap/examples/01_text_input.py
python /scratch/vsetlur/ontology-mapping/ontomap/examples/02_ec_augment.py
python /scratch/vsetlur/ontology-mapping/ontomap/examples/03_batch_csv.py > /tmp/batch.sssom.tsv
python /scratch/vsetlur/ontology-mapping/ontomap/examples/04_varied_inputs.py
python /scratch/vsetlur/ontology-mapping/ontomap/examples/05_sqlite_output.py
```
