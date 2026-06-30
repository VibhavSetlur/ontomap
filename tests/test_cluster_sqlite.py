"""Tests for clustering integration into the SQLite output (ontomap.io)."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from ontomap.io import write_sqlite, cluster_result_from_results, write_clusters
from ontomap.cluster import cluster_reaction_sets


@dataclass
class _FakeResult:
    """Minimal stand-in for MapResult — only the fields write_sqlite reads."""
    query_id: str
    direction: str = "sso"
    predictions: list = field(default_factory=list)
    confidence_calibrated: list = field(default_factory=list)
    source_name: str | None = None
    source_ec: str | None = None
    source_def: str | None = None
    source_aliases: list = field(default_factory=list)
    ontology_term: str | None = None
    stage_scores: dict = field(default_factory=dict)
    reaction_meta: dict = field(default_factory=dict)
    latency_ms: float = 1.0
    cold: bool = False
    device: str = "cpu"
    warnings: list = field(default_factory=list)


def _fake_results():
    return [
        _FakeResult("a", predictions=[("rxn1", 0.9), ("rxn2", 0.8), ("rxn3", 0.7)]),
        _FakeResult("b", predictions=[("rxn1", 0.9), ("rxn2", 0.8), ("rxn3", 0.6)]),
        _FakeResult("z", predictions=[("rxn90", 0.5), ("rxn91", 0.4)]),
    ]


def test_write_sqlite_with_clusters(tmp_path):
    results = _fake_results()
    cl = cluster_result_from_results(results, threshold=0.3, cap=5, topk=10)
    db = tmp_path / "out.sqlite"
    write_sqlite(results, db, cluster_result=cl)

    conn = sqlite3.connect(str(db))
    try:
        # cluster tables exist and are populated
        n_clusters = conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0]
        n_members = conn.execute("SELECT COUNT(*) FROM cluster_members").fetchone()[0]
        assert n_members == 3                     # every query assigned
        assert n_clusters == 2                    # {a,b} together, z alone
        # a and b share a cluster, z is separate
        amap = dict(conn.execute("SELECT query_id, cluster_id FROM cluster_members"))
        assert amap["a"] == amap["b"]
        assert amap["z"] != amap["a"]
        # cluster_overview view works
        rows = conn.execute("SELECT cluster_id, size FROM cluster_overview").fetchall()
        assert max(s for _, s in rows) <= 5
        # no oversized cluster
        assert conn.execute("SELECT MAX(size) FROM clusters").fetchone()[0] <= 5
    finally:
        conn.close()


def test_write_sqlite_without_clusters_has_no_cluster_tables(tmp_path):
    results = _fake_results()
    db = tmp_path / "out_nocl.sqlite"
    write_sqlite(results, db)  # no cluster_result
    conn = sqlite3.connect(str(db))
    try:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "clusters" not in names
        assert "cluster_members" not in names
        # core tables still present
        assert {"queries", "predictions", "reactions"} <= names
    finally:
        conn.close()


def test_cluster_result_from_results_matches_direct(tmp_path):
    results = _fake_results()
    via_io = cluster_result_from_results(results, threshold=0.3, cap=5, topk=10)
    direct = cluster_reaction_sets(
        {r.query_id: [rxn for rxn, _ in r.predictions] for r in results},
        threshold=0.3, cap=5, topk=10)
    assert via_io.assignments == direct.assignments
