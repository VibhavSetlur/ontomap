"""Bundled workspace step 17 + 18 helper modules + the project's src/ontomap library.

These are required by ontomap._frozen_runtime — DO NOT import these from
outside the package; use ontomap.Pipeline / ontomap.io instead.
"""
import sys as _sys
from pathlib import Path as _Path

# Make the bundled `ontomap_lib/` importable as a top-level package called
# `ontomap_lib` (distinct from the outer `ontomap` distribution package).
_HELPERS_DIR = _Path(__file__).resolve().parent
if str(_HELPERS_DIR) not in _sys.path:
    _sys.path.insert(0, str(_HELPERS_DIR))
