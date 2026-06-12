#!/usr/bin/env bash
# scripts/setup.sh — one-shot bootstrap after `pip install -e .`
#
# After cloning the repo:
#   pip install -e .[dev]
#   bash scripts/setup.sh
#
# Total time: ~2 min on H100 + good network. Disk: ~2.5 GB.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> 1/3 Downloading SapBERT + MedCPT weights from HuggingFace ..."
python scripts/download_models.py

echo
echo "==> 2/3 Downloading ModelSEED corpus + applying EC patches ..."
python scripts/build_corpus.py --patches

echo
echo "==> 3/3 Regenerating SapBERT corpus + source embeddings ..."
python scripts/regen_embeddings.py

echo
echo "==> Verification:"
python -c "from ontomap import Pipeline, __version__; print(f'ontomap {__version__} loaded')"
python -c "
from ontomap import Pipeline
pipe = Pipeline.from_pretrained(direction='sso')
r = pipe.map_descriptions(['Enoyl-CoA hydratase (EC 4.2.1.17)'], ids=['demo'], top_k=3, verbose=False)[0]
print('Top-3:', [(rxn, round(s, 3)) for rxn, s in r.predictions[:3]])
"
echo
echo "✓ ontomap ready. See README.md and examples/ for usage."
