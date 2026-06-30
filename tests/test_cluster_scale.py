"""Regression test for the v1.8.2 clustering scalability fix.

A giant reaction-hub component (one reaction shared by thousands of descriptions) used to make
clustering hang. This builds a synthetic version and asserts it (a) finishes quickly and (b) still
honours the hard cap.
"""
from __future__ import annotations

import time

from ontomap.cluster import cluster_reaction_sets, _min_shared_for_threshold


def test_min_shared_bound():
    # top-20 sets, t=0.3 -> need >= ceil(2*20*0.3/1.3) = 10 shared
    assert _min_shared_for_threshold(0.3, 20) == 10
    assert _min_shared_for_threshold(0.3, 0) == 1
    assert _min_shared_for_threshold(0.5, 10) >= 1


def test_giant_hub_terminates_and_caps():
    # 3000 descriptions all sharing ONE hub reaction (rxnHUB) + a little private structure.
    # Before the fix this blew up to ~millions of pairs and the cap-split looped.
    rs = {}
    for i in range(3000):
        rs[f"q{i}"] = ["rxnHUB", f"rxn_{i % 50}", f"rxn_{(i // 50) % 50 + 100}"]
    t0 = time.time()
    res = cluster_reaction_sets(rs, method="cc", threshold=0.3, cap=5, topk=20)
    elapsed = time.time() - t0
    assert elapsed < 60, f"clustering took {elapsed:.1f}s — scalability regression"
    # hard cap honoured
    assert max(res.size_histogram()) <= 5
    # every description assigned exactly once
    assert sum(c["size"] for c in res.clusters.values()) == 3000


def test_results_stable_on_small_set():
    # tight pairs still cluster together (behaviour unchanged by the fix)
    rs = {
        "a": ["r1", "r2", "r3", "r4"],
        "b": ["r1", "r2", "r3", "r4"],      # identical -> with a
        "c": ["z1", "z2", "z3", "z4"],
        "d": ["z1", "z2", "z3", "z4"],      # identical -> with c
        "e": ["q9"],                         # singleton
    }
    res = cluster_reaction_sets(rs, method="cc", threshold=0.3, cap=5, topk=20)
    # find cluster of a; b must be with it
    member_of = {q: cid for cid, c in res.clusters.items() for q in c["members"]}
    assert member_of["a"] == member_of["b"]
    assert member_of["c"] == member_of["d"]
    assert member_of["e"] not in (member_of["a"], member_of["c"])
