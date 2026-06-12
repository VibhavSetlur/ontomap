"""Frozen pipeline-3 runner — SapBERT-LoRA + multi-axis + MedCPT fused rerank.

This module wraps the workspace step 25/26 frozen pipeline as a clean,
importable, batched API for the CLI and programmatic use.

Implementation note (2026-06-10): the underlying pipeline helpers
currently live in workspace/22_hybrid_ensemble/scripts/22a_ensemble_pipeline.py
and workspace/17_sapbert_lora/scripts/17d_evaluate.py + step 18 18a_medcpt_rerank.py.
The step-25 agent factored the common parts into
`workspace/25_pipeline_3_frozen_gold_eval/scripts/_pipeline_3_runtime.py`.
Once Phase 8 wire-up lands, this module imports from it (or copies
the relevant functions verbatim into `ontomap/_frozen_runtime.py`).

The MapResult shape is the public contract for the rich JSON / SQLite /
SSSOM / Parquet outputs (see ontomap/io.py).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Literal

import numpy as np

Direction = Literal["sso", "ko"]
Device = Literal["cpu", "cuda", "auto"]

# σ values from step 18 Variant-C analysis (frozen).
SIGMA = {"sso": 0.3, "ko": 0.7}


@dataclass
class PipelineConfig:
    """Configuration knobs for the frozen pipeline. Mostly fixed at freeze time."""

    direction: Direction = "sso"
    device: Device = "auto"
    top_k_retrieve: int = 100         # FAISS top-N before rerank
    top_k_out: int = 100              # how many to return (≤ top_k_retrieve)
    medcpt_batch_size: int = 100
    sigma: float | None = None        # auto from direction if None
    weights_dir: Path | None = None   # bundled by default
    seed: int = 17
    ec_augment: bool = False          # v1.2.0 — merge EC-matched reactions into pool

    def resolved_sigma(self) -> float:
        return self.sigma if self.sigma is not None else SIGMA[self.direction]


@dataclass
class MapResult:
    """Result for one (query) → top-k reactions mapping.

    Public contract — every field here is surfaced in the rich JSON /
    SQLite / Parquet / SSSOM outputs, and any change is a breaking change.
    """

    # --- Required identity ---
    query_id: str
    direction: Direction

    # --- Source metadata (for downstream consumers) ---
    source_name: str | None = None
    source_ec: str | None = None
    source_def: str | None = None
    source_aliases: list[str] = field(default_factory=list)
    ontology_term: str | None = None
    """Original SSO or KO identifier used as the query (e.g. SSO:000010862, K05825).
    Populated when running in SSO/KO direction; None for free-text description queries."""

    # --- Ranking ---
    predictions: list[tuple[str, float]] = field(default_factory=list)
    """List of (reaction_id, fused_score) — length up to top_k_out (default 100)."""

    confidence_calibrated: list[float] = field(default_factory=list)
    """Calibrated probability per prediction (isotonic regression, per-direction)."""

    stage_scores: dict[str, dict[str, float]] = field(default_factory=dict)
    """Per-reaction extra-score breakdown — {reaction_id: {lora_norm, medcpt_norm}}.

    Lets researchers see why a candidate ranked where it did
    (LoRA vs MedCPT contribution before σ-fusion).
    """

    reaction_meta: dict[str, dict] = field(default_factory=dict)
    """Per-reaction metadata embedded in the result — {reaction_id: {name, ec_list,
    equation, pathway, alt_names, ec_match_level}}. Denormalised so a downstream
    consumer doesn't have to round-trip to ModelSEED.
    """

    # --- Runtime telemetry ---
    latency_ms: float = 0.0
    stage_breakdown_ms: dict[str, float] = field(default_factory=dict)
    """Per-stage wall-clock — {sapbert_lora_encode, faiss_retrieve, medcpt_rescore, fusion}."""
    cold: bool = False
    device: str = "cuda:0"

    # --- Soft-fail surface ---
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Quick dict for stdout streaming. For full output use ontomap.io._result_to_rich_dict."""
        return {
            "query_id": self.query_id,
            "direction": self.direction,
            "source_name": self.source_name,
            "source_ec": self.source_ec,
            "predictions": [
                {
                    "rank": i + 1,
                    "reaction_id": rxn,
                    "fused_score": float(score),
                    "confidence": float(self.confidence_calibrated[i]) if i < len(self.confidence_calibrated) else None,
                }
                for i, (rxn, score) in enumerate(self.predictions)
            ],
            "latency_ms": float(self.latency_ms),
            "cold": self.cold,
        }

    @property
    def top1(self) -> tuple[str, float] | None:
        return self.predictions[0] if self.predictions else None


