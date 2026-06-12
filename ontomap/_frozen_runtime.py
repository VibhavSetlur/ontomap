"""Pipeline_3 runtime — minimal wired implementation for the bundled ontomap.

Loads SapBERT (bundled local path), LoRA adapter (bundled), MedCPT (bundled),
cached source/target embeddings (bundled), and ModelSEED corpus metadata
(bundled), and runs the frozen pipeline_3 stack:

    Stage 1a: encode source axes (NAME + EC) with SapBERT-LoRA
    Stage 1b: multi-axis FAISS top-100 retrieval with frozen swept weights
    Stage 2:  MedCPT cross-encoder rerank with min-max σ-fusion → top-K

Stage 0 (no-LoRA baseline) and Stage 3 (Qwen LLM) are intentionally excluded.

Public entry point: `FrozenPipeline(direction, device).map_batch(query_ids, top_k)`.
"""

from __future__ import annotations

import importlib.util as _ilu
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ontomap import _paths

# Ensure bundled helpers + src/ontomap library are importable
from ontomap import _helpers  # noqa: F401  (side-effect: sys.path injection)


LOG = logging.getLogger("ontomap._frozen_runtime")

SIGMA = {"sso": 0.3, "ko": 0.7}
SWEPT = None  # lazy-loaded

# v1.1.0: EC-priority bonus added to fused score when query EC matches candidate EC.
# Default ON — validated as a free hit@1 / hit@10 upgrade on the multi-gold harness.
# Set OMAP_DISABLE_EC_PRIORITY=1 to disable.
import re as _re
_EC_RE = _re.compile(r"(?:EC[:\s]*)?(\d+\.\d+\.\d+(?:\.\d+)?)")
EC_PRIORITY_BONUS = 0.15
EC_PRIORITY_ENABLED = os.environ.get("OMAP_DISABLE_EC_PRIORITY", "0") != "1"

# v1.1.0: corpus EC patches. Auto-detected + hand-curated EC tags for
# ModelSEED reactions whose ec_numbers field is empty in the upstream corpus.
# Applied at corpus load time. See data/modelseed_corpus_patches.csv.
_EC_PATCH_CACHE: dict[str, str] | None = None


def _swept_weights() -> dict:
    global SWEPT
    if SWEPT is None:
        SWEPT = json.loads(_paths.swept_weights_path().read_text())
    return SWEPT


def _load_ec_patches() -> dict[str, str]:
    """Return {reaction_id: proposed_ec_string} from bundled patches CSV.

    Patches are applied non-destructively: only reactions whose corpus ec_numbers
    is empty receive the patched value (see step17_evaluate.encode_corpus_lora).
    """
    global _EC_PATCH_CACHE
    if _EC_PATCH_CACHE is not None:
        return _EC_PATCH_CACHE
    p = Path(__file__).parent.parent / "data" / "modelseed_corpus_patches.csv"
    out: dict[str, str] = {}
    if p.exists():
        with p.open() as f:
            next(f)  # header
            for line in f:
                cols = line.rstrip("\n").split(",")
                if len(cols) >= 3 and cols[0]:
                    out[cols[0]] = cols[2]
        LOG.info(f"loaded {len(out)} EC patches from {p.name}")
    _EC_PATCH_CACHE = out
    return out


def _extract_query_ecs(text: str) -> list[str]:
    """Extract EC numbers (3- or 4-level) from a query description."""
    if not text:
        return []
    return list(dict.fromkeys(e for e in _EC_RE.findall(text) if e.count(".") >= 2))


def _ec_match_bonus(query_ecs: list[str], cand_ec_str: str, bonus: float = EC_PRIORITY_BONUS) -> float:
    """Return `bonus` if any query EC substring-matches any candidate EC; else 0."""
    if not query_ecs or not cand_ec_str:
        return 0.0
    cand_ecs = str(cand_ec_str).split("|")
    for q in query_ecs:
        for c in cand_ecs:
            c = c.strip()
            if q and c and (q in c or c in q):
                return bonus
    return 0.0


