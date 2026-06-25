#!/usr/bin/env bash
# scripts/setup.sh — one-command bootstrap for a fresh ontomap clone.
#
#   git clone https://github.com/VibhavSetlur/ontology-mapping.git
#   cd ontology-mapping/ontomap
#   pip install -e .          # (or let step 1 below do it)
#   bash scripts/setup.sh
#
# After this finishes BOTH capabilities work from a clone with no maintainer
# hand-off:
#   1. model mapping   — ontomap map-model --model your_model.json -o out.sqlite
#   2. reaction pipeline — ontomap map --text "Enoyl-CoA hydratase (EC 4.2.1.17)"
#
# What it reconstructs (all from public sources + the small gold inputs that
# ship in git: data/dictionaries/, data/splits/, weights/lora/):
#   - SapBERT + MedCPT encoders  (HuggingFace, ~880 MB)  -> weights/{sapbert,medcpt}/
#   - ModelSEED biochemistry     (ModelSEED GitHub, ~37 MB) -> data/modelseed{,_corpus}/
#   - cached corpus embeddings   (computed locally, ~278 MB) -> data/embeddings/
#   - LoRA adapters              (committed; else retrained from data/splits/)
#
# Idempotent — safe to re-run. GPU optional (CPU works, ~10x slower). Pass
# --skip-reaction-pipeline to set up ONLY capability 1 (model mapping), which
# needs neither the embeddings cache nor the LoRA adapters.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"

SKIP_RXN=0
for arg in "$@"; do
  case "$arg" in
    --skip-reaction-pipeline) SKIP_RXN=1 ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
  esac
done

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
ok()   { printf '   \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '   \033[33m!\033[0m %s\n' "$*" >&2; }

# ---------------------------------------------------------------------------
say "1/6  Install the package (editable)"
if python -c "import ontomap" 2>/dev/null; then
  ok "ontomap importable — skipping pip install (re-run 'pip install -e .' if you changed pyproject)"
else
  pip install -e . || { warn "pip install -e . failed — install deps then re-run"; exit 1; }
  ok "installed"
fi

# ---------------------------------------------------------------------------
say "2/6  Encoder weights — SapBERT (+ MedCPT for the reaction pipeline)"
python scripts/download_models.py || {
  warn "download_models.py failed — ensure 'pip install huggingface_hub' + network access"
  exit 1
}
ok "encoders present under weights/"

# ---------------------------------------------------------------------------
say "3/6  ModelSEED biochemistry tables"
# (a) modelmap location: data/modelseed/{compounds,reactions}.tsv
mkdir -p data/modelseed
MS_BASE="https://raw.githubusercontent.com/ModelSEED/ModelSEEDDatabase/master/Biochemistry"
for tbl in compounds reactions; do
  if [ ! -s "data/modelseed/${tbl}.tsv" ]; then
    echo "   downloading ${tbl}.tsv …"
    curl -fsSL -o "data/modelseed/${tbl}.tsv" "${MS_BASE}/${tbl}.tsv"
  fi
done
# (b) reaction-pipeline corpus: data/modelseed_corpus/ (tables + Aliases/)
if [ "$SKIP_RXN" -eq 0 ]; then
  if [ ! -s "data/modelseed_corpus/reactions.tsv" ] || \
     [ ! -s "data/modelseed_corpus/Aliases/Unique_ModelSEED_Reaction_ECs.txt" ]; then
    echo "   building reaction-pipeline corpus (data/modelseed_corpus/ + Aliases/) …"
    python scripts/build_corpus.py --patches || warn "build_corpus.py failed (reaction pipeline corpus)"
  fi
fi
python - <<'PY'
from ontomap.modelmap import load_compounds, load_reactions
nc, nr = len(load_compounds()), len(load_reactions())
assert nc > 30000 and nr > 40000, (nc, nr)
print(f"   ModelSEED loaded: {nc:,} compounds, {nr:,} reactions")
PY
ok "ModelSEED tables ready"

if [ "$SKIP_RXN" -eq 1 ]; then
  say "Done (model mapping only)."
  cat <<'EOF'
   Capability 1 ready:
     ontomap map-model --model your_model.json --output mapping.sqlite
   To also enable the reaction pipeline, re-run without --skip-reaction-pipeline.
EOF
  exit 0
fi

# ---------------------------------------------------------------------------
say "4/6  LoRA adapters (reaction pipeline)"
NEED_TRAIN=0
for d in sso ko; do
  if [ -d "weights/lora/$d/lora_adapter" ] && [ -f "weights/lora/$d/lora_adapter/adapter_model.safetensors" ]; then
    ok "weights/lora/$d/lora_adapter present"
  else
    warn "weights/lora/$d/lora_adapter missing"
    NEED_TRAIN=1
  fi
done
if [ "$NEED_TRAIN" -eq 1 ]; then
  if [ -f "data/splits/sso_C.json" ] && [ -f "data/splits/ko_C.json" ]; then
    echo "   retraining missing adapter(s) from data/splits/ (~3-6 min/dir on GPU) …"
    python scripts/train_lora_from_splits.py --direction both ||
      warn "train_lora_from_splits.py failed — reaction pipeline will not load"
  else
    warn "data/splits/ missing — cannot retrain LoRA. Re-clone (splits ship in git) or see SETUP_ASSETS.md."
  fi
fi

# ---------------------------------------------------------------------------
say "5/6  Cached corpus embeddings (target_sapbert.npz)"
if [ -s "data/embeddings/target_sapbert.npz" ]; then
  ok "data/embeddings/target_sapbert.npz present"
else
  echo "   computing SapBERT corpus embeddings (~30s GPU / ~10min CPU) …"
  python scripts/regen_embeddings.py || warn "regen_embeddings.py failed"
fi

# ---------------------------------------------------------------------------
say "6/6  Verify"
ontomap info || warn "ontomap info reported problems (see above)"
echo
echo "============================================================"
echo "OK  ontomap ready. Try:"
echo "    ontomap map --text 'Enoyl-CoA hydratase (EC 4.2.1.17)'"
echo "    ontomap map-model --model your_model.json --output mapping.sqlite"
echo "============================================================"
