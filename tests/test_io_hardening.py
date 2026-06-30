"""Tests for the v1.8.1 production I/O hardening."""
from __future__ import annotations

import sqlite3
import pytest

from ontomap.io import read_descriptions
from ontomap.cluster import load_reaction_sets_from_predictions


# ---- read_descriptions: explicit-column errors + empty input ----

def test_csv_bad_text_column_lists_available(tmp_path):
    p = tmp_path / "in.csv"
    p.write_text("foo,bar\nhello,world\n")
    with pytest.raises(ValueError, match="not found.*Available columns"):
        read_descriptions(p, text_column="description")


def test_csv_empty_returns_empty(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text("description\n")  # header only
    descs, ids = read_descriptions(p)
    assert descs == [] and ids == []


def test_csv_autodetect_and_ids(tmp_path):
    p = tmp_path / "in.csv"
    p.write_text("id,description\nq1,enoyl-CoA hydratase\nq2,ABC transporter\n")
    descs, ids = read_descriptions(p, id_column="id")
    assert descs == ["enoyl-CoA hydratase", "ABC transporter"]
    assert ids == ["q1", "q2"]


def test_jsonl_bad_column_errors(tmp_path):
    p = tmp_path / "in.jsonl"
    p.write_text('{"foo": "x"}\n')
    with pytest.raises(ValueError, match="not found"):
        read_descriptions(p, text_column="description")


def test_parquet_roundtrip_and_bad_column(tmp_path):
    pq = pytest.importorskip("pyarrow.parquet")
    pa = pytest.importorskip("pyarrow")
    p = tmp_path / "in.parquet"
    pq.write_table(pa.table({"id": ["q1", "q2"], "description": ["aaa", "bbb"]}), p)
    descs, ids = read_descriptions(p, id_column="id")
    assert descs == ["aaa", "bbb"] and ids == ["q1", "q2"]
    with pytest.raises(ValueError, match="not found"):
        read_descriptions(p, text_column="nope")


# ---- load_reaction_sets_from_predictions: missing file / bad schema / parquet ----

def test_predictions_missing_file():
    with pytest.raises(FileNotFoundError):
        load_reaction_sets_from_predictions("/nonexistent/preds.sqlite")


def test_predictions_sqlite_without_table(tmp_path):
    p = tmp_path / "bad.sqlite"
    conn = sqlite3.connect(str(p))
    conn.execute("CREATE TABLE other (x INTEGER)")
    conn.commit(); conn.close()
    with pytest.raises(ValueError, match="no .predictions. table"):
        load_reaction_sets_from_predictions(p)


def test_predictions_sqlite_ok(tmp_path):
    p = tmp_path / "preds.sqlite"
    conn = sqlite3.connect(str(p))
    conn.execute("CREATE TABLE predictions (query_id TEXT, rank INTEGER, reaction_id TEXT)")
    conn.executemany("INSERT INTO predictions VALUES (?,?,?)",
                     [("a", 1, "rxn1"), ("a", 2, "rxn2"), ("b", 1, "rxn1")])
    conn.commit(); conn.close()
    out = load_reaction_sets_from_predictions(p, topk=20)
    assert out == {"a": ["rxn1", "rxn2"], "b": ["rxn1"]}


def test_predictions_parquet(tmp_path):
    pq = pytest.importorskip("pyarrow.parquet")
    pa = pytest.importorskip("pyarrow")
    p = tmp_path / "preds.parquet"
    pq.write_table(pa.table({"query_id": ["a", "a", "b"], "rank": [1, 2, 1],
                             "reaction_id": ["rxn1", "rxn2", "rxn9"]}), p)
    out = load_reaction_sets_from_predictions(p, topk=20)
    assert out == {"a": ["rxn1", "rxn2"], "b": ["rxn9"]}


def test_predictions_parquet_bad_schema(tmp_path):
    pq = pytest.importorskip("pyarrow.parquet")
    pa = pytest.importorskip("pyarrow")
    p = tmp_path / "bad.parquet"
    pq.write_table(pa.table({"query_id": ["a"], "foo": [1]}), p)
    with pytest.raises(ValueError, match="missing prediction columns"):
        load_reaction_sets_from_predictions(p)
