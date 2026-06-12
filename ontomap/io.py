"""Input + output format handlers for the ontomap CLI.

Inputs:  CSV, TSV, JSONL, JSON, Parquet, TXT (one id per line).
Outputs: SSSOM-TSV, JSON, JSONL, CSV, TSV, Parquet, **SQLite**, **directory**.

SQLite output:
  3 tables — queries (pk=query_id), predictions (pk=(query_id, rank)),
  reactions (pk=reaction_id). One foreign-key edge from predictions to
  both. Indices on predictions.reaction_id and queries.direction.

Directory output:
  One <query_id>.json file per query under output_dir/, plus a manifest
  pointing at the keys + pipeline version. Useful for huge batch runs
  where loading everything into one process is undesirable.

Richer JSON:
  Each prediction carries fused_score + confidence_calibrated +
  lora_score_norm + medcpt_score_norm + ec_match_level + predicate +
  embedded reaction metadata (name, EC list, equation, pathway, aliases).
  Top-100 by default; --top-k clips.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from typing import Iterable, Literal

InputFormat = Literal["csv", "tsv", "json", "jsonl", "parquet", "txt"]
OutputFormat = Literal[
    "sssom-tsv", "json", "jsonl", "csv", "tsv", "parquet", "sqlite", "dir",
]

# ---- format detection ----------------------------------------------------------


def detect_input_format(path: Path) -> InputFormat:
    s = path.name.lower()
    if s.endswith(".csv"): return "csv"
    if s.endswith(".tsv"): return "tsv"
    if s.endswith(".jsonl") or s.endswith(".ndjson"): return "jsonl"
    if s.endswith(".json"): return "json"
    if s.endswith(".parquet"): return "parquet"
    if s.endswith(".txt"): return "txt"
    raise ValueError(f"cannot detect input format from extension: {path.name}")


def detect_output_format(path: Path) -> OutputFormat:
    """Detect from extension. Directory paths → 'dir'. .sssom.tsv special-cased."""
    if path.is_dir() or (not path.suffix and not path.exists()):
        # No suffix and not an existing file → treat as directory target
        if not path.suffix:
            return "dir"
    s = path.name.lower()
    if s.endswith(".sssom.tsv"): return "sssom-tsv"
    if s.endswith(".tsv"): return "tsv"
    if s.endswith(".csv"): return "csv"
    if s.endswith(".jsonl") or s.endswith(".ndjson"): return "jsonl"
    if s.endswith(".json"): return "json"
    if s.endswith(".parquet"): return "parquet"
    if s.endswith(".sqlite") or s.endswith(".db") or s.endswith(".sqlite3"): return "sqlite"
    raise ValueError(f"cannot detect output format from extension: {path.name}")


# ---- input readers -------------------------------------------------------------


def read_ids(
    path: Path,
    id_column: str | None = None,
    input_format: InputFormat | None = None,
) -> list[str]:
    fmt = input_format or detect_input_format(path)
    if fmt == "txt":
        out: list[str] = []
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"): continue
            out.append(line)
        return out

    if fmt == "json":
        data = json.loads(path.read_text())
        if isinstance(data, list) and data and isinstance(data[0], str):
            return list(data)
        if isinstance(data, list) and data and isinstance(data[0], dict):
            col = id_column or _guess_id_column(list(data[0].keys()))
            return [str(r[col]) for r in data]
        raise ValueError("JSON input must be a list of strings or list of objects")

    if fmt == "jsonl":
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        if not rows: return []
        col = id_column or _guess_id_column(list(rows[0].keys()))
        return [str(r[col]) for r in rows]

    if fmt in ("csv", "tsv"):
        delim = "," if fmt == "csv" else "\t"
        with path.open() as f:
            reader = csv.DictReader(f, delimiter=delim)
            fieldnames = reader.fieldnames or []
            col = id_column or _guess_id_column(fieldnames)
            return [str(row[col]) for row in reader]

    if fmt == "parquet":
        try:
            import pyarrow.parquet as pq
        except ImportError as e:
            raise ImportError("install pyarrow to read parquet inputs") from e
        tbl = pq.read_table(path)
        col = id_column or _guess_id_column(tbl.column_names)
        return [str(v) for v in tbl.column(col).to_pylist()]

    raise ValueError(f"unsupported input format: {fmt}")


def _guess_id_column(columns: Iterable[str]) -> str:
    cols = list(columns)
    candidates = ["id", "sso_id", "ko_id", "source_id", "query_id", "input_id"]
    lower_map = {c.lower(): c for c in cols}
    for cand in candidates:
        if cand in lower_map: return lower_map[cand]
    if cols: return cols[0]
    raise ValueError("input file has no columns and --id-column was not provided")


def _guess_text_column(columns: Iterable[str]) -> str:
    cols = list(columns)
    candidates = [
        "description", "desc", "text", "function", "function_name",
        "annotation", "label", "name", "product",
    ]
    lower_map = {c.lower(): c for c in cols}
    for cand in candidates:
        if cand in lower_map: return lower_map[cand]
    raise ValueError(
        "could not auto-detect a description column; pass --text-column. "
        f"Available columns: {cols}"
    )


def read_descriptions(
    path: Path,
    text_column: str | None = None,
    id_column: str | None = None,
    input_format: InputFormat | None = None,
) -> tuple[list[str], list[str]]:
    """Read free-text descriptions (optionally with stable ids) from a file.

    Supports the same formats as `read_ids` plus per-row id+description
    extraction. Returns (descriptions, ids). If no id column is provided,
    synthetic `FREE:00000001`-style ids are generated.

    For TXT input each non-comment line IS one description (no id).
    """
    fmt = input_format or detect_input_format(path)

    def _finalize(descs: list[str], ids: list[str] | None) -> tuple[list[str], list[str]]:
        if ids is None or all(i in (None, "") for i in ids):
            ids = [f"FREE:{i + 1:08d}" for i in range(len(descs))]
        else:
            ids = [str(i) for i in ids]
        return descs, ids

    if fmt == "txt":
        descs: list[str] = []
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            descs.append(stripped)
        return _finalize(descs, None)

    if fmt == "json":
        data = json.loads(path.read_text())
        if isinstance(data, list) and data and isinstance(data[0], str):
            return _finalize(list(data), None)
        if isinstance(data, list) and data and isinstance(data[0], dict):
            tcol = text_column or _guess_text_column(list(data[0].keys()))
            descs = [str(r[tcol]) for r in data]
            ids = (
                [str(r.get(id_column)) for r in data]
                if id_column and id_column in data[0]
                else None
            )
            return _finalize(descs, ids)
        raise ValueError("JSON input must be a list of strings or list of objects")

    if fmt == "jsonl":
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        if not rows:
            return [], []
        tcol = text_column or _guess_text_column(list(rows[0].keys()))
        descs = [str(r[tcol]) for r in rows]
        ids = (
            [str(r.get(id_column)) for r in rows]
            if id_column and id_column in rows[0]
            else None
        )
        return _finalize(descs, ids)

    if fmt in ("csv", "tsv"):
        delim = "," if fmt == "csv" else "\t"
        with path.open() as f:
            reader = csv.DictReader(f, delimiter=delim)
            fieldnames = reader.fieldnames or []
            tcol = text_column or _guess_text_column(fieldnames)
            rows = list(reader)
        descs = [str(row[tcol]) for row in rows]
        ids = (
            [str(row.get(id_column, "")) for row in rows]
            if id_column and id_column in fieldnames
            else None
        )
        return _finalize(descs, ids)

    if fmt == "parquet":
        try:
            import pyarrow.parquet as pq
        except ImportError as e:
            raise ImportError("install pyarrow to read parquet inputs") from e
        tbl = pq.read_table(path)
        tcol = text_column or _guess_text_column(tbl.column_names)
        descs = [str(v) for v in tbl.column(tcol).to_pylist()]
        ids = (
            [str(v) for v in tbl.column(id_column).to_pylist()]
            if id_column and id_column in tbl.column_names
            else None
        )
        return _finalize(descs, ids)

    raise ValueError(f"unsupported input format for descriptions: {fmt}")


# ---- predicate bucketing -----------------------------------------------------


def confidence_to_predicate(conf: float) -> str:
    """SSSOM predicate bucketing — same thresholds as `src/ontomap/sssom.py`."""
    if conf >= 0.85: return "skos:exactMatch"
    if conf >= 0.65: return "skos:closeMatch"
    return "skos:relatedMatch"


# ---- output writers -----------------------------------------------------------


def write_results(
    results: list,
    path: Path,
    output_format: OutputFormat | None = None,
    direction: str = "sso",
    pipeline_version: str = "pipeline_3-v0.1.0",
) -> None:
    """Dispatch to the right writer based on output format."""
    fmt = output_format or detect_output_format(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "json":
        data = [_result_to_rich_dict(r, pipeline_version) for r in results]
        path.write_text(json.dumps(data, indent=2))
        return
    if fmt == "jsonl":
        with path.open("w") as f:
            for r in results:
                f.write(json.dumps(_result_to_rich_dict(r, pipeline_version)) + "\n")
        return
    if fmt in ("csv", "tsv"):
        _write_csv_tsv(results, path, "," if fmt == "csv" else "\t")
        return
    if fmt == "sssom-tsv":
        _write_sssom_tsv(results, path, direction, pipeline_version)
        return
    if fmt == "parquet":
        _write_parquet(results, path)
        return
    if fmt == "sqlite":
        write_sqlite(results, path, pipeline_version=pipeline_version)
        return
    if fmt == "dir":
        write_directory(results, path, pipeline_version=pipeline_version)
        return
    raise ValueError(f"unsupported output format: {fmt}")


# ---- rich JSON representation ------------------------------------------------


def _result_to_rich_dict(r, pipeline_version: str) -> dict:
    """Convert a MapResult to the rich, researcher-facing JSON shape.

    The shape is what `--format json` writes and what `dir` writes per-file.
    Includes pipeline provenance, per-stage timing, per-prediction reaction
    metadata + confidence + EC match level.
    """
    preds = []
    for rank, ((rxn_id, score), conf) in enumerate(
        zip(r.predictions, r.confidence_calibrated or [None] * len(r.predictions)),
        start=1,
    ):
        c = conf if conf is not None else float(score)
        meta = getattr(r, "reaction_meta", {}).get(rxn_id, {}) if hasattr(r, "reaction_meta") else {}
        scores_extra = getattr(r, "stage_scores", {}).get(rxn_id, {}) if hasattr(r, "stage_scores") else {}
        preds.append({
            "rank": rank,
            "reaction_id": rxn_id,
            "fused_score": round(float(score), 6),
            "confidence_calibrated": round(float(c), 6) if c is not None else None,
            "lora_score_norm": scores_extra.get("lora_norm"),
            "medcpt_score_norm": scores_extra.get("medcpt_norm"),
            "ec_match_level": meta.get("ec_match_level"),
            "predicate": confidence_to_predicate(float(c)) if c is not None else None,
            "reaction": {
                "name": meta.get("name"),
                "ec_list": meta.get("ec_list") or [],
                "equation": meta.get("equation"),
                "pathway": meta.get("pathway") or [],
                "alt_names": meta.get("alt_names") or [],
            },
        })

    return {
        "query": {
            "id": r.query_id,
            "direction": r.direction,
            "source_name": getattr(r, "source_name", None),
            "source_ec": getattr(r, "source_ec", None),
            "source_def": getattr(r, "source_def", None),
            "source_aliases": getattr(r, "source_aliases", None) or [],
        },
        "pipeline": {
            "version": pipeline_version,
            "components": ["SapBERT", "LoRA", "multi-axis-FAISS", "MedCPT-fused"],
            "top_k_retrieve": 100,
            "top_k_returned": len(r.predictions),
        },
        "runtime": {
            "wall_ms": round(float(r.latency_ms), 3),
            "stage_breakdown_ms": r.stage_breakdown_ms,
            "cold": bool(getattr(r, "cold", False)),
            "device": getattr(r, "device", "cuda:0"),
        },
        "predictions": preds,
        "warnings": r.warnings,
    }


# ---- CSV/TSV ---------------------------------------------------------------


def _write_csv_tsv(results, path: Path, delim: str) -> None:
    with path.open("w", newline="") as f:
        writer = csv.writer(f, delimiter=delim)
        writer.writerow([
            "query_id", "direction", "rank", "reaction_id",
            "reaction_name", "ec_list", "fused_score", "confidence",
            "predicate", "ec_match_level", "latency_ms",
        ])
        for r in results:
            for rank, ((rxn, score), conf) in enumerate(
                zip(r.predictions, r.confidence_calibrated or [None] * len(r.predictions)),
                start=1,
            ):
                meta = getattr(r, "reaction_meta", {}).get(rxn, {}) if hasattr(r, "reaction_meta") else {}
                c = conf if conf is not None else float(score)
                writer.writerow([
                    r.query_id, r.direction, rank, rxn,
                    meta.get("name", ""),
                    ";".join(meta.get("ec_list") or []),
                    f"{float(score):.6f}",
                    f"{float(c):.6f}" if c is not None else "",
                    confidence_to_predicate(float(c)) if c is not None else "",
                    meta.get("ec_match_level", ""),
                    f"{r.latency_ms:.3f}",
                ])


# ---- Parquet ---------------------------------------------------------------


def _write_parquet(results, path: Path) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as e:
        raise ImportError("install pyarrow to write parquet outputs") from e
    rows = []
    for r in results:
        for rank, ((rxn, score), conf) in enumerate(
            zip(r.predictions, r.confidence_calibrated or [None] * len(r.predictions)),
            start=1,
        ):
            meta = getattr(r, "reaction_meta", {}).get(rxn, {}) if hasattr(r, "reaction_meta") else {}
            c = conf if conf is not None else float(score)
            rows.append({
                "query_id": r.query_id,
                "direction": r.direction,
                "rank": rank,
                "reaction_id": rxn,
                "reaction_name": meta.get("name"),
                "ec_list": ";".join(meta.get("ec_list") or []),
                "fused_score": float(score),
                "confidence": float(c) if c is not None else None,
                "predicate": confidence_to_predicate(float(c)) if c is not None else None,
                "ec_match_level": meta.get("ec_match_level"),
                "latency_ms": float(r.latency_ms),
            })
    pq.write_table(pa.Table.from_pylist(rows), path)


# ---- SSSOM ----------------------------------------------------------------


def _write_sssom_tsv(results, path: Path, direction: str, pipeline_version: str) -> None:
    """Emit minimal SSSOM-TSV (Matentzoglu et al. 2022)."""
    header = [
        "# curie_map:",
        "#   ontomap: https://github.com/VibhavSetlur/ontology-mapping/",
        "#   ModelSEED: https://modelseed.org/",
        "#   SSO: https://kbase.us/SSO/",
        "#   KO: https://www.kegg.jp/entry/",
        f"# mapping_set_id: ontomap-{pipeline_version}-{direction}",
        f"# mapping_set_version: {pipeline_version}",
        "# mapping_tool: ontomap pipeline_3 (SapBERT-LoRA + multi-axis + MedCPT fused)",
    ]
    cols = [
        "subject_id", "subject_label", "predicate_id",
        "object_id", "object_label",
        "mapping_justification", "confidence", "rank",
    ]
    with path.open("w") as f:
        for line in header: f.write(line + "\n")
        f.write("\t".join(cols) + "\n")
        for r in results:
            for rank, ((rxn, score), conf) in enumerate(
                zip(r.predictions, r.confidence_calibrated or [None] * len(r.predictions)),
                start=1,
            ):
                meta = getattr(r, "reaction_meta", {}).get(rxn, {}) if hasattr(r, "reaction_meta") else {}
                c = conf if conf is not None else float(score)
                f.write("\t".join([
                    r.query_id, getattr(r, "source_name", "") or "",
                    confidence_to_predicate(float(c)),
                    rxn, meta.get("name") or "",
                    "semapv:LexicalMatching",
                    f"{c:.4f}",
                    str(rank),
                ]) + "\n")


# ---- SQLite ----------------------------------------------------------------


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS queries (
  query_id          TEXT    PRIMARY KEY,
  direction         TEXT    NOT NULL,
  source_name       TEXT,
  source_ec         TEXT,
  source_def        TEXT,
  source_aliases    TEXT,
  ontology_term     TEXT,
  timestamp_utc     TEXT    NOT NULL,
  n_candidates      INTEGER NOT NULL,
  pipeline_version  TEXT    NOT NULL,
  latency_ms        REAL    NOT NULL,
  cold              INTEGER NOT NULL,
  device            TEXT
);

CREATE TABLE IF NOT EXISTS predictions (
  query_id              TEXT    NOT NULL,
  rank                  INTEGER NOT NULL,
  reaction_id           TEXT    NOT NULL,
  fused_score           REAL    NOT NULL,
  confidence_calibrated REAL,
  lora_score_norm       REAL,
  medcpt_score_norm     REAL,
  ec_match_level        INTEGER,
  predicate             TEXT,
  PRIMARY KEY (query_id, rank),
  FOREIGN KEY (query_id)    REFERENCES queries(query_id),
  FOREIGN KEY (reaction_id) REFERENCES reactions(reaction_id)
);

CREATE TABLE IF NOT EXISTS reactions (
  reaction_id  TEXT PRIMARY KEY,
  name         TEXT,
  ec_list      TEXT,
  equation     TEXT,
  pathway      TEXT,
  alt_names    TEXT,
  source_db    TEXT DEFAULT 'ModelSEED'
);

CREATE INDEX IF NOT EXISTS idx_predictions_reaction ON predictions(reaction_id);
CREATE INDEX IF NOT EXISTS idx_predictions_query    ON predictions(query_id);
CREATE INDEX IF NOT EXISTS idx_queries_direction    ON queries(direction);

CREATE VIEW IF NOT EXISTS top_n_with_meta AS
SELECT q.query_id, q.direction, q.source_name, q.source_ec,
       p.rank, p.reaction_id, p.fused_score, p.confidence_calibrated,
       p.predicate, p.ec_match_level,
       r.name AS reaction_name, r.ec_list, r.equation, r.pathway
FROM queries q
JOIN predictions p ON q.query_id = p.query_id
JOIN reactions   r ON p.reaction_id = r.reaction_id
ORDER BY q.query_id, p.rank;
"""