def _ec_augmented_candidates(query_ecs: list[str], rxn_meta: dict, already: set, max_extra: int = 20) -> list[str]:
    """v1.2.0: find ModelSEED reactions whose ec_numbers substring-matches a
    query EC and that are NOT already in the candidate pool. Returns up to
    `max_extra` reaction IDs.

    Used by --ec-augment to broaden the candidate pool with EC-matched reactions
    that the SapBERT-LoRA NAME axis may have missed.
    """
    extras: list[str] = []
    for rxn_id, meta in rxn_meta.items():
        if rxn_id in already:
            continue
        cand_ec = (meta or {}).get("ec_numbers", "")
        if not cand_ec:
            continue
        cand_list = str(cand_ec).split("|")
        for q in query_ecs:
            for c in cand_list:
                c = c.strip()
                if q and c and (q in c or c in q):
                    extras.append(rxn_id)
                    if len(extras) >= max_extra:
                        return extras
                    break
            if extras and extras[-1] == rxn_id:
                break
    return extras


# ---------------------------------------------------------------------------
# Load bundled workspace helpers (step 17 eval + step 18 medcpt rerank)
# ---------------------------------------------------------------------------

def _load_helper_module(stem: str, file: str):
    p = _paths.package_root() / "_helpers" / file
    spec = _ilu.spec_from_file_location(stem, p)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Lazy import — heavy (pulls torch, sentence-transformers, transformers)
_step17 = None
_step18 = None
_ontomap_lib = None


def _step17_mod():
    global _step17
    if _step17 is None:
        _step17 = _load_helper_module("step17_evaluate", "step17_evaluate.py")
    return _step17


def _step18_mod():
    global _step18
    if _step18 is None:
        _step18 = _load_helper_module("step18_medcpt", "step18_medcpt.py")
    return _step18


def _modelseed_data():
    """Load ModelSEED corpus once. Uses bundled src/ontomap library via ontomap_lib."""
    global _ontomap_lib
    if _ontomap_lib is None:
        from ontomap_lib import data as _data  # type: ignore
        _ontomap_lib = _data
    return _ontomap_lib


# ---------------------------------------------------------------------------
# Source dictionary lookups
# ---------------------------------------------------------------------------

def _load_source_dict(direction: str) -> dict[str, dict]:
    """Load SSO or KO source dictionary (OBO-style JSON)."""
    path = _paths.dictionary_path(direction)
    raw = json.loads(path.read_text())
    return raw.get("term_hash", raw)


def _free_text_metadata(query_id: str, label: str) -> dict:
    """Metadata for a free-text description (no dictionary lookup).

    Extracts EC numbers from the description text via the same regex used for
    SSO labels. Returns the shape `_source_metadata` returns so downstream
    code does not branch on free-text vs id input.
    """
    import re
    ec_pat = re.compile(r"EC[:\s-]?(\d+\.\d+\.\d+\.\d+|\d+\.\d+\.\d+\.-)")
    ecs = list(dict.fromkeys(ec_pat.findall(label)))
    # Strip the EC tag from the human-readable name (encoder still gets it via the EC axis).
    name_clean = ec_pat.sub("", label).strip().rstrip("()").strip() or label
    return {
        "name": name_clean,
        "ec_list": ecs,
        "definition": label,
        "aliases": [],
    }


def _source_metadata(direction: str, query_id: str, src_dict: dict) -> dict:
    """Resolve canonical name + EC + definition for a source ID."""
    entry = src_dict.get(query_id)
    if entry is None:
        stripped = query_id.split(":")[-1]
        entry = src_dict.get(stripped)
    if entry is None:
        return {
            "name": query_id, "ec_list": [], "definition": None, "aliases": []
        }

    # OBO-style fields: name, def, synonym, xref (with EC: prefix), ...
    name = entry.get("name") or entry.get("label") or query_id
    definition = entry.get("def") or entry.get("definition") or entry.get("description")
    aliases = entry.get("synonym") or entry.get("synonyms") or []
    if isinstance(aliases, str):
        aliases = [aliases]

    # Extract EC numbers from name or xref fields
    import re
    ec_pat = re.compile(r"EC[:\s-]?(\d+\.\d+\.\d+\.\d+|\d+\.\d+\.\d+\.-)")
    ecs = []
    for src in [name, definition or ""] + list(aliases):
        ecs.extend(ec_pat.findall(str(src)))
    # Also check xrefs
    for xref in entry.get("xref") or []:
        if isinstance(xref, str) and xref.startswith("EC:"):
            ecs.append(xref[3:])
    ec_list = list(dict.fromkeys(ecs))

    return {
        "name": name,
        "ec_list": ec_list,
        "definition": definition,
        "aliases": list(aliases),
    }


