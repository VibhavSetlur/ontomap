"""Multi-source annotation TSV → ontomap-ready description file.

Built for the canonical bacterial-genome annotation dump shape:

    gene  source  ontology_term  description  reactions

…where the same gene appears once per annotation source (RAST, BAKTA, dram,
glm4ec, prokka, kofamscan, fitness_browser, COG, GO, EC, …), giving 10–14×
redundancy across descriptions. The `reactions` column is non-empty when
the source already proposed ModelSEED reactions (e.g. glm4ec EC-based,
dram KO-based, RAST/fitness_browser SSO-curated). These existing rows are
the partial gold standard against which ontomap predictions can be checked.

Two dedup modes:

  * `per-gene` (default) — one row per (gene, unique description). Use when
    you want a per-gene prediction and the analyst will collapse later.
  * `global` — one row per unique description, with the gene list as a
    semicolon-joined string. Use when you want to run ontomap once per
    unique description (cheapest pass; downstream re-attaches predictions
    to all genes that mention that description).

Both modes emit a sidecar JSONL with full provenance per (gene_or_id,
description) row: contributing sources, ontology terms attached by those
sources, and any reaction IDs the source already proposed.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

# Strings dropped under default `drop_trivial=True`. Lowercased compare.
TRIVIAL_DESCRIPTIONS = {
    "",
    "hypothetical protein",
    "putative protein",
    "protein of unknown function",
    "uncharacterized protein",
    "unknown",
    "unknown function",
    "n/a",
    "na",
    "none",
}


def _is_trivial(desc: str) -> bool:
    return (desc or "").strip().lower() in TRIVIAL_DESCRIPTIONS


def aggregate_annotation_tsv(
    input_path: Path,
    output_path: Path,
    provenance_path: Path | None = None,
    dedup_mode: str = "per-gene",
    drop_trivial: bool = True,
    gene_column: str = "gene",
    source_column: str = "source",
    description_column: str = "description",
    ontology_column: str = "ontology_term",
    reactions_column: str = "reactions",
) -> tuple[int, int, int]:
    """Aggregate a multi-source annotation TSV.

    Args:
        input_path: TSV with at minimum a gene + description column. Extra
            source/ontology/reactions columns enrich the provenance sidecar.
        output_path: clean TSV emitted for ontomap. Columns depend on
            `dedup_mode` — see module docstring.
        provenance_path: optional JSONL sidecar with full per-description
            source/gene/reactions provenance.
        dedup_mode: "per-gene" or "global". Default per-gene.
        drop_trivial: drop "hypothetical protein"-style rows (default True).
        gene_column / source_column / description_column / ontology_column /
            reactions_column: column-name overrides if your TSV uses different
            header names.

    Returns:
        (n_output_rows, n_unique_genes, n_provenance_records)
    """
    if dedup_mode not in ("per-gene", "global"):
        raise ValueError(f"dedup_mode must be 'per-gene' or 'global', got {dedup_mode!r}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if provenance_path:
        provenance_path.parent.mkdir(parents=True, exist_ok=True)

    # Provenance accumulator: keyed by (gene_or_id, description). Each entry
    # stores: gene(s), sources, ontology_terms, existing_reactions.
    provenance: dict[tuple[str, str], dict] = defaultdict(
        lambda: {
            "genes": set(),
            "sources": set(),
            "ontology_terms": set(),
            "existing_reactions": set(),
        }
    )

    rows_total = 0
    rows_kept = 0
    with input_path.open() as f:
        reader = csv.DictReader(f, delimiter="\t")
        if reader.fieldnames is None:
            raise ValueError(f"{input_path} has no header row")
        # Resolve columns
        missing = [c for c in (gene_column, description_column) if c not in reader.fieldnames]
        if missing:
            raise ValueError(
                f"{input_path} missing required columns: {missing} "
                f"(available: {reader.fieldnames})"
            )

        for row in reader:
            rows_total += 1
            desc = (row.get(description_column) or "").strip()
            if drop_trivial and _is_trivial(desc):
                continue
            if not desc:
                continue
            gene = (row.get(gene_column) or "").strip()
            source = (row.get(source_column) or "").strip()
            onto = (row.get(ontology_column) or "").strip()
            rxns_field = (row.get(reactions_column) or "").strip()
            rxns = [r.strip() for r in rxns_field.split(";") if r.strip()] if rxns_field else []

            if dedup_mode == "per-gene":
                key = (gene, desc)
            else:
                key = ("__ALL__", desc)

            entry = provenance[key]
            if gene:
                entry["genes"].add(gene)
            if source:
                entry["sources"].add(source)
            if onto:
                entry["ontology_terms"].add(onto)
            for r in rxns:
                entry["existing_reactions"].add(r)
            rows_kept += 1

    # Emit clean ontomap-ready TSV
    with output_path.open("w", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        if dedup_mode == "per-gene":
            writer.writerow(["id", "gene", "description", "n_sources", "has_existing_reactions"])
            for (gene, desc), entry in provenance.items():
                writer.writerow([
                    f"{gene}|{_safe_short(desc)}",
                    gene, desc,
                    len(entry["sources"]),
                    int(bool(entry["existing_reactions"])),
                ])
        else:
            writer.writerow(["id", "description", "n_genes", "n_sources", "has_existing_reactions"])
            for (_, desc), entry in provenance.items():
                writer.writerow([
                    f"DESC|{_safe_short(desc)}",
                    desc,
                    len(entry["genes"]),
                    len(entry["sources"]),
                    int(bool(entry["existing_reactions"])),
                ])

    if provenance_path:
        with provenance_path.open("w") as fout:
            for (gene_or_all, desc), entry in provenance.items():
                fout.write(json.dumps({
                    "id": (
                        f"{gene_or_all}|{_safe_short(desc)}"
                        if dedup_mode == "per-gene"
                        else f"DESC|{_safe_short(desc)}"
                    ),
                    "description": desc,
                    "gene": gene_or_all if dedup_mode == "per-gene" else None,
                    "genes": sorted(entry["genes"]),
                    "sources": sorted(entry["sources"]),
                    "ontology_terms": sorted(entry["ontology_terms"]),
                    "existing_reactions": sorted(entry["existing_reactions"]),
                }) + "\n")

    n_unique_genes = len({g for g, _ in provenance.keys()} - {"__ALL__"}) if dedup_mode == "per-gene" else \
        len({g for v in provenance.values() for g in v["genes"]})

    return len(provenance), n_unique_genes, rows_kept


def _safe_short(desc: str, max_len: int = 60) -> str:
    """Short, filesystem-safe slug for a description (used as id stem)."""
    s = "".join(c if c.isalnum() or c in "-_." else "_" for c in desc)
    s = "_".join(filter(None, s.split("_")))
    return s[:max_len]