class Pipeline:
    """Frozen pipeline-3 runner.

    Construct via `Pipeline.from_pretrained(direction='sso')`. After
    construction the encoder, LoRA adapter, FAISS index, MedCPT
    cross-encoder, and corpus embeddings are loaded into memory. Use
    `map_one` for single queries or `map_batch` for many.

    The first call to map_one/map_batch may be slow (cold cache).
    Subsequent calls share the loaded weights + indexes (warm cache).
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self._loaded = False

    @classmethod
    def from_pretrained(
        cls,
        direction: Direction = "sso",
        device: Device = "auto",
        weights_dir: Path | None = None,
        **kwargs,
    ) -> "Pipeline":
        cfg = PipelineConfig(direction=direction, device=device, weights_dir=weights_dir, **kwargs)
        pipe = cls(cfg)
        pipe.load()
        return pipe

    def load(self) -> None:
        """Load the bundled FrozenPipeline (SapBERT + LoRA + MedCPT + corpus). Idempotent."""
        if self._loaded:
            return
        from ontomap._frozen_runtime import FrozenPipeline
        self._impl = FrozenPipeline(direction=self.config.direction,
                                     device=self.config.device,
                                     ec_augment=self.config.ec_augment)
        self._impl.load()
        self._loaded = True

    def map_one(
        self,
        query_id: str,
        top_k: int | None = None,
    ) -> MapResult:
        """Map a single SSO or KO id to top-k ModelSEED reactions."""
        if not self._loaded:
            self.load()
        k = top_k if top_k is not None else self.config.top_k_out
        fr = self._impl.map_one(query_id, top_k=k)
        return _fr_to_mapresult(fr)

    def map_batch(
        self,
        query_ids: list[str],
        top_k: int | None = None,
        batch_size: int = 64,
        verbose: bool = True,
    ) -> list[MapResult]:
        """Map a list of ids. Returns one MapResult per input id, in order."""
        if not self._loaded:
            self.load()
        k = top_k if top_k is not None else self.config.top_k_out
        frs = self._impl.map_batch(query_ids, top_k=k, verbose=verbose)
        return [_fr_to_mapresult(fr) for fr in frs]

    def map_descriptions(
        self,
        descriptions: list[str],
        ids: list[str] | None = None,
        top_k: int | None = None,
        batch_size: int = 64,
        verbose: bool = True,
    ) -> list[MapResult]:
        """Map free-text functional descriptions to top-k ModelSEED reactions.

        For real-world annotation dumps (RAST / BAKTA / dram / Prokka /
        glm4ec / etc.) where source descriptions are free text rather than
        SSO/KO ids. Any `EC X.Y.Z[.W]` substring in the description is
        auto-extracted into the EC axis. The fused-score / confidence /
        reaction-metadata shape is identical to `map_batch`.

        Args:
            descriptions: list of free-text function names.
            ids: optional stable ids (synthetic `FREE:000NNNNN` ids assigned otherwise).
            top_k: number of candidates per query (default = config.top_k_out).
            verbose: progress logging.

        Returns: one `MapResult` per input description, in order.

        Example:
            >>> pipe = Pipeline.from_pretrained(direction="sso", device="cuda")
            >>> r = pipe.map_descriptions(
            ...     ["Enoyl-CoA hydratase (EC 4.2.1.17)"],
            ...     ids=["gene1"],
            ...     top_k=5,
            ... )[0]
            >>> r.top1
            ('rxn02167', 0.93...)
        """
        if not self._loaded:
            self.load()
        k = top_k if top_k is not None else self.config.top_k_out
        frs = self._impl.map_descriptions(
            descriptions, ids=ids, top_k=k, verbose=verbose
        )
        return [_fr_to_mapresult(fr) for fr in frs]

    def map(
        self,
        *,
        name: str | None = None,
        ec: str | None = None,
        notes: str | None = None,
        tags: list[str] | None = None,
        id: str | None = None,
        top_k: int | None = None,
        verbose: bool = False,
    ) -> "MapResult":
        """v1.4.0 — structured input convenience for a single query.

        Compose any combination of `name`, `ec`, `notes`, `tags` into the
        pipeline-friendly text the runtime expects. Accepts:

        - `name + ec`       → "Aldehyde dehydrogenase (EC 1.2.1.3)"
        - `name only`       → "Aldehyde dehydrogenase"
        - `ec only`         → "EC 1.2.1.3"
        - `name + ec + tags` → "Aldehyde dehydrogenase (EC 1.2.1.3) [putative; partial]"

        At least one of `name` or `ec` must be non-empty.

        Example:
            >>> pipe.map(name="Enoyl-CoA hydratase", ec="4.2.1.17", id="g1")
            MapResult(query_id='g1', predictions=[...], ...)
            >>> pipe.map(ec="1.2.1.3")          # EC only
            >>> pipe.map(name="aldehyde dehydrogenase")  # name only
            >>> pipe.map(name="...", ec="...", tags=["putative", "partial"])
        """
        parts = []
        if name and name.strip():
            parts.append(name.strip())
        if ec and ec.strip():
            ec = ec.strip()
            if not ec.lower().startswith("ec"):
                ec = f"EC {ec}"
            # if we already have a name, append EC as "(EC X.Y.Z)"
            if parts:
                parts[-1] = f"{parts[-1]} ({ec})"
            else:
                parts.append(ec)
        if tags:
            tag_text = "; ".join(t.strip() for t in tags if t and t.strip())
            if tag_text:
                parts.append(f"[{tag_text}]")
        if notes and notes.strip():
            parts.append(f"({notes.strip()})")
        if not parts:
            raise ValueError(
                "Pipeline.map requires at least one of name, ec, notes, tags to be non-empty"
            )
        text = " ".join(parts)
        results = self.map_descriptions(
            [text], ids=[id or "Q1"], top_k=top_k, verbose=verbose
        )
        return results[0]


def _fr_to_mapresult(fr) -> MapResult:
    """Convert _frozen_runtime.FrozenResult into the public MapResult shape."""
    return MapResult(
        query_id=fr.query_id,
        direction=fr.direction,
        source_name=fr.source_name,
        source_ec=fr.source_ec,
        source_def=fr.source_def,
        source_aliases=fr.source_aliases,
        ontology_term=getattr(fr, "ontology_term", None),
        predictions=fr.predictions,
        confidence_calibrated=[s for _, s in fr.predictions],  # placeholder — isotonic not yet wired
        stage_scores=fr.stage_scores,
        reaction_meta=fr.reaction_meta,
        latency_ms=fr.latency_ms,
        stage_breakdown_ms=fr.stage_breakdown_ms,
        cold=fr.cold,
        device=fr.device,
        warnings=fr.warnings,
    )