def write_sqlite(results, path: Path, pipeline_version: str = "pipeline_3-v0.1.0") -> None:
    """Persist results to a SQLite database (3-table schema + a convenience view)."""
    import datetime
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(SQLITE_SCHEMA)

        # Pre-collect reaction rows (dedup across queries)
        rxn_rows: dict[str, tuple] = {}
        q_rows = []
        p_rows = []
        for r in results:
            q_rows.append((
                r.query_id, r.direction,
                getattr(r, "source_name", None),
                getattr(r, "source_ec", None),
                getattr(r, "source_def", None),
                "|".join(getattr(r, "source_aliases", None) or []) or None,
                getattr(r, "ontology_term", None),
                timestamp,
                len(r.predictions),
                pipeline_version,
                float(r.latency_ms),
                int(bool(getattr(r, "cold", False))),
                getattr(r, "device", "cuda:0"),
            ))
            for rank, ((rxn, score), conf) in enumerate(
                zip(r.predictions, r.confidence_calibrated or [None] * len(r.predictions)),
                start=1,
            ):
                meta = getattr(r, "reaction_meta", {}).get(rxn, {}) if hasattr(r, "reaction_meta") else {}
                stage = getattr(r, "stage_scores", {}).get(rxn, {}) if hasattr(r, "stage_scores") else {}
                c = conf if conf is not None else float(score)
                p_rows.append((
                    r.query_id, rank, rxn,
                    float(score),
                    float(c) if c is not None else None,
                    stage.get("lora_norm"),
                    stage.get("medcpt_norm"),
                    meta.get("ec_match_level"),
                    confidence_to_predicate(float(c)) if c is not None else None,
                ))
                if rxn not in rxn_rows:
                    rxn_rows[rxn] = (
                        rxn,
                        meta.get("name"),
                        ";".join(meta.get("ec_list") or []) or None,
                        meta.get("equation"),
                        ";".join(meta.get("pathway") or []) or None,
                        "|".join(meta.get("alt_names") or []) or None,
                        "ModelSEED",
                    )

        conn.executemany(
            "INSERT OR REPLACE INTO reactions VALUES (?,?,?,?,?,?,?)",
            list(rxn_rows.values()),
        )
        conn.executemany(
            "INSERT OR REPLACE INTO queries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            q_rows,
        )
        conn.executemany(
            "INSERT OR REPLACE INTO predictions VALUES (?,?,?,?,?,?,?,?,?)",
            p_rows,
        )
        conn.commit()
    finally:
        conn.close()


