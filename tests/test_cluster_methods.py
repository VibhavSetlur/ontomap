"""Tests for selectable clustering methods (ontomap 1.8.0)."""
from __future__ import annotations

import pytest

from ontomap.cluster import cluster_reaction_sets, CLUSTER_METHODS


def _synthetic():
    # two clear synonym groups + one singleton
    return {
        "a1": ["rxn1", "rxn2", "rxn3", "rxn4"],
        "a2": ["rxn1", "rxn2", "rxn3", "rxn5"],
        "a3": ["rxn1", "rxn2", "rxn4", "rxn5"],
        "b1": ["rxn10", "rxn11", "rxn12"],
        "b2": ["rxn10", "rxn11", "rxn13"],
        "z1": ["rxn90", "rxn91"],
    }


@pytest.mark.parametrize("method", CLUSTER_METHODS)
def test_each_method_runs_and_respects_cap(method):
    rs = _synthetic()
    res = cluster_reaction_sets(rs, method=method, threshold=0.3, cap=5, topk=20)
    # every query assigned exactly once
    assert set(res.assignments) == set(rs)
    # hard cap honoured
    assert max(c["size"] for c in res.clusters.values()) <= 5
    # provenance records the algorithm
    assert res.params["algorithm"] == method


@pytest.mark.parametrize("method", CLUSTER_METHODS)
def test_each_method_groups_obvious_synonyms(method):
    rs = _synthetic()
    res = cluster_reaction_sets(rs, method=method, threshold=0.3, cap=5, topk=20)
    # a1/a2/a3 share 2-3 reactions -> should land together under every method
    a = {res.assignments["a1"], res.assignments["a2"], res.assignments["a3"]}
    assert len(a) == 1, f"{method} failed to group the a-family: {a}"


def test_invalid_method_raises():
    with pytest.raises(ValueError, match="method must be one of"):
        cluster_reaction_sets(_synthetic(), method="not_a_method")


def test_cap_below_one_raises():
    with pytest.raises(ValueError, match="cap must be"):
        cluster_reaction_sets(_synthetic(), method="cc", cap=0)


def test_cc_is_default():
    res = cluster_reaction_sets(_synthetic())
    assert res.params["algorithm"] == "cc"


def test_stable_uuids_across_methods_for_same_partition():
    # cc on this synthetic data yields a deterministic partition; uuids stable across runs
    r1 = cluster_reaction_sets(_synthetic(), method="cc")
    r2 = cluster_reaction_sets(_synthetic(), method="cc")
    assert r1.assignments == r2.assignments
