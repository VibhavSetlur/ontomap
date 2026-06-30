"""ontomap CLI — `ontomap` console-script entry-point.

Subcommands:
    map            map SSO/KO ids OR free-text → ModelSEED reactions (single or batch)
    map-model      map a whole model's compounds + reactions → ModelSEED (rich SQLite)
    aggregate-tsv  dedup a multi-source annotation TSV into an ontomap-ready file
    bench          reproducible scaling benchmark (latency / RAM / VRAM at multiple N)
    fetch-models   pre-download all required model weights
    info           print version + weight pins + device + memory + smoke-test
    version        print package version
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ontomap import __version__


def cmd_map(args: argparse.Namespace) -> int:
    """Map one or more SSO/KO ids OR free-text descriptions to top-k ModelSEED reactions."""
    from ontomap.pipeline import Pipeline
    from ontomap.io import read_ids, read_descriptions, write_results

    direction = args.direction
    device = args.device
    descriptions = None  # set in free-text mode
    description_ids = None

    # v1.4.0: --name / --ec structured input. Compose into the text form
    # that map_descriptions expects so the rest of the path is unchanged.
    if args.name or args.ec:
        if not direction:
            direction = "sso"
        parts = []
        if args.name and args.name.strip():
            parts.append(args.name.strip())
        if args.ec and args.ec.strip():
            ec = args.ec.strip()
            if not ec.lower().startswith("ec"):
                ec = f"EC {ec}"
            if parts:
                parts[-1] = f"{parts[-1]} ({ec})"
            else:
                parts.append(ec)
        if args.tags:
            tag_text = "; ".join(t.strip() for t in args.tags.split(";") if t.strip())
            if tag_text:
                parts.append(f"[{tag_text}]")
        descriptions = [" ".join(parts)]
        description_ids = [args.text_id or "FREE:00000001"]
    # Free-text single-query
    elif args.text:
        if not direction:
            direction = "sso"  # SSO LoRA is the default for free-text
        descriptions = [args.text]
        description_ids = [args.text_id or "FREE:00000001"]
    # Free-text batch from a file
    elif args.text_input:
        if not direction:
            direction = "sso"
        descriptions, description_ids = read_descriptions(
            Path(args.text_input),
            text_column=args.text_column,
            id_column=args.id_column,
            input_format=args.input_format,
        )
    # Single SSO/KO id
    elif args.sso or args.ko:
        if args.sso and args.ko:
            print("ERROR: pass --sso OR --ko, not both", file=sys.stderr)
            return 2
        if args.sso:
            direction = "sso"
            ids = [args.sso]
        else:
            direction = "ko"
            ids = [args.ko]
    elif args.input:
        if not direction:
            print("ERROR: --direction sso|ko required for --input", file=sys.stderr)
            return 2
        ids = read_ids(
            Path(args.input),
            id_column=args.id_column,
            input_format=args.input_format,
        )
    else:
        print(
            "ERROR: pass one of --sso ID, --ko ID, --input FILE, "
            "--text TEXT, or --text-input FILE",
            file=sys.stderr,
        )
        return 2

    pipe = Pipeline.from_pretrained(direction=direction, device=device,
                                     ec_augment=getattr(args, "ec_augment", False))
    if descriptions is not None:
        results = pipe.map_descriptions(
            descriptions,
            ids=description_ids,
            top_k=args.top_k,
            batch_size=args.batch_size,
            verbose=not args.quiet,
        )
    else:
        results = pipe.map_batch(
            ids,
            top_k=args.top_k,
            batch_size=args.batch_size,
            verbose=not args.quiet,
        )

    if args.output:
        write_results(
            results,
            Path(args.output),
            output_format=args.format,
            direction=direction,
        )
        if not args.quiet:
            print(f"wrote {len(results)} results to {args.output}", file=sys.stderr)
    else:
        # stdout: one JSON object per query
        for r in results:
            print(json.dumps(r.to_dict()))
    return 0


def cmd_map_model(args: argparse.Namespace) -> int:
    """Map a whole foreign-namespace metabolic model's compounds + reactions to ModelSEED.

    Writes a rich, self-contained SQLite DB (default) or a raw JSON of the
    top-k predictions. ModelSEED data is resolved from --modelseed-dir →
    $ONTOMAP_MODELSEED → bundled data/modelseed (see SETUP_ASSETS.md).
    """
    out = args.output
    fmt = args.format
    if fmt is None:
        fmt = "sqlite" if str(out).lower().endswith((".sqlite", ".db", ".sqlite3")) else "json"

    if fmt == "sqlite":
        from ontomap.modelmap import map_model_to_sqlite
        path = map_model_to_sqlite(
            args.model, modelseed_dir=args.modelseed_dir, path=out,
            device=args.device, top_k=args.top_k, network=not args.no_network,
            run_metadata={"source": "ontomap map-model CLI"},
        )
        if not args.quiet:
            print(f"wrote rich SQLite mapping → {path}", file=sys.stderr)
    else:
        from ontomap.modelmap import map_model
        res = map_model(args.model, modelseed_dir=args.modelseed_dir,
                        device=args.device, top_k=args.top_k, network=not args.no_network)
        ser = {kind: {q: [{"rank": i + 1, "id": c, "score": s, "signals": sig}
                          for i, (c, s, sig) in enumerate(v)]
                      for q, v in res[kind].items()}
               for kind in ("compounds", "reactions")}
        if out:
            Path(out).write_text(json.dumps(ser, indent=2))
            if not args.quiet:
                print(f"wrote {out}", file=sys.stderr)
        else:
            print(json.dumps(ser))
    return 0


def cmd_aggregate_tsv(args: argparse.Namespace) -> int:
    """Aggregate a multi-source annotation TSV → ontomap-ready descriptions file.

    Built for the Christopher Henry / RAST-vault dump shape:
        gene  source  ontology_term  description  reactions

    Behaviour:
      - dedup descriptions per gene (keeping all sources that contributed)
      - optionally collapse to one row per unique description (across genes)
      - drop trivially uninformative descriptions ("hypothetical protein",
        empty, "putative protein") unless --keep-trivial
      - emit a clean two-column TSV ready for `ontomap map --text-input`
      - emit a sidecar JSONL with full source/gene/reaction provenance for
        every description so downstream tools can re-attach gold reactions
    """
    from ontomap.aggregate import aggregate_annotation_tsv

    n_descs, n_genes, n_provenance = aggregate_annotation_tsv(
        input_path=Path(args.input),
        output_path=Path(args.output),
        provenance_path=Path(args.provenance) if args.provenance else None,
        dedup_mode=args.dedup,
        drop_trivial=not args.keep_trivial,
        gene_column=args.gene_column,
        source_column=args.source_column,
        description_column=args.description_column,
        ontology_column=args.ontology_column,
        reactions_column=args.reactions_column,
    )
    print(
        f"aggregated → {n_descs} descriptions covering {n_genes} genes "
        f"({n_provenance} provenance rows)",
        file=sys.stderr,
    )
    return 0


def cmd_bench(args: argparse.Namespace) -> int:
    """Reproducible scaling benchmark."""
    from ontomap.bench import run_bench

    tiers = [int(t) for t in args.tiers.split(",")]
    results = run_bench(
        direction=args.direction,
        tiers=tiers,
        device=args.device,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        seed=args.seed,
    )
    print(json.dumps(results, indent=2))
    return 0


def cmd_fetch_models(args: argparse.Namespace) -> int:
    """Pre-download all required model weights to HF cache."""
    from ontomap.weights_fetch import fetch_all

    summary = fetch_all(force=args.force)
    print(json.dumps(summary, indent=2))
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    """Print version + weight pins + device + memory + bundle status + smoke-test."""
    from ontomap.info import collect_info, verify_manifest_cmd

    if args.verify_manifest:
        result = verify_manifest_cmd()
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"MANIFEST verification: {result['n_ok']}/{result['n_total']} OK, "
                  f"{result['n_bad']} BAD, {result['n_missing']} MISSING")
            for r in result["results"]:
                marker = {"OK": "✓", "BAD": "✗", "MISSING": "?"}[r["status"]]
                print(f"  {marker} {r['path']}")
                if r["status"] == "BAD":
                    print(f"      expected sha {r['expected_sha'][:16]}…  actual sha {r['actual_sha'][:16]}…")
                    print(f"      expected size {r['expected_size']:,}  actual size {r['actual_size']:,}")
        return 0 if result.get("ok") else 1

    info = collect_info(run_smoke_test=not args.no_smoke)
    if args.json:
        print(json.dumps(info, indent=2))
    else:
        print(f"ontomap v{info['version']}")
        print(f"  Python:    {info['python']}")
        print(f"  Torch:     {info.get('torch')}")
        print(f"  CUDA:      {info.get('cuda_available')} ({info.get('cuda_device','-')})")
        print(f"  Home:      {info['ontomap_home']}")
        print(f"  Weights:   {info['weights_status']}")
        if info.get("bundle_missing"):
            for m in info["bundle_missing"]:
                print(f"             ✗ missing: {m}")
        health = info.get("asset_health") or {}
        if health:
            bad = info.get("asset_health_bad") or []
            print(f"  Assets:    {len(health) - len(bad)}/{len(health)} healthy"
                  + (f"  (bad: {', '.join(bad)})" if bad else ""))
            for k in bad:
                print(f"             ✗ {k}: {health[k].get('error')}")
        print(f"  Smoke:     {info.get('smoke_status','skipped')}")
        if info.get("warnings"):
            print("  Warnings:")
            for w in info["warnings"]:
                print(f"    - {w}")
    return 0 if info.get("ok") else 1


def cmd_version(args: argparse.Namespace) -> int:
    print(__version__)
    return 0


def cmd_describe(args: argparse.Namespace) -> int:
    """(Re)generate the schema README beside an existing ontomap SQLite."""
    from pathlib import Path

    from ontomap.io import write_sqlite_readme

    db = Path(args.db)
    if not db.exists():
        print(f"ERROR: {db} not found", file=sys.stderr)
        return 1
    readme = write_sqlite_readme(db, kind=args.kind)
    if readme is None:
        print(f"ERROR: could not introspect {db}", file=sys.stderr)
        return 2
    print(f"wrote {readme}")
    return 0


def cmd_cluster(args: argparse.Namespace) -> int:
    """Cluster function descriptions by reaction-prediction overlap (pre-council step).

    Reads an ontomap predictions artefact (JSON/JSONL/SQLite), groups descriptions whose
    top-k ModelSEED reaction sets overlap (Jaccard >= threshold) with a hard size cap
    enforced by hierarchical sub-clustering, and writes a cluster-UUID table. Optionally
    injects the clusters into an existing ontomap SQLite (clusters + cluster_members).
    """
    from ontomap.cluster import (
        cluster_reaction_sets, cluster_result_to_rows,
        load_reaction_sets_from_predictions,
    )

    reaction_sets = load_reaction_sets_from_predictions(args.predictions, topk=args.topk)
    if not reaction_sets:
        print(f"ERROR: no predictions found in {args.predictions}", file=sys.stderr)
        return 1
    result = cluster_reaction_sets(
        reaction_sets, method=args.method, threshold=args.threshold, cap=args.cap, topk=args.topk
    )
    rows = cluster_result_to_rows(result)
    hist = result.size_histogram()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    suffix = out.suffix.lower()
    if suffix == ".parquet":
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as e:
            raise ImportError("install pyarrow to write parquet cluster output") from e
        pq.write_table(pa.Table.from_pylist(rows), out)
    elif suffix in (".tsv", ".csv"):
        import csv as _csv
        delim = "\t" if suffix == ".tsv" else ","
        with out.open("w", newline="") as f:
            w = _csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter=delim)
            w.writeheader()
            w.writerows(rows)
    elif suffix in (".json", ".jsonl"):
        out.write_text(json.dumps({"clusters": result.clusters, "params": result.params}, indent=2))
    else:
        raise ValueError(f"unsupported --output extension: {out.name} (use .parquet/.tsv/.csv/.json)")

    if args.inject_sqlite:
        import sqlite3
        from ontomap.io import write_clusters
        conn = sqlite3.connect(args.inject_sqlite)
        try:
            wc = write_clusters(conn, result)
        finally:
            conn.close()
        if not args.quiet:
            print(f"injected {wc['clusters']} clusters / {wc['cluster_members']} members "
                  f"into {args.inject_sqlite}", file=sys.stderr)

    print(
        f"clustered {len(reaction_sets)} descriptions -> {result.n_clusters} clusters "
        f"({result.n_singletons} singletons, max size {max(hist)}); "
        f"size histogram {hist}; wrote {out}",
        file=sys.stderr,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ontomap",
        description=(
            "Frozen pipeline-3 SSO/KO → ModelSEED reaction mapping. "
            "SapBERT-LoRA + multi-axis FAISS + MedCPT fused rerank, no LLM."
        ),
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    # ---- map ----
    m = sub.add_parser(
        "map",
        help="map SSO/KO id(s) OR free-text descriptions to top-k ModelSEED reactions",
    )
    grp = m.add_mutually_exclusive_group()
    grp.add_argument("--sso", type=str, help="single SSO id, e.g. SSO:000000027")
    grp.add_argument("--ko", type=str, help="single KO id, e.g. K10046")
    grp.add_argument(
        "--input",
        type=str,
        help="path to input file of SSO/KO ids (CSV/TSV/JSON/JSONL/Parquet/TXT)",
    )
    grp.add_argument(
        "--text",
        type=str,
        help='single free-text description, e.g. "Enoyl-CoA hydratase (EC 4.2.1.17)" '
             "(direction defaults to sso)",
    )
    grp.add_argument(
        "--text-input",
        type=str,
        help="path to input file containing free-text descriptions. "
             "Use --text-column to point at the description column (auto-detected).",
    )
    grp.add_argument(
        "--name", type=str,
        help='(v1.4.0) name component of a structured query; pair with --ec '
             '(e.g. --name "Aldehyde dehydrogenase" --ec 1.2.1.3)',
    )
    m.add_argument(
        "--ec", type=str, default=None,
        help='(v1.4.0) EC component of a structured query. Works with --name (composed '
             'into "<name> (EC <ec>)") OR alone (e.g. --ec 1.2.1.3, direction defaults to sso)',
    )
    m.add_argument("--tags", type=str, default=None,
        help='(v1.4.0) optional semicolon-separated tags appended to the query, '
             'e.g. --tags "putative;partial"')
    m.add_argument("--direction", choices=["sso", "ko"], help="required when using --input")
    m.add_argument("--id-column", default=None, help="column name in --input file (auto-detected if omitted)")
    m.add_argument(
        "--text-column",
        default=None,
        help="column name with free-text descriptions in --text-input file "
             "(auto-detected from {description, desc, text, function, label, name})",
    )
    m.add_argument(
        "--text-id",
        default=None,
        help='stable id to attach to --text TEXT (default: "FREE:00000001")',
    )
    m.add_argument("--input-format", choices=["csv", "tsv", "json", "jsonl", "parquet", "txt"], default=None)
    m.add_argument("--output", "-o", default=None, help="output path (omit to stream JSONL to stdout)")
    m.add_argument("--format", "-f", choices=["sssom-tsv", "json", "jsonl", "csv", "tsv", "parquet"], default=None,
                   help="output format (auto-detected from --output extension if omitted)")
    m.add_argument("--top-k", "-k", type=int, default=20,
                   help="number of candidates per query (default 20 — the validated production "
                        "depth; enough for downstream `ontomap cluster` which uses top-20)")
    m.add_argument("--batch-size", type=int, default=64, help="encoder batch size (default 64)")
    m.add_argument("--device", default="auto", help="cuda | cpu | auto (default auto)")
    m.add_argument("--quiet", "-q", action="store_true")
    m.add_argument("--ec-augment", action="store_true",
                   help="(v1.2.0) Also score reactions whose ec_numbers match the query EC "
                        "even when SapBERT-LoRA didn't surface them in the top-100. "
                        "Adds ~10%% wall-clock; lifts recall@100 by ~1pp.")
    m.set_defaults(func=cmd_map)

    # ---- aggregate-tsv ----
    a = sub.add_parser(
        "aggregate-tsv",
        help="aggregate a multi-source annotation TSV (e.g. RAST/BAKTA/dram/glm4ec dump) "
             "into an ontomap-ready descriptions file",
    )
    a.add_argument("--input", "-i", required=True, help="multi-source annotation TSV")
    a.add_argument("--output", "-o", required=True, help="output TSV (gene_or_id, description)")
    a.add_argument(
        "--provenance",
        default=None,
        help="optional sidecar JSONL: per-description sources/genes/existing reactions",
    )
    a.add_argument(
        "--dedup",
        choices=["per-gene", "global"],
        default="per-gene",
        help="per-gene: one row per (gene, unique description); "
             "global: one row per unique description across all genes",
    )
    a.add_argument("--keep-trivial", action="store_true",
                   help='keep "hypothetical protein" / empty / "putative protein"-style rows')
    a.add_argument("--gene-column", default="gene")
    a.add_argument("--source-column", default="source")
    a.add_argument("--description-column", default="description")
    a.add_argument("--ontology-column", default="ontology_term")
    a.add_argument("--reactions-column", default="reactions")
    a.set_defaults(func=cmd_aggregate_tsv)

    # ---- map-model ----
    mm = sub.add_parser(
        "map-model",
        help="map a whole metabolic model's compounds + reactions to ModelSEED "
             "(writes a rich, self-contained SQLite DB)",
    )
    mm.add_argument("--model", required=True,
                    help="COBRA-style model JSON with metabolites[] + reactions[]")
    mm.add_argument("--output", "-o", default="model_mapping.sqlite",
                    help="output path: .sqlite/.db → rich DB (default); .json → raw top-k")
    mm.add_argument("--format", "-f", choices=["sqlite", "json"], default=None,
                    help="auto-detected from --output extension if omitted")
    mm.add_argument("--modelseed-dir", default=None,
                    help="dir with compounds.tsv + reactions.tsv "
                         "(default: $ONTOMAP_MODELSEED or bundled data/modelseed)")
    mm.add_argument("--top-k", "-k", type=int, default=100, help="candidates per query (default 100)")
    mm.add_argument("--device", default="auto", help="cuda | cpu | auto (default auto)")
    mm.add_argument("--no-network", action="store_true",
                    help="disable the reaction-network compound rerank (faster, ~lower compound hit@1)")
    mm.add_argument("--quiet", "-q", action="store_true")
    mm.set_defaults(func=cmd_map_model)

    # ---- bench ----
    b = sub.add_parser("bench", help="reproducible scaling benchmark (latency / RAM / VRAM at multiple N)")
    b.add_argument("--direction", choices=["sso", "ko", "both"], default="both")
    b.add_argument("--tiers", default="10,100,1000", help="comma-separated N values (default 10,100,1000)")
    b.add_argument("--device", default="auto")
    b.add_argument("--output-dir", default=None, help="directory for bench tables + figures")
    b.add_argument("--seed", type=int, default=17)
    b.set_defaults(func=cmd_bench)

    # ---- fetch-models ----
    f = sub.add_parser("fetch-models", help="pre-download SapBERT + MedCPT + (if not bundled) LoRA adapters")
    f.add_argument("--force", action="store_true", help="re-download even if already cached")
    f.set_defaults(func=cmd_fetch_models)

    # ---- info ----
    i = sub.add_parser("info", help="print version + weight pins + device + memory + bundle status + smoke-test")
    i.add_argument("--no-smoke", action="store_true", help="skip the end-to-end smoke test")
    i.add_argument("--verify-manifest", action="store_true",
                   help="re-hash every bundled file and compare to weights/MANIFEST.txt (slow)")
    i.add_argument("--json", action="store_true", help="emit JSON")
    i.set_defaults(func=cmd_info)

    # ---- describe ----
    d = sub.add_parser(
        "describe",
        help="(re)generate the schema README beside an ontomap SQLite deliverable",
    )
    d.add_argument("db", help="path to an ontomap .sqlite file")
    d.add_argument(
        "--kind", default="auto", choices=["auto", "annotated", "model", "core"],
        help="deliverable type (default: auto-detect from tables)",
    )
    d.set_defaults(func=cmd_describe)

    # ---- cluster ----
    cl = sub.add_parser(
        "cluster",
        help="pre-council clustering: group descriptions by reaction-prediction overlap "
             "(reaction-Jaccard + hard size cap) and emit a cluster-UUID table",
    )
    cl.add_argument("--predictions", "-p", required=True,
                    help="ontomap predictions artefact to cluster (.sqlite/.parquet/.json/.jsonl)")
    cl.add_argument("--output", "-o", required=True,
                    help="cluster-UUID output (.parquet/.tsv/.csv/.json)")
    from ontomap.cluster import CLUSTER_METHODS
    cl.add_argument("--method", "-m", default="cc",
                    choices=list(CLUSTER_METHODS),
                    help="component-refinement algorithm (default cc; cc is the validated "
                         "production default, others are alternative merge/cohesion trade-offs)")
    cl.add_argument("--threshold", "-t", type=float, default=0.3,
                    help="Jaccard edge threshold (default 0.3, validated production default)")
    cl.add_argument("--cap", type=int, default=5,
                    help="hard maximum cluster size (default 5; started here, targeting 2-3 per cluster)")
    cl.add_argument("--topk", "-k", type=int, default=20,
                    help="top-k reactions per description used for the Jaccard (default 20)")
    cl.add_argument("--inject-sqlite", default=None,
                    help="also write clusters+cluster_members into this existing ontomap SQLite")
    cl.add_argument("--quiet", "-q", action="store_true")
    cl.set_defaults(func=cmd_cluster)

    # ---- version ----
    v = sub.add_parser("version", help="print package version")
    v.set_defaults(func=cmd_version)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
