"""Loaders for all data sources used in the pipeline.

Conventions:
- All loaders return plain Python dicts keyed by canonical ID.
- All IDs preserve original case and prefix (SSO:000..., rxn00..., sul00..., K00...).
- Source files are read from data/ground-truth/ (committed) and data/raw/modelseed/ (downloaded).
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Iterable

# `REPO_ROOT` is the ontomap distribution folder (the dir that holds
# `weights/`, `data/`, `scripts/`). From this file
# (ontomap/_helpers/ontomap_lib/data.py) that's three parents up.
REPO_ROOT = Path(__file__).resolve().parents[3]


def _first_existing(*candidates: Path) -> Path:
    """Return the first candidate path that exists, else the first candidate.

    Lets the loaders work across both the current bundled layout
    (`data/dictionaries/`, `data/modelseed_corpus/`) and the historical
    research-workspace layout (`data/ground-truth/`, `data/raw/modelseed/`)
    without requiring the runtime monkey-patch in `_frozen_runtime.py`.
    Honors `$ONTOMAP_HOME` so a relocated bundle still resolves.
    """
    import os as _os

    home = _os.environ.get("ONTOMAP_HOME")
    if home:
        candidates = (Path(home) / candidates[0].relative_to(REPO_ROOT),) + candidates
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


# Source dictionaries (SSO_dictionary.json, KO_dictionary.json, gold maps).
# Current bundled layout puts them in data/dictionaries/; the historical
# workspace layout used data/ground-truth/. Resolve whichever is present.
GROUND_TRUTH = _first_existing(
    REPO_ROOT / "data" / "dictionaries",
    REPO_ROOT / "data" / "ground-truth",
)
# ModelSEED corpus (reactions.tsv + Aliases/Unique_ModelSEED_*.txt). Current
# bundled layout is data/modelseed_corpus/; historical was data/raw/modelseed/.
MODELSEED_RAW = _first_existing(
    REPO_ROOT / "data" / "modelseed_corpus",
    REPO_ROOT / "data" / "raw" / "modelseed",
)

EC_PATTERN = re.compile(r"\b(\d+\.\d+\.\d+\.[\d\-]+)\b")


# ---------- SSO ----------

def load_sso_dictionary() -> dict[str, dict]:
    """Returns {SSO_id: {id, name, ...}} from SSO_dictionary.json."""
    with (GROUND_TRUTH / "SSO_dictionary.json").open() as f:
        d = json.load(f)
    return d["term_hash"]


def load_sso_reactions_gold() -> dict[str, list[str]]:
    """Returns {SSO_id: [rxn_id, ...]} ground truth."""
    with (GROUND_TRUTH / "SSO_reactions.json").open() as f:
        return json.load(f)


# ---------- KO ----------

def load_ko_dictionary() -> dict[str, dict]:
    """Returns {K_id: {id, name, ...}}."""
    with (GROUND_TRUTH / "KO_dictionary.json").open() as f:
        d = json.load(f)
    return d["term_hash"]


def load_kegg_ko_seed_gold() -> dict[str, dict]:
    """Returns {K_id: {seed_ids: [rxn...], definition: str, kegg_ids: [R...]}}."""
    out: dict[str, dict] = {}
    with (GROUND_TRUTH / "kegg_95_0_ko_seed.tsv").open() as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            ko = row["ko_id"]
            out[ko] = {
                "seed_ids": [s for s in (row.get("seed_ids") or "").split(";") if s],
                "definition": row.get("definition") or "",
                "kegg_ids": [s for s in (row.get("kegg_ids") or "").split(";") if s],
            }
    return out


# ---------- ModelSEED reactions ----------

def load_modelseed_reactions() -> dict[str, dict]:
    """Returns {rxn_id: {id, name, equation, definition, ec_numbers, status, is_obsolete, ...}}.

    Loads from data/raw/modelseed/reactions.tsv.
    """
    out: dict[str, dict] = {}
    with (MODELSEED_RAW / "reactions.tsv").open() as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            out[row["id"]] = row
    return out


def load_modelseed_reaction_ecs() -> dict[str, list[str]]:
    """Returns {rxn_id: [ec_strings]} from Aliases/Unique_ModelSEED_Reaction_ECs.txt."""
    out: dict[str, list[str]] = {}
    with (MODELSEED_RAW / "Aliases" / "Unique_ModelSEED_Reaction_ECs.txt").open() as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rxn = row["ModelSEED ID"]
            ec = row["External ID"]
            out.setdefault(rxn, []).append(ec)
    return out


def load_modelseed_reaction_pathways() -> dict[str, list[str]]:
    """Returns {rxn_id: [pathway_names]} merging across sources (MetaCyc, KEGG)."""
    out: dict[str, list[str]] = {}
    with (MODELSEED_RAW / "Aliases" / "Unique_ModelSEED_Reaction_Pathways.txt").open() as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rxn = row["ModelSEED ID"]
            pname = row["External ID"]
            out.setdefault(rxn, []).append(pname)
    return out


def load_modelseed_reaction_aliases() -> dict[str, dict[str, list[str]]]:
    """Returns {rxn_id: {source: [external_ids]}} e.g. {'rxn00001': {'KEGG': ['R00004']}}."""
    out: dict[str, dict[str, list[str]]] = {}
    with (MODELSEED_RAW / "Aliases" / "Unique_ModelSEED_Reaction_Aliases.txt").open() as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rxn = row["ModelSEED ID"]
            src = row["Source"]
            ext = row["External ID"]
            out.setdefault(rxn, {}).setdefault(src, []).append(ext)
    return out


def load_modelseed_reaction_names() -> dict[str, list[str]]:
    """Alternate names per reaction."""
    out: dict[str, list[str]] = {}
    with (MODELSEED_RAW / "Aliases" / "Unique_ModelSEED_Reaction_Names.txt").open() as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rxn = row["ModelSEED ID"]
            name = row["External ID"]
            out.setdefault(rxn, []).append(name)
    return out


# ---------- helpers ----------

def parse_ec_from_text(text: str) -> list[str]:
    """Extract EC numbers from a free-text string. Returns deduped list, preserving order."""
    if not text:
        return []
    seen: dict[str, None] = {}
    for m in EC_PATTERN.finditer(text):
        seen.setdefault(m.group(1), None)
    return list(seen.keys())


def is_multifunctional(role_name: str) -> bool:
    return " / " in role_name or " @ " in role_name


def is_transporter(role_name: str) -> bool:
    if not role_name:
        return False
    low = role_name.lower()
    return any(k in low for k in ("transporter", "permease", "abc transport", "porter "))


def is_hypothetical(role_name: str) -> bool:
    return bool(role_name) and "hypothetical" in role_name.lower()


def gold_bucket(size: int) -> str:
    if size <= 1:
        return "1"
    if size <= 5:
        return "2-5"
    if size <= 10:
        return "6-10"
    return "11+"


def stratify(role_name: str, gold_size: int) -> dict[str, str | bool]:
    return {
        "role_type": (
            "hypothetical" if is_hypothetical(role_name)
            else "transporter" if is_transporter(role_name)
            else "multifunction" if is_multifunctional(role_name)
            else "single-function"
        ),
        "gold_bucket": gold_bucket(gold_size),
        "ec_present": bool(parse_ec_from_text(role_name)),
    }


def iter_chunks(seq, n: int) -> Iterable[list]:
    buf = []
    for x in seq:
        buf.append(x)
        if len(buf) >= n:
            yield buf
            buf = []
    if buf:
        yield buf