# ---------------------------------------------------------------------------
# Result type — what map_one returns
# ---------------------------------------------------------------------------

@dataclass
class FrozenResult:
    query_id: str
    direction: str
    source_name: str | None = None
    source_ec: str | None = None
    source_def: str | None = None
    source_aliases: list[str] = field(default_factory=list)
    ontology_term: str | None = None
    predictions: list[tuple[str, float]] = field(default_factory=list)  # (rxn_id, fused_score)
    stage_scores: dict[str, dict[str, float]] = field(default_factory=dict)  # {rxn_id: {lora_norm, medcpt_norm}}
    reaction_meta: dict[str, dict] = field(default_factory=dict)
    latency_ms: float = 0.0
    stage_breakdown_ms: dict[str, float] = field(default_factory=dict)
    cold: bool = False
    device: str = "cuda:0"
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# The frozen pipeline
# ---------------------------------------------------------------------------

def _resolve_device(spec: str) -> str:
    if spec == "auto":
        try:
            import torch
            return "cuda:0" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"
    return spec


class FrozenPipeline:
    """Pipeline_3 frozen runtime — uses only bundled ontomap artifacts."""

    def __init__(self, direction: str, device: str = "auto", ec_augment: bool | None = None):
        assert direction in ("sso", "ko")
        self.direction = direction
        self.device = _resolve_device(device)
        self._loaded = False
        self._first_call = True

        # v1.2.0: EC-augmented retrieval. If ec_augment=None, defer to env
        # var OMAP_EC_AUGMENT (default off). Setting True explicitly overrides.
        if ec_augment is None:
            ec_augment = os.environ.get("OMAP_EC_AUGMENT", "0") == "1"
        self._ec_augment = bool(ec_augment)

        # Will be populated by .load()
        self._src_dict = None
        self._lora_model = None
        self._medcpt_model = None
        self._medcpt_tokenizer = None
        self._base_arrays = None        # SapBERT base corpus embedding cache
        self._corpus_text = None        # ModelSEED corpus text axes + ECs
        self._faiss_index = None
        self._labels = None             # source-id → human label

    def load(self) -> None:
        if self._loaded:
            return

        import torch
        s17 = _step17_mod()
        omd = _modelseed_data()

        # 1) source dict
        self._src_dict = _load_source_dict(self.direction)

        # 2) load base corpus + text axes (uses cached base SapBERT embeddings)
        # Step 17's load_base_cache reads from data/embeddings/multi_axis_sapbert/.
        # We bundle them at ontomap/data/embeddings/. Mirror the expected layout:
        bundled_emb = _paths.embeddings_dir()
        # Step 17's helper reads from PROJECT_ROOT/data/embeddings/multi_axis_sapbert/<dir>_source_sapbert.npz
        # We need to monkey-patch its EMB_BASE before invocation
        if hasattr(s17, "EMB_BASE"):
            s17.EMB_BASE = bundled_emb
        # Point the ModelSEED loaders at the bundled corpus. The bundled
        # `ontomap_lib/data.py` uses two module-level path attrs we override:
        #   - MODELSEED_RAW: reactions.tsv + Aliases/Unique_ModelSEED_*.txt
        #   - GROUND_TRUTH:  SSO_dictionary.json + KO_dictionary.json
        if hasattr(omd, "MODELSEED_RAW"):
            omd.MODELSEED_RAW = _paths.modelseed_corpus_dir()
        if hasattr(omd, "GROUND_TRUTH"):
            omd.GROUND_TRUTH = _paths.data_dir() / "dictionaries"

        # build_corpus_text + load_base_cache both read paths via module-level
        # globals (no positional args)
        corpus_text = s17.build_corpus_text()
        base_arrays = s17.load_base_cache()
        self._corpus_text = corpus_text
        self._base_arrays = base_arrays

        # 3) Load LoRA adapter. The bundled step17.load_lora_model expects the
        # PARENT directory of `lora_adapter/` and will append the suffix itself.
        # Bundled layout: weights/lora/{sso,ko}/lora_adapter/.
        lora_parent = _paths.lora_dir(self.direction)
        LOG.info(f"loading LoRA adapter from {lora_parent}/lora_adapter (base SapBERT bundled)")
        self._lora_model = s17.load_lora_model(lora_parent)
        if hasattr(self._lora_model, "to"):
            self._lora_model.to(self.device)

        # 4) Pre-encode the corpus under LoRA (one-time, ~30s on GPU)
        LOG.info("encoding ModelSEED corpus NAME+EC under LoRA (one-time)")
        tgt_name, tgt_ec, tgt_eq, tgt_pw, _ = s17.encode_corpus_lora(
            self._lora_model, corpus_text, base_arrays
        )
        self._tgt_axes = (tgt_name, tgt_ec, tgt_eq, tgt_pw)

        # 5) Build FAISS top-100 index on target NAME axis
        import faiss
        d = tgt_name.shape[1]
        index = faiss.IndexFlatIP(d)
        index.add(tgt_name.astype("float32"))
        self._faiss_index = index

        # 6) Load labels (source-id → human-readable name) from bundled splits
        labels_path = _paths.data_dir() / "splits" / f"{self.direction}_meta.json"
        if labels_path.exists():
            self._labels = json.loads(labels_path.read_text()).get("labels", {})
        else:
            self._labels = {}

        # 7) Load MedCPT
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
        medcpt_path = str(_paths.medcpt_dir())
        LOG.info(f"loading MedCPT from {medcpt_path}")
        self._medcpt_tokenizer = AutoTokenizer.from_pretrained(medcpt_path)
        self._medcpt_model = AutoModelForSequenceClassification.from_pretrained(medcpt_path)
        self._medcpt_model.to(self.device).eval()

        # 8) Cache reaction-metadata lookup (for predictions[*].reaction)
        # Step 17 corpus_text returns (ids, names, ecs, equations, pathways, ecs_raw)
        ids, names, ecs_text, eqs, pws, ecs_raw = corpus_text
        self._rxn_meta_by_id = {
            rid: {
                "name": names[i],
                "ec_list": ecs_raw[i] if ecs_raw else [],
                "equation": eqs[i],
                "pathway": [pws[i]] if pws[i] else [],
                "alt_names": [],
            }
            for i, rid in enumerate(ids)
        }

        self._loaded = True
        LOG.info(f"FrozenPipeline loaded · direction={self.direction} · device={self.device}")

    def map_one(self, query_id: str, top_k: int = 100) -> FrozenResult:
        if not self._loaded:
            self.load()
        return self.map_batch([query_id], top_k=top_k, verbose=False)[0]

    def map_descriptions(
        self,
        descriptions: list[str],
        ids: list[str] | None = None,
        top_k: int = 100,
        verbose: bool = True,
    ) -> list[FrozenResult]:
        """Map free-text functional descriptions to top-k ModelSEED reactions.

        Bypasses the SSO/KO dictionary lookup — the description text IS the
        source. Any embedded `EC X.Y.Z[.W]` substring is auto-extracted into
        the EC axis (same regex `render_source_axes` uses for SSO labels).

        Args:
            descriptions: free-text function names, e.g.
                ["Enoyl-CoA hydratase (EC 4.2.1.17)", "ABC transporter ATP-binding protein"].
            ids: optional caller-supplied stable ids. If omitted, synthetic ids
                "FREE:00000001", "FREE:00000002", ... are assigned.
            top_k: number of candidates per query.
            verbose: progress logging.

        Returns: one FrozenResult per input description, in order.
        """
        if not self._loaded:
            self.load()
        if ids is None:
            ids = [f"FREE:{i + 1:08d}" for i in range(len(descriptions))]
        if len(ids) != len(descriptions):
            raise ValueError(f"len(ids)={len(ids)} ≠ len(descriptions)={len(descriptions)}")
        labels = dict(zip(ids, descriptions))
        return self.map_batch(
            ids, top_k=top_k, verbose=verbose, source_labels=labels
        )

    def map_batch(
        self,
        query_ids: list[str],
        top_k: int = 100,
        verbose: bool = True,
        source_labels: dict[str, str] | None = None,
    ) -> list[FrozenResult]:
        """Run the frozen pipeline on a batch of source IDs.

        Args:
            query_ids: SSO/KO IDs to look up in the bundled dictionary, OR
                synthetic IDs paired with `source_labels` for free-text mode.
            source_labels: optional {id: label_text} overlay. When provided,
                the label text bypasses the dictionary lookup and goes directly
                through `render_source_axes`. Used by `map_descriptions`.
        """
        if not self._loaded:
            self.load()

        s17 = _step17_mod()
        s18 = _step18_mod()
        sigma = SIGMA[self.direction]
        weights = _swept_weights()[f"{self.direction}_swept_weights"]

        # Free-text mode: synthesise dict entries from labels so downstream
        # metadata lookups (source_name, MedCPT query text) all see the text.
        is_free_text = source_labels is not None
        if is_free_text:
            override_dict = {
                qid: {"name": txt} for qid, txt in source_labels.items()
            }
            meta_per_q = [
                _free_text_metadata(qid, source_labels[qid]) for qid in query_ids
            ]
            labels_for_encode = dict(source_labels)
        else:
            meta_per_q = [_source_metadata(self.direction, qid, self._src_dict) for qid in query_ids]
            labels_for_encode = self._labels

        # Step 17 encode_sources expects (model, source_ids, labels_dict). Use bundled labels if available.
        src_name, src_ec, src_ecs = s17.encode_sources(
            self._lora_model, query_ids, labels_for_encode
        )

        # 2) Multi-axis FAISS top-100 retrieve + rerank per source
        tgt_name, tgt_ec, tgt_eq, tgt_pw = self._tgt_axes
        ids, _, _, _, _, tgt_ecs_raw = self._corpus_text
        retrieved = s17.run_one_pipeline(
            src_name, src_ec, src_ecs,
            tgt_name, tgt_ec, tgt_eq, tgt_pw,
            tgt_ecs_raw, ids, weights,
            top_k_retrieve=100,
            top_k_out=100,
        )

        # 3) MedCPT cross-encoder rerank with σ-fusion
        results = []
        for i, qid in enumerate(query_ids):
            t0 = time.perf_counter()
            cand = retrieved[i]                       # list of (rxn_id, lora_score) length 100
            cand_rxns = [r for r, _ in cand]
            lora_scores = np.array([s for _, s in cand], dtype=np.float32)

            # Build MedCPT pair texts and score
            if is_free_text:
                src_entry = override_dict.get(qid, {})
            else:
                src_entry = self._src_dict.get(qid) or self._src_dict.get(qid.split(":")[-1]) or {}
            try:
                qtext = s18.build_source_text(self.direction, qid, src_entry)
            except Exception:
                qtext = meta_per_q[i]["name"]
            cand_texts = [
                s18.build_candidate_text(r, self._rxn_meta_by_id, {}, {}, {})
                for r in cand_rxns
            ]
            medcpt_scores = np.array(s18.score_pairs(
                self._medcpt_model, self._medcpt_tokenizer, self.device, qtext, cand_texts
            ), dtype=np.float32)

            # min-max normalise both signals and fuse
            def _mm(a):
                lo, hi = float(a.min()), float(a.max())
                return np.zeros_like(a) if hi - lo < 1e-9 else (a - lo) / (hi - lo)
            ln = _mm(lora_scores)
            mn = _mm(medcpt_scores)
            fused = sigma * ln + (1.0 - sigma) * mn

            # v1.1.0: EC-priority bonus — if query EC matches candidate EC,
            # add a small fixed boost to the fused score. Validated as a
            # +1pp hit@1 / +0.7pp frac@20 free upgrade.
            query_ecs = _extract_query_ecs(
                (meta_per_q[i].get("name") or "") if not is_free_text
                else override_dict.get(qid, {}).get("name", "")
            )
            if EC_PRIORITY_ENABLED and query_ecs:
                bonuses = np.array([
                    _ec_match_bonus(query_ecs, (self._rxn_meta_by_id.get(rxn_id, {}) or {}).get("ec_numbers", ""))
                    for rxn_id in cand_rxns
                ], dtype=np.float32)
                fused = fused + bonuses

            # v1.2.0: EC-augmented retrieval — optionally MERGE in candidates whose
            # ec_numbers exactly match the query EC but are NOT in the FAISS top-100.
            # Off by default; controlled by ec_augment kwarg or OMAP_EC_AUGMENT env var.
            if self._ec_augment and query_ecs:
                extra_rxns = _ec_augmented_candidates(
                    query_ecs, self._rxn_meta_by_id, set(cand_rxns), max_extra=20
                )
                if extra_rxns:
                    # Score extras with MedCPT (LoRA score = 0 — cold add)
                    extra_cand_texts = [
                        s18.build_candidate_text(r, self._rxn_meta_by_id, {}, {}, {})
                        for r in extra_rxns
                    ]
                    extra_med = np.array(s18.score_pairs(
                        self._medcpt_model, self._medcpt_tokenizer, self.device, qtext, extra_cand_texts
                    ), dtype=np.float32)
                    # min-max norm against original medcpt range
                    orig_lo, orig_hi = float(medcpt_scores.min()), float(medcpt_scores.max())
                    extra_med_norm = np.zeros_like(extra_med) if orig_hi - orig_lo < 1e-9 else (extra_med - orig_lo) / (orig_hi - orig_lo)
                    extra_med_norm = np.clip(extra_med_norm, 0.0, 1.0)
                    # extras get fused with lora_norm=0 + EC bonus (they DO match by construction)
                    extra_fused = (1 - sigma) * extra_med_norm + EC_PRIORITY_BONUS
                    fused = np.concatenate([fused, extra_fused])
                    cand_rxns = list(cand_rxns) + list(extra_rxns)
                    ln = np.concatenate([ln, np.zeros(len(extra_rxns), dtype=np.float32)])
                    mn = np.concatenate([mn, extra_med_norm])
            order = np.argsort(-fused)[:top_k]

            preds = [(cand_rxns[int(o)], float(fused[int(o)])) for o in order]
            stage_scores = {
                cand_rxns[int(o)]: {
                    "lora_norm": float(ln[int(o)]),
                    "medcpt_norm": float(mn[int(o)]),
                }
                for o in order
            }
            reaction_meta = {
                cand_rxns[int(o)]: self._rxn_meta_by_id.get(cand_rxns[int(o)], {})
                for o in order
            }
            elapsed_ms = (time.perf_counter() - t0) * 1000

            r = FrozenResult(
                query_id=qid,
                direction=self.direction,
                source_name=meta_per_q[i].get("name"),
                source_ec=";".join(meta_per_q[i].get("ec_list") or []) or None,
                source_def=meta_per_q[i].get("definition"),
                source_aliases=meta_per_q[i].get("aliases") or [],
                ontology_term=qid,  # SSO:xxx or Kxxxxx — the original ontology ID
                predictions=preds,
                stage_scores=stage_scores,
                reaction_meta=reaction_meta,
                latency_ms=elapsed_ms,
                cold=self._first_call,
                device=self.device,
            )
            self._first_call = False
            results.append(r)
            if verbose and (i + 1) % max(1, len(query_ids) // 20) == 0:
                pct = (i + 1) / len(query_ids) * 100
                print(f"\r  ontomap: {i + 1}/{len(query_ids)} ({pct:.0f}%)", end="", flush=True)
        if verbose:
            print()
        return results
