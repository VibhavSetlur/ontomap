"""Smoke tests — minimal end-to-end checks. Run via `pytest -m smoke`.

These tests exercise the public API surface without requiring model weights
to be present. The actual frozen-pipeline tests live in test_pipeline.py
(marked `slow`) and require either bundled weights or `ontomap fetch-models`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import ontomap


pytestmark = pytest.mark.smoke


def test_version_present():
    assert ontomap.__version__
    assert ontomap.__version__.count(".") == 2


def test_pipeline_imports():
    from ontomap import Pipeline, MapResult, PipelineConfig  # noqa: F401


def test_cli_help(capsys):
    from ontomap import cli

    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "ontomap" in out.lower()
    assert "map" in out
    assert "bench" in out


def test_cli_version():
    from ontomap import cli

    rc = cli.main(["version"])
    assert rc == 0


def test_io_detect_formats(tmp_path: Path):
    from ontomap.io import detect_input_format, detect_output_format

    assert detect_input_format(tmp_path / "x.csv") == "csv"
    assert detect_input_format(tmp_path / "x.tsv") == "tsv"
    assert detect_input_format(tmp_path / "x.jsonl") == "jsonl"
    assert detect_input_format(tmp_path / "x.json") == "json"
    assert detect_input_format(tmp_path / "x.parquet") == "parquet"
    assert detect_input_format(tmp_path / "x.txt") == "txt"

    assert detect_output_format(tmp_path / "x.sssom.tsv") == "sssom-tsv"
    assert detect_output_format(tmp_path / "x.tsv") == "tsv"
    assert detect_output_format(tmp_path / "x.csv") == "csv"
    assert detect_output_format(tmp_path / "x.json") == "json"
    assert detect_output_format(tmp_path / "x.parquet") == "parquet"


def test_io_read_ids_txt(tmp_path: Path):
    from ontomap.io import read_ids

    f = tmp_path / "ids.txt"
    f.write_text("# header comment\nSSO:000000001\nSSO:000000002\n  \nSSO:000000003\n")
    ids = read_ids(f)
    assert ids == ["SSO:000000001", "SSO:000000002", "SSO:000000003"]


def test_io_read_ids_csv(tmp_path: Path):
    from ontomap.io import read_ids

    f = tmp_path / "ids.csv"
    f.write_text("sso_id,note\nSSO:000000001,a\nSSO:000000002,b\n")
    ids = read_ids(f)
    assert ids == ["SSO:000000001", "SSO:000000002"]


def test_io_read_ids_json_list_of_strings(tmp_path: Path):
    from ontomap.io import read_ids

    f = tmp_path / "ids.json"
    f.write_text(json.dumps(["K10046", "K10047"]))
    ids = read_ids(f)
    assert ids == ["K10046", "K10047"]


def test_io_read_ids_jsonl(tmp_path: Path):
    from ontomap.io import read_ids

    f = tmp_path / "ids.jsonl"
    f.write_text('{"ko_id":"K10046"}\n{"ko_id":"K10047"}\n')
    ids = read_ids(f)
    assert ids == ["K10046", "K10047"]


def test_io_write_jsonl_roundtrip(tmp_path: Path):
    from ontomap import MapResult
    from ontomap.io import write_results

    r = MapResult(query_id="SSO:000000001", direction="sso",
                  predictions=[("rxn16679", 0.92), ("rxn00148", 0.41)],
                  confidence_calibrated=[0.87, 0.32],
                  latency_ms=12.5)
    out = tmp_path / "out.jsonl"
    write_results([r], out)
    rows = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    # New rich shape: query nested, predictions list of dicts
    assert rows[0]["query"]["id"] == "SSO:000000001"
    assert rows[0]["query"]["direction"] == "sso"
    assert len(rows[0]["predictions"]) == 2
    assert rows[0]["predictions"][0]["reaction_id"] == "rxn16679"
    assert rows[0]["predictions"][0]["rank"] == 1


def test_io_write_sssom_tsv(tmp_path: Path):
    from ontomap import MapResult
    from ontomap.io import write_results

    r = MapResult(query_id="SSO:000000001", direction="sso",
                  predictions=[("rxn16679", 0.92)],
                  confidence_calibrated=[0.87],
                  latency_ms=12.5)
    out = tmp_path / "out.sssom.tsv"
    write_results([r], out, direction="sso")
    text = out.read_text()
    assert "curie_map" in text
    assert "skos:exactMatch" in text
    assert "rxn16679" in text


def test_io_write_sqlite(tmp_path: Path):
    from ontomap import MapResult
    from ontomap.io import write_sqlite
    import sqlite3

    r = MapResult(
        query_id="SSO:000000027", direction="sso",
        source_name="1,2-phenylacetyl-CoA epoxidase, subunit A",
        source_ec="1.14.13.149",
        predictions=[("rxn16679", 0.97), ("rxn00148", 0.41)],
        confidence_calibrated=[0.91, 0.32],
        reaction_meta={
            "rxn16679": {
                "name": "phenylacetyl-CoA:oxygen oxidoreductase",
                "ec_list": ["1.14.13.149"],
                "equation": "phenylacetyl-CoA + O2 + NADPH + H+ -> ... + NADP+ + H2O",
                "pathway": ["Phenylalanine metabolism"],
                "ec_match_level": 4,
            }
        },
        latency_ms=128.0,
    )
    db = tmp_path / "results.sqlite"
    write_sqlite([r], db)

    conn = sqlite3.connect(str(db))
    try:
        q = conn.execute("SELECT query_id, source_ec FROM queries").fetchall()
        p = conn.execute(
            "SELECT rank, reaction_id, fused_score, confidence_calibrated, predicate "
            "FROM predictions ORDER BY rank"
        ).fetchall()
        r_meta = conn.execute(
            "SELECT reaction_id, name, ec_list FROM reactions"
        ).fetchall()
        view = conn.execute(
            "SELECT query_id, rank, reaction_id, reaction_name FROM top_n_with_meta"
        ).fetchall()
    finally:
        conn.close()

    assert q == [("SSO:000000027", "1.14.13.149")]
    assert p[0][0] == 1 and p[0][1] == "rxn16679"
    assert p[0][4] == "skos:exactMatch"
    assert ("rxn16679",) == r_meta[0][:1]
    assert view[0][3] == "phenylacetyl-CoA:oxygen oxidoreductase"


def test_io_write_directory(tmp_path: Path):
    from ontomap import MapResult
    from ontomap.io import write_directory

    r1 = MapResult(query_id="SSO:000000027", direction="sso",
                   predictions=[("rxn16679", 0.97)], confidence_calibrated=[0.91],
                   latency_ms=128.0)
    r2 = MapResult(query_id="K10046", direction="ko",
                   predictions=[("rxn07673", 0.88)], confidence_calibrated=[0.84],
                   latency_ms=170.0)
    out_dir = tmp_path / "batch_out"
    write_directory([r1, r2], out_dir)

    assert (out_dir / "manifest.json").exists()
    assert (out_dir / "sso" / "SSO_000000027.json").exists()
    assert (out_dir / "ko" / "K10046.json").exists()
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["n_queries"] == 2
    assert manifest["directions"]["sso"]["n"] == 1
    assert manifest["directions"]["ko"]["n"] == 1


def test_io_read_descriptions_tsv(tmp_path: Path):
    from ontomap.io import read_descriptions

    f = tmp_path / "annot.tsv"
    f.write_text(
        "gene\tdescription\tnote\n"
        "Ac3H11_1\tAraC family transcriptional regulator\ta\n"
        "Ac3H11_2\tEnoyl-CoA hydratase (EC 4.2.1.17)\tb\n"
    )
    descs, ids = read_descriptions(f, id_column="gene")
    assert descs == [
        "AraC family transcriptional regulator",
        "Enoyl-CoA hydratase (EC 4.2.1.17)",
    ]
    assert ids == ["Ac3H11_1", "Ac3H11_2"]


def test_io_read_descriptions_autodetects_text_column(tmp_path: Path):
    from ontomap.io import read_descriptions

    f = tmp_path / "annot.csv"
    f.write_text("function,gene\nEnoyl-CoA hydratase,Ac3H11_100\nABC transporter,Ac3H11_2\n")
    descs, ids = read_descriptions(f)
    assert descs == ["Enoyl-CoA hydratase", "ABC transporter"]
    # No id_column requested → synthetic ids
    assert ids == ["FREE:00000001", "FREE:00000002"]


def test_io_read_descriptions_txt(tmp_path: Path):
    from ontomap.io import read_descriptions

    f = tmp_path / "descriptions.txt"
    f.write_text(
        "# a comment\n"
        "Enoyl-CoA hydratase (EC 4.2.1.17)\n"
        "ABC transporter substrate-binding protein\n"
        "\n"
        "AraC family transcriptional regulator\n"
    )
    descs, ids = read_descriptions(f)
    assert descs == [
        "Enoyl-CoA hydratase (EC 4.2.1.17)",
        "ABC transporter substrate-binding protein",
        "AraC family transcriptional regulator",
    ]
    assert ids == ["FREE:00000001", "FREE:00000002", "FREE:00000003"]


def test_aggregate_tsv_global_dedup(tmp_path: Path):
    """Multi-source dump → one row per unique description across all genes."""
    from ontomap.aggregate import aggregate_annotation_tsv

    src = tmp_path / "dump.tsv"
    src.write_text(
        "gene\tsource\tontology_term\tdescription\treactions\n"
        # Two genes both mapped to "AraC family transcriptional regulator" by multiple sources
        "Ac3H11_1\tRAST\tSSO:000023839\tAraC family transcriptional regulator\t\n"
        "Ac3H11_1\tbakta\t\tAraC family transcriptional regulator\t\n"
        "Ac3H11_1\tprokka\t\tHTH-type transcriptional activator RhaR\t\n"
        "Ac3H11_2\tRAST\tSSO:000023839\tAraC family transcriptional regulator\t\n"
        # Hypothetical proteins should be dropped
        "Ac3H11_3\tprokka\t\thypothetical protein\t\n"
        # Reaction-bearing row
        "Ac3H11_100\tglm4ec\tEC:4.2.1.17\tEnoyl-CoA hydratase (EC 4.2.1.17)\tMSRXN:rxn02167;MSRXN:rxn03245\n"
    )
    out_path = tmp_path / "clean.tsv"
    prov_path = tmp_path / "clean.provenance.jsonl"
    n_descs, n_genes, n_rows_kept = aggregate_annotation_tsv(
        input_path=src, output_path=out_path, provenance_path=prov_path, dedup_mode="global",
    )
    # 3 unique non-trivial descriptions; 3 unique genes contributing them
    assert n_descs == 3
    assert n_genes == 3
    assert n_rows_kept == 5  # all 5 non-hypothetical rows survived

    out_lines = out_path.read_text().splitlines()
    assert out_lines[0].split("\t") == ["id", "description", "n_genes", "n_sources", "has_existing_reactions"]
    # Reaction-bearing row should have has_existing_reactions=1
    enoyl = [line for line in out_lines if "Enoyl-CoA hydratase" in line][0]
    assert enoyl.endswith("\t1")

    prov_lines = [json.loads(line) for line in prov_path.read_text().splitlines()]
    by_desc = {p["description"]: p for p in prov_lines}
    assert "Enoyl-CoA hydratase (EC 4.2.1.17)" in by_desc
    assert by_desc["Enoyl-CoA hydratase (EC 4.2.1.17)"]["existing_reactions"] == [
        "MSRXN:rxn02167", "MSRXN:rxn03245",
    ]
    assert "Ac3H11_100" in by_desc["Enoyl-CoA hydratase (EC 4.2.1.17)"]["genes"]
    # AraC descriptions cover two genes from three sources
    arac = by_desc["AraC family transcriptional regulator"]
    assert sorted(arac["genes"]) == ["Ac3H11_1", "Ac3H11_2"]
    assert sorted(arac["sources"]) == ["RAST", "bakta"]


def test_aggregate_tsv_per_gene_dedup(tmp_path: Path):
    from ontomap.aggregate import aggregate_annotation_tsv

    src = tmp_path / "dump.tsv"
    src.write_text(
        "gene\tsource\tontology_term\tdescription\treactions\n"
        "Ac3H11_1\tRAST\tSSO:1\tAraC regulator\t\n"
        "Ac3H11_1\tbakta\t\tAraC regulator\t\n"
        "Ac3H11_2\tRAST\tSSO:1\tAraC regulator\t\n"
    )
    out_path = tmp_path / "clean.tsv"
    n_descs, n_genes, _ = aggregate_annotation_tsv(
        input_path=src, output_path=out_path, dedup_mode="per-gene",
    )
    # Two (gene, description) keys: (Ac3H11_1, AraC), (Ac3H11_2, AraC)
    assert n_descs == 2
    assert n_genes == 2


def test_confidence_v2_demotes_non_enzymes(tmp_path: Path):
    """v2 must demote keyword-trap miscalibrations from exactMatch to relatedMatch."""
    from ontomap.confidence_v2 import recalibrate_one

    # The 6 NR-miscalib cases from the step-27 audit. v1 had them all at
    # ≥ 0.85 exactMatch — v2 must demote each to relatedMatch.
    cases = [
        ("HTH-type transcriptional regulator DmlR", None, 0.884, 0.882, []),
        ("DUF4442 domain-containing protein", None, 0.897, 0.890, []),
        ("Uncharacterized protein conserved in bacteria", None, 0.986, 0.625, []),
        ("histone-like protein", None, 0.951, 0.856, ["2.1.1.43"]),
        ("CRISPR-associated protein Csy2", None, 0.912, 0.912, []),
        ("Inner membrane protein", None, 0.882, 0.708, []),
    ]
    for desc, ec, t1, t2, rxn_ec in cases:
        score, pred, br = recalibrate_one(desc, ec, t1, t2, rxn_ec)
        assert pred == "skos:relatedMatch", \
            f"v2 should demote '{desc}' but got pred={pred} score={score:.3f}"
        assert "non_enzyme_keyword_x0.55" in br["applied_rules"]


def test_confidence_v2_preserves_enzymes(tmp_path: Path):
    """v2 must not penalise actual enzymes with no non-enzyme keywords."""
    from ontomap.confidence_v2 import recalibrate_one

    score, pred, br = recalibrate_one(
        "Enoyl-CoA hydratase (EC 4.2.1.17)",
        "4.2.1.17",
        0.930, 0.880, ["4.2.1.17"],
    )
    assert pred == "skos:exactMatch"
    # EC match should add +0.05
    assert score > 0.93
    assert "ec_match_4_+0.05" in br["applied_rules"]


def test_confidence_v2_gap_penalty(tmp_path: Path):
    """Small top1-top2 gap should knock confidence down by 0.10."""
    from ontomap.confidence_v2 import recalibrate_one

    score_wide, _, br_wide = recalibrate_one(
        "L-arginine carboxy-lyase", None, 0.90, 0.50, []
    )
    score_narrow, _, br_narrow = recalibrate_one(
        "L-arginine carboxy-lyase", None, 0.90, 0.89, []
    )
    assert br_narrow["gap_penalty"] == 0.10
    assert br_wide["gap_penalty"] == 0.0
    assert score_narrow == score_wide - 0.10


def test_confidence_v2_recalibrate_predictions_inplace(tmp_path: Path):
    """recalibrate_predictions should add v2 fields to every prediction record."""
    from ontomap.confidence_v2 import recalibrate_predictions

    payload = [{
        "query": {"id": "FREE:00000001", "source_name": "Enoyl-CoA hydratase (EC 4.2.1.17)",
                  "source_ec": "4.2.1.17", "direction": "sso"},
        "predictions": [
            {"rank": 1, "reaction_id": "rxn02167", "fused_score": 0.93,
             "reaction": {"name": "enoyl-CoA hydratase", "ec_list": ["4.2.1.17"]}},
            {"rank": 2, "reaction_id": "rxn03245", "fused_score": 0.88,
             "reaction": {"name": "enoyl-CoA hydratase variant", "ec_list": ["4.2.1.17"]}},
        ],
    }]
    out = recalibrate_predictions(payload)
    p = out[0]["predictions"][0]
    assert "fused_score_v2" in p
    assert "predicate_v2" in p
    assert "confidence_v2_breakdown" in p
    assert p["predicate_v2"] == "skos:exactMatch"


def test_cli_help_includes_new_subcommands(capsys):
    from ontomap import cli

    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "aggregate-tsv" in out
