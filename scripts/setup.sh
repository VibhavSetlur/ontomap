#!/usr/bin/env bash
# scripts/setup.sh — one-shot bootstrap after cloning ontomap.
#
#   git clone https://github.com/VibhavSetlur/ontomap.git
#   cd ontomap
#   pip install -e .
#   bash scripts/setup.sh
#
# Fetches the PUBLIC assets needed for compound/reaction MODEL MAPPING
# (ontomap.modelmap, 1.5+): SapBERT weights (HuggingFace) + the ModelSEED
# biochemistry tables (GitHub). Idempotent. GPU optional (CPU ~10× slower).
#
# The SSO/KO/RAST → reaction Pipeline (the 1.x core) additionally needs the
# LoRA adapters + SSO/KO dictionaries + cached embeddings — see the optional
# section at the end and SETUP_ASSETS.md.
set -euo pipefail
cd "$(dirname "$0")/.."

MS_BASE="https://raw.githubusercontent.com/ModelSEED/ModelSEEDDatabase/master/Biochemistry"

echo "==> 1/3  SapBERT encoder weights (HuggingFace) ..."
python scripts/download_models.py || {
  echo "  ! download_models.py failed — ensure 'pip install huggingface_hub' and network access." >&2
  exit 1
}

echo
echo "==> 2/3  ModelSEED biochemistry tables -> data/modelseed/ ..."
mkdir -p data/modelseed
for tbl in compounds reactions; do
  if [ ! -s "data/modelseed/${tbl}.tsv" ]; then
    echo "  downloading ${tbl}.tsv ..."
    curl -fsSL -o "data/modelseed/${tbl}.tsv" "${MS_BASE}/${tbl}.tsv"
  else
    echo "  data/modelseed/${tbl}.tsv present — skip"
  fi
done

echo
echo "==> 3/3  Verify modelmap can read its assets ..."
python - <<'PY'
from ontomap.modelmap import load_compounds, load_reactions
nc = len(load_compounds()); nr = len(load_reactions())
assert nc > 30000 and nr > 40000, (nc, nr)
print(f"  ModelSEED loaded: {nc:,} compounds, {nr:,} reactions")
print("  modelmap assets OK.")
PY

echo
echo "============================================================"
echo "OK  ontomap.modelmap ready. Try:"
echo "    ontomap map-model --model your_model.json --output mapping.sqlite"
echo "  or, in Python:"
echo "    from ontomap import map_model_to_sqlite"
echo "    map_model_to_sqlite('your_model.json', path='mapping.sqlite')"
echo "============================================================"
echo
echo "Optional - enable the SSO/KO/RAST -> reaction Pipeline (1.x core):"
echo "  needs MedCPT + LoRA adapters + SSO/KO dictionaries + cached embeddings."
echo "  python scripts/build_corpus.py --patches   # ModelSEED corpus for the reaction pipeline"
echo "  python scripts/regen_embeddings.py         # cache SapBERT corpus embeddings (~30s on GPU)"
echo "  # LoRA adapters + SSO/KO dictionaries are NOT public - see SETUP_ASSETS.md."