# ---- Annotated SQLite (enriched deliverable) ------------------------------


ANNOTATED_SCHEMA_EXTRA = """
CREATE TABLE IF NOT EXISTS genomes (
  genome_id        TEXT PRIMARY KEY,
  name             TEXT,
  source_tsv       TEXT,
  n_genes          INTEGER,
  n_descriptions   INTEGER,
  n_annotations    INTEGER,
  notes            TEXT
);

CREATE TABLE IF NOT EXISTS genes (
  gene_id    TEXT PRIMARY KEY,
  genome_id  TEXT NOT NULL,
  FOREIGN KEY (genome_id) REFERENCES genomes(genome_id)
);

CREATE TABLE IF NOT EXISTS annotation_sources (
  source_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  source_name  TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS descriptions (
  description_id          TEXT PRIMARY KEY,
  description             TEXT NOT NULL,
  n_genes                 INTEGER,
  n_sources               INTEGER,
  has_existing_reactions  INTEGER,
  FOREIGN KEY (description_id) REFERENCES queries(query_id)
);

CREATE TABLE IF NOT EXISTS annotations (
  annotation_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  genome_id       TEXT NOT NULL,
  gene_id         TEXT NOT NULL,
  source_id       INTEGER NOT NULL,
  ontology_term   TEXT,
  description_id  TEXT,
  raw_reactions   TEXT,
  FOREIGN KEY (genome_id)      REFERENCES genomes(genome_id),
  FOREIGN KEY (gene_id)        REFERENCES genes(gene_id),
  FOREIGN KEY (source_id)      REFERENCES annotation_sources(source_id),
  FOREIGN KEY (description_id) REFERENCES descriptions(description_id)
);

CREATE TABLE IF NOT EXISTS existing_reactions (
  description_id  TEXT NOT NULL,
  reaction_id     TEXT NOT NULL,
  PRIMARY KEY (description_id, reaction_id),
  FOREIGN KEY (description_id) REFERENCES descriptions(description_id)
);

CREATE INDEX IF NOT EXISTS idx_genes_genome           ON genes(genome_id);
CREATE INDEX IF NOT EXISTS idx_annotations_gene       ON annotations(gene_id);
CREATE INDEX IF NOT EXISTS idx_annotations_source     ON annotations(source_id);
CREATE INDEX IF NOT EXISTS idx_annotations_desc       ON annotations(description_id);
CREATE INDEX IF NOT EXISTS idx_annotations_genome     ON annotations(genome_id);
CREATE INDEX IF NOT EXISTS idx_existing_reactions_rxn ON existing_reactions(reaction_id);

CREATE VIEW IF NOT EXISTS description_context AS
SELECT d.description_id, d.description, d.n_genes, d.n_sources, d.has_existing_reactions,
       (SELECT GROUP_CONCAT(DISTINCT a.gene_id)
          FROM annotations a WHERE a.description_id = d.description_id) AS genes,
       (SELECT GROUP_CONCAT(DISTINCT s.source_name)
          FROM annotations a
          JOIN annotation_sources s ON a.source_id = s.source_id
          WHERE a.description_id = d.description_id) AS sources,
       (SELECT GROUP_CONCAT(DISTINCT a.ontology_term)
          FROM annotations a
          WHERE a.description_id = d.description_id AND a.ontology_term IS NOT NULL) AS ontology_terms,
       (SELECT GROUP_CONCAT(er.reaction_id)
          FROM existing_reactions er WHERE er.description_id = d.description_id) AS existing_reactions
FROM descriptions d;

CREATE VIEW IF NOT EXISTS prediction_full AS
SELECT d.description_id, d.description,
       p.rank, p.reaction_id, p.fused_score, p.confidence_calibrated, p.predicate,
       p.lora_score_norm, p.medcpt_score_norm, p.ec_match_level,
       r.name AS reaction_name, r.ec_list, r.equation, r.pathway, r.alt_names,
       (SELECT GROUP_CONCAT(DISTINCT a.gene_id)
          FROM annotations a WHERE a.description_id = d.description_id) AS genes,
       (SELECT GROUP_CONCAT(DISTINCT s.source_name)
          FROM annotations a
          JOIN annotation_sources s ON a.source_id = s.source_id
          WHERE a.description_id = d.description_id) AS sources
FROM descriptions d
JOIN predictions p ON d.description_id = p.query_id
JOIN reactions   r ON p.reaction_id    = r.reaction_id
ORDER BY d.description_id, p.rank;
"""


