"""The SQLite deliverable writers must auto-emit a schema README.

Regression guard for the v1.6.0 self-documenting-deliverable feature: the
README that documented José's deliverable schema lived only in a folder that got
deleted, and nothing regenerated it. Now every `write_annotated_sqlite` /
`write_sqlite` call drops a README beside the DB, and `ontomap describe`
regenerates it on demand. No model weights required — synthetic results only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ontomap.io import write_annotated_sqlite, write_sqlite, write_sqlite_readme

pytestmark = pytest.mark.smoke


class _FakeResult:
    """Minimal stand-in for MapResult — only the fields the writers read."""

    def __init__(self, query_id, description):
        self.query_id = query_id
        self.direction = "sso"
        self.source_name = description
        self.source_ec = None
        self.source_def = description
        self.source_aliases = []
        self.ontology_term = "SSO:000000001"
        self.predictions = [("rxn02167", 0.98), ("rxn03247", 0.91)]
        self.confidence_calibrated = [0.98, 0.91]
        self.stage_scores = {}
        self.reaction_meta = {
            "rxn02167": {"name": "Enoyl-CoA hydratase", "ec_list": ["4.2.1.17"],
                         "equation": "A => B", "pathway": [], "alt_names": [],
                         "ec_match_level": 4},
            "rxn03247": {"name": "other", "ec_list": [], "equation": None,
                         "pathway": [], "alt_names": [], "ec_match_level": 0},
        }
        self.latency_ms = 1.0
        self.cold = False
        self.device = "cpu"


def _annotated_fixtures(tmp_path: Path):
    desc = "Enoyl-CoA hydratase (EC 4.2.1.17)"
    did = "DESC|Enoyl-CoA_hydratase_EC_4.2.1.17"
    tsv = tmp_path / "ann.tsv"
    tsv.write_text(
        "gene\tsource\tontology_term\tdescription\treactions\n"
        f"gene1\tRAST\tSSO:000000001\t{desc}\tMSRXN:rxn02167\n"
    )
    prov = tmp_path / "prov.jsonl"
    prov.write_text(json.dumps({
        "id": did, "description": desc, "genes": ["gene1"],
        "sources": ["RAST"], "ontology_terms": ["SSO:000000001"],
        "existing_reactions": ["MSRXN:rxn02167"],
    }) + "\n")
    return tsv, prov, did, desc


def test_write_annotated_sqlite_emits_readme(tmp_path):
    tsv, prov, did, desc = _annotated_fixtures(tmp_path)
    db = tmp_path / "deliverable.sqlite"
    counts = write_annotated_sqlite(
        [_FakeResult(did, desc)], annotation_tsv=tsv, provenance_jsonl=prov,
        out_path=db, genome_id="g1", genome_name="Test genome",
    )
    assert counts["queries"] == 1
    readme = tmp_path / "README.md"
    assert readme.exists(), "annotated writer must emit README.md beside the DB"
    text = readme.read_text()
    # every core table documented
    for tbl in ("queries", "predictions", "reactions", "existing_reactions",
                "descriptions", "annotations"):
        assert f"`{tbl}`" in text, f"{tbl} missing from README"
    # the join gotcha that bit the José deliverable
    assert "MSRXN" in text
    # views documented
    assert "prediction_full" in text


def test_write_sqlite_emits_readme(tmp_path):
    db = tmp_path / "core.sqlite"
    write_sqlite([_FakeResult("DESC|x", "x")], db)
    assert (tmp_path / "README.md").exists()


def test_describe_regenerates_for_existing_db(tmp_path):
    tsv, prov, did, desc = _annotated_fixtures(tmp_path)
    db = tmp_path / "deliverable.sqlite"
    write_annotated_sqlite(
        [_FakeResult(did, desc)], annotation_tsv=tsv, provenance_jsonl=prov,
        out_path=db, genome_id="g1",
    )
    # README.md already exists → describe falls back to <db>.README.md
    out = write_sqlite_readme(db, kind="annotated")
    assert out is not None and out.exists()
    assert "predictions" in out.read_text()
