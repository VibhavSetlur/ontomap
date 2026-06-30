"""Tests for ontomap.cluster — reaction-output Jaccard clustering with hard size cap."""
from __future__ import annotations

import uuid

from ontomap.cluster import (
    cluster_reaction_sets,
    CLUSTER_NAMESPACE,
    DEFAULT_CAP,
)


def test_synonyms_cluster_together():
    # three near-identical reaction sets should form one cluster; a disjoint one stays alone
    rs = {
        "a": ["rxn1", "rxn2", "rxn3"],
        "b": ["rxn1", "rxn2", "rxn3"],
        "c": ["rxn1", "rxn2", "rxn4"],
        "z": ["rxn90", "rxn91"],
    }
    res = cluster_reaction_sets(rs, threshold=0.3, cap=5)
    assert res.assignments["a"] == res.assignments["b"] == res.assignments["c"]
    assert res.assignments["z"] != res.assignments["a"]
    assert res.n_clusters == 2


def test_hard_cap_is_never_exceeded():
    # 12 identical sets would form one size-12 component; cap must split it
    rs = {f"q{i}": ["rxn1", "rxn2", "rxn3", "rxn4"] for i in range(12)}
    res = cluster_reaction_sets(rs, threshold=0.3, cap=5)
    sizes = [c["size"] for c in res.clusters.values()]
    assert max(sizes) <= 5
    assert sum(sizes) == 12  # every query assigned exactly once


def test_every_query_assigned_once():
    rs = {f"q{i}": [f"rxn{i}", "rxnX"] for i in range(20)}
    res = cluster_reaction_sets(rs, threshold=0.3, cap=5)
    assert len(res.assignments) == 20
    # union of all cluster members == all ids, no dupes
    members = [m for c in res.clusters.values() for m in c["members"]]
    assert sorted(members) == sorted(rs.keys())


def test_uuid_is_stable_and_reproducible():
    rs = {"a": ["rxn1", "rxn2"], "b": ["rxn1", "rxn2"]}
    r1 = cluster_reaction_sets(rs, threshold=0.3, cap=5)
    r2 = cluster_reaction_sets(rs, threshold=0.3, cap=5)
    assert r1.assignments == r2.assignments
    cid = r1.assignments["a"]
    # uuid5 over sorted member ids in the cluster namespace
    expected = str(uuid.uuid5(CLUSTER_NAMESPACE, "a|b"))
    assert cid == expected


def test_singletons_get_own_cluster():
    rs = {"a": ["rxn1"], "b": ["rxn2"], "c": ["rxn3"]}
    res = cluster_reaction_sets(rs, threshold=0.3, cap=5)
    assert res.n_clusters == 3
    assert res.n_singletons == 3


def test_topk_truncation():
    # only top-2 used; a and b share their top-2 even though tails differ
    rs = {"a": ["rxn1", "rxn2", "rxn9"], "b": ["rxn1", "rxn2", "rxn8"]}
    res = cluster_reaction_sets(rs, threshold=0.5, cap=5, topk=2)
    assert res.assignments["a"] == res.assignments["b"]


def test_default_cap_value():
    assert DEFAULT_CAP == 5