def write_annotated_sqlite(
    results,
    annotation_tsv: Path,
    provenance_jsonl: Path,
    out_path: Path,
    genome_id: str,
    genome_name: str | None = None,
    pipeline_version: str = "pipeline_3-v0.1.0",
) -> dict:
    """Write a self-contained deliverable SQLite that combines:

    1. Core ontomap output (queries, predictions, reactions + top_n_with_meta view)
    2. Annotation context from the raw TSV (genomes, genes, annotation_sources,
       descriptions, annotations, existing_reactions)
    3. Convenience views (description_context, prediction_full)

    Args:
        results: list of MapResult from Pipeline.map_descriptions(...)
        annotation_tsv: raw input TSV with columns
            gene, source, ontology_term, description, reactions
        provenance_jsonl: per-description provenance file produced by
            ontomap.aggregate.aggregate_annotation_tsv (one JSON record per
            description with keys: id, description, genes, sources,
            ontology_terms, existing_reactions)
        out_path: destination .sqlite path
        genome_id: short id stored on genomes table and every annotation row
        genome_name: optional human-readable name
        pipeline_version: stored on every query row for provenance

    Returns: dict with per-table row counts.
    """
    import datetime
    write_sqlite(results, out_path, pipeline_version=pipeline_version)
    conn = sqlite3.connect(str(out_path))
    try:
        conn.executescript(ANNOTATED_SCHEMA_EXTRA)
        # 1) load provenance: description_id -> {description, n_genes, n_sources, existing_reactions}
        desc_rows: list[tuple] = []
        existing_pairs: list[tuple] = []
        gene_set: set[str] = set()
        with open(provenance_jsonl) as fh:
            for line in fh:
                rec = json.loads(line)
                did = rec["id"]
                desc_rows.append((
                    did, rec.get("description", ""),
                    len(rec.get("genes") or []),
                    len(rec.get("sources") or []),
                    int(bool(rec.get("existing_reactions") or [])),
                ))
                for rxn in (rec.get("existing_reactions") or []):
                    existing_pairs.append((did, rxn))
                for g in (rec.get("genes") or []):
                    gene_set.add(g)
        conn.executemany(
            "INSERT OR REPLACE INTO descriptions VALUES (?,?,?,?,?)",
            desc_rows,
        )
        conn.executemany(
            "INSERT OR REPLACE INTO existing_reactions VALUES (?,?)",
            existing_pairs,
        )
        # 2) load raw TSV → annotations + sources + genes
        source_id_cache: dict[str, int] = {}
        def _source_id(name: str) -> int:
            sid = source_id_cache.get(name)
            if sid is not None:
                return sid
            cur = conn.execute("INSERT OR IGNORE INTO annotation_sources(source_name) VALUES (?)", (name,))
            sid = cur.lastrowid or conn.execute(
                "SELECT source_id FROM annotation_sources WHERE source_name = ?", (name,)
            ).fetchone()[0]
            source_id_cache[name] = sid
            return sid

        # description text → description_id reverse lookup
        text_to_did = {d[1]: d[0] for d in desc_rows}

        ann_rows: list[tuple] = []
        n_ann = 0
        with open(annotation_tsv) as fh:
            header = fh.readline().rstrip("\n").split("\t")
            # tolerate column-order shifts
            cols = {name: i for i, name in enumerate(header)}
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < len(header):
                    parts += [""] * (len(header) - len(parts))
                gene = parts[cols["gene"]]
                source = parts[cols["source"]]
                ont = parts[cols["ontology_term"]] or None
                desc = parts[cols["description"]]
                rxn_raw = parts[cols["reactions"]] or None
                if gene:
                    gene_set.add(gene)
                did = text_to_did.get(desc) if desc else None
                sid = _source_id(source) if source else None
                if sid is None:
                    continue
                ann_rows.append((genome_id, gene, sid, ont, did, rxn_raw))
                n_ann += 1
                if len(ann_rows) >= 5000:
                    conn.executemany(
                        "INSERT INTO annotations(genome_id, gene_id, source_id, ontology_term, description_id, raw_reactions) VALUES (?,?,?,?,?,?)",
                        ann_rows,
                    )
                    ann_rows.clear()
        if ann_rows:
            conn.executemany(
                "INSERT INTO annotations(genome_id, gene_id, source_id, ontology_term, description_id, raw_reactions) VALUES (?,?,?,?,?,?)",
                ann_rows,
            )

        # 3) genes table (from union of all genes seen)
        conn.executemany(
            "INSERT OR REPLACE INTO genes(gene_id, genome_id) VALUES (?,?)",
            [(g, genome_id) for g in sorted(gene_set)],
        )

        # 4) genomes row
        conn.execute(
            "INSERT OR REPLACE INTO genomes(genome_id, name, source_tsv, n_genes, n_descriptions, n_annotations, notes) VALUES (?,?,?,?,?,?,?)",
            (
                genome_id,
                genome_name or genome_id,
                str(annotation_tsv),
                len(gene_set),
                len(desc_rows),
                n_ann,
                f"built {datetime.datetime.now(datetime.timezone.utc).isoformat()} from {Path(annotation_tsv).name}",
            ),
        )
        conn.commit()

        # counts for caller
        counts = {}
        for t in ("queries", "predictions", "reactions",
                  "genomes", "genes", "annotation_sources",
                  "descriptions", "annotations", "existing_reactions"):
            counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        return counts
    finally:
        conn.close()


