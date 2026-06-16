# Installing `ontomap`

## TL;DR (fresh clone)

```bash
git clone https://github.com/VibhavSetlur/ontomap.git && cd ontomap
pip install -e .                          # editable install
bash scripts/setup.sh                     # fetch public assets: SapBERT + ModelSEED tables
ontomap version                           # 1.5.1
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

The bundled `weights/` and `data/` directories use **relative-or-absolute symlinks** to keep the source-repo disk footprint small. When sharing, dereference them so the recipient gets real files:

```bash
# zip option (recommended) — recipient untars and runs pip install -e .
tar -czhf ontomap-v0.1.0.tar.gz ontomap/          # -h dereferences symlinks
# or
zip -r --symlinks  ontomap-v0.1.0-with-symlinks.zip ontomap/   # WRONG — preserves symlinks
zip -r            ontomap-v0.1.0.zip            ontomap/       # also wrong (zip silently follows by default but verify)

# rsync option — for HPC-to-HPC transfer
rsync -avL ontomap/ user@dest:/path/ontomap/      # -L dereferences symlinks

# cp option — for same-machine relocation
cp -RL ontomap /destination/ontomap               # -L dereferences
```

Recipient then:

```bash
cd ontomap
pip install -e .
ontomap info --verify-manifest      # confirms every file matches its SHA-256
```

If `--verify-manifest` reports BAD or MISSING for any artifact, the share failed (symlink not dereferenced, or partial copy). Re-share with `cp -RL` / `rsync -L` / `tar -czh`.

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

**`ontomap info` reports `INCOMPLETE bundle`** — the symlinks didn't resolve. Common cause: copied with `cp` instead of `cp -RL`. Re-copy with dereferencing, or set `ONTOMAP_HOME` to the original folder.

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
