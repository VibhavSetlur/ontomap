# Installing `ontomap`

## TL;DR (fresh clone)

```bash
git clone https://github.com/VibhavSetlur/ontomap.git && cd ontomap
pip install -e .                          # editable install
bash scripts/setup.sh                     # fetch public assets: SapBERT + ModelSEED tables
ontomap version                           # 1.8.3
ontomap map-model --model your_model.json --output mapping.sqlite   # capability 1
```

This enables **capability 1 (model mapping)** from public assets only.
Letting **Claude Code** drive setup? See [`CLAUDE.md`](CLAUDE.md).

> Capability 2 (the SSO/KO/RAST → reaction `Pipeline`) additionally needs the
> LoRA adapters + SSO/KO dictionaries + cached embeddings, which are **not in
> the public repo** — see [`SETUP_ASSETS.md`](SETUP_ASSETS.md). The model
> mapping in capability 1 does **not** need them.

## Requirements

- **Python ≥ 3.10** (3.11 recommended; tested 3.10–3.12).
- **PyTorch ≥ 2.2** installed automatically. For CUDA support, pin to your CUDA version per the PyTorch site:
  ```bash
  pip install torch --index-url https://download.pytorch.org/whl/cu121
  ```
- **Disk space:** ~1.3 GB for the dereferenced bundle (~860 MB weights + ~470 MB data).
- **RAM:** ~4 GB minimum; ~8 GB comfortable.
- **GPU (optional):** any NVIDIA GPU with ≥ 8 GB VRAM speeds inference ~10×. CPU works fine for batch sizes < 100.

## Recommended: conda environment

```bash
conda create -n ontomap python=3.11 -y
conda activate ontomap
cd ontomap
pip install -e .
```

## Sharing / copying the folder

The preferred way to share is a **git clone + `bash scripts/setup.sh`** — the
small gold inputs (LoRA adapters, dictionaries, splits) ship in git as real
files, and `setup.sh` reconstructs the large fetched/computed assets (encoders,
ModelSEED corpus, embeddings cache). No symlink dereferencing needed.

If you instead copy a *populated* checkout directly (e.g. HPC-to-HPC, to skip
re-downloading the ~880 MB encoders), note that `download_models.py` links the
encoders into the HuggingFace cache — so dereference symlinks on copy:

```bash
# zip option — recipient untars and runs pip install -e .
tar -czhf ontomap-bundle.tar.gz ontomap/          # -h dereferences symlinks
# rsync option — for HPC-to-HPC transfer
rsync -avL ontomap/ user@dest:/path/ontomap/      # -L dereferences symlinks
# cp option — for same-machine relocation
cp -RL ontomap /destination/ontomap               # -L dereferences
```

Recipient then:

```bash
cd ontomap
pip install -e .
bash scripts/setup.sh               # fills in anything the copy missed (idempotent)
ontomap info --verify-manifest      # confirms every file matches its SHA-256
```

If `--verify-manifest` reports BAD or MISSING for any artifact, just re-run
`bash scripts/setup.sh` — it regenerates whatever is missing.

## With GPU FAISS (optional ~2× retrieval speedup)

```bash
pip install -e ".[gpu]"
```

## With SSSOM tooling (validators, converters)

```bash
pip install -e ".[sssom]"
```

## Air-gapped install (no internet at runtime OR install time)

The bundle is already air-gap-friendly — no model downloads needed. For install in an air-gapped env you also need transitive Python deps. Build a wheel cache on a connected machine:

```bash
# on a connected machine
pip download -r <(pip install --dry-run -e . 2>&1 | grep '^  ' | awk '{print $1}') -d wheels/
# ship wheels/ + ontomap/ together; on the target:
pip install --no-index --find-links wheels/ -e .
```

## Custom artifact location

If you want to share the python package separately from the weights/data (e.g., put the weights on shared storage and the package in each user's home):

```bash
export ONTOMAP_HOME=/shared/ontology-mapping/ontomap   # contains weights/ and data/
cd /home/user/ontomap-code
pip install -e .
ontomap info                                            # picks up ONTOMAP_HOME
```

## Troubleshooting

**`ontomap info` reports `INCOMPLETE bundle`** — one or more assets are missing or weren't fetched/computed yet. Fix: re-run `bash scripts/setup.sh` (idempotent — it regenerates only what's missing). If you relocated the folder, set `ONTOMAP_HOME` to point at the directory containing `weights/` and `data/`.

**`ModuleNotFoundError: faiss`** — `pip install faiss-cpu` (CPU) or `pip install faiss-gpu` (GPU).

**`CUDA out of memory`** — use `--device cpu`, or reduce MedCPT batch size with `--batch-size 16`.

**LoRA adapter not loading** — `ontomap info --verify-manifest` will identify the missing/corrupt file. If you trained your own LoRA, drop it at `weights/lora/{direction}/lora_adapter/` and re-run.

**Wrong Python version** — `ontomap` requires ≥ 3.10. Check with `python --version`.

## Verifying the install

```bash
ontomap info                              # quick: version, device, bundle presence, smoke test
ontomap info --verify-manifest            # thorough: SHA-256 every file (≈ 30 s for 1.2 GB)
ontomap map --sso SSO:000000027 --top-k 3 # real query
pytest -m smoke                           # 13 unit tests
bash examples/quickstart.sh               # 6-step end-to-end demo
```

If `ontomap info` reports `smoke-test FAIL`, file an issue with the full traceback.

## Uninstall

```bash
pip uninstall ontomap
# the bundle stays on disk where it was; delete it manually:
rm -rf /path/to/ontomap/
```