# ---- Directory output -------------------------------------------------------


def write_directory(results, dir_path: Path, pipeline_version: str = "pipeline_3-v0.1.0") -> None:
    """Write one <safe_query_id>.json file per result + a manifest.json index.

    Useful for very large batch runs where loading all results into one
    JSON/SQLite at once is undesirable.
    """
    import datetime
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    dir_path.mkdir(parents=True, exist_ok=True)

    # Per-direction subfolders for readability
    by_direction: dict[str, list] = {}
    for r in results:
        by_direction.setdefault(r.direction, []).append(r)

    manifest = {
        "pipeline_version": pipeline_version,
        "timestamp_utc": timestamp,
        "n_queries": len(results),
        "directions": {},
    }

    for direction, items in by_direction.items():
        sub = dir_path / direction
        sub.mkdir(exist_ok=True)
        entries = []
        for r in items:
            safe = r.query_id.replace(":", "_").replace("/", "_")
            fname = f"{safe}.json"
            (sub / fname).write_text(json.dumps(_result_to_rich_dict(r, pipeline_version), indent=2))
            entries.append({"query_id": r.query_id, "file": f"{direction}/{fname}",
                            "n_predictions": len(r.predictions)})
        manifest["directions"][direction] = {
            "n": len(items),
            "files": entries,
        }

    (dir_path / "manifest.json").write_text(json.dumps(manifest, indent=2))
