"""Pre-council clustering of function descriptions by reaction-prediction overlap.

The 48-genome annotation pipeline (Henry/Faria/Setlur) inverts the old flow: instead
of running the LLM council on each function description individually, it FIRST groups
descriptions that ontomap maps to overlapping ModelSEED reaction sets, then submits each
small group to the council as a unit for a single shared-reaction (synonymy) decision.

This module produces those groups. The design follows the empirical method bake-off
(workspace step 51) and Henry's cluster-size verdict:

  * Cluster on the JACCARD overlap of each description's top-k ModelSEED reaction
    predictions (the AutoMap / ontomap output), NOT on description embeddings. The
    bake-off showed embedding/k-means clustering cannot respect a small size cap
    (51-97% of items landed in oversized clusters), while reaction-output Jaccard
    plus a hierarchical cap keeps every cluster within bounds and biologically tight.
  * Connected components on a graph with an edge wherever Jaccard >= ``threshold``.
  * HARD SIZE CAP via hierarchical sub-clustering: any component larger than ``cap``
    is recursively re-clustered at a tightened threshold until every piece is <= cap.
    This is the "tighten Jaccard until each sub-piece is <= 5" rule from the meeting,
    NOT random batching (which destroys the natural biology the synonymy verdict needs).

Henry's verdict (head-to-head on the Acidovorax pilot): council inter-model agreement
is strong at sizes 2-3, degrades at 5-8, and collapses past 10; schema validity drops at
12+. So the safe-by-default cap is 5, with 2-3 the sweet spot.

Each cluster gets a stable UUID (uuid5 over its sorted member ids) so cluster ids are
reproducible across runs and can be linked back to per-description provenance in the
parquet aggregator and to the council's per-cluster decision.

Public API:
    cluster_reaction_sets(...)   -> ClusterResult   (the production method)
    cluster_embeddings(...)      -> ClusterResult   (the embedding comparator, documented)
    ClusterResult                 dataclass with assignments + per-cluster metadata
"""
from __future__ import annotations

import itertools
import uuid
from collections import defaultdict
from dataclasses import dataclass, field

# Stable namespace so cluster UUIDs are reproducible across runs / machines.
CLUSTER_NAMESPACE = uuid.UUID("6f6e746f-6d61-7063-6c75-737465720001")

DEFAULT_THRESHOLD = 0.3
DEFAULT_CAP = 5
DEFAULT_TOPK = 20


@dataclass
class ClusterResult:
    """Result of clustering a set of queries by reaction-prediction overlap.

    assignments: query_id -> cluster_uuid (every query gets exactly one;
        singletons get their own single-member cluster uuid).
    clusters:    cluster_uuid -> dict(members=[query_id,...], size, cohesion,
        representative). ``representative`` is the member with the largest reaction
        set (the most informative description in the group).
    params:      the knobs used, for provenance.
    """
    assignments: dict[str, str]
    clusters: dict[str, dict]
    params: dict = field(default_factory=dict)

    @property
    def n_clusters(self) -> int:
        return len(self.clusters)

    @property
    def n_singletons(self) -> int:
        return sum(1 for c in self.clusters.values() if c["size"] == 1)

    def size_histogram(self) -> dict[int, int]:
        hist: dict[int, int] = defaultdict(int)
        for c in self.clusters.values():
            hist[c["size"]] += 1
        return dict(sorted(hist.items()))


# ---------------------------------------------------------------------------
# Jaccard helpers
# ---------------------------------------------------------------------------
def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    u = len(a | b)
    return len(a & b) / u if u else 0.0


def _min_shared_for_threshold(thresh: float, max_set: int) -> int:
    """Minimum number of shared reactions a pair can have and still reach Jaccard>=thresh.

    Jaccard = s / (|A|+|B|-s). With |A|,|B| <= K the union is minimised (Jaccard maximised)
    when both sets are as small as the shared count allows, but the *necessary* condition for
    ANY pair is s/(|A|+|B|-s) >= t with |A|,|B| <= K, i.e. the easiest case |A|=|B|=s gives
    Jaccard 1; the HARDEST (largest union) at fixed s is |A|=|B|=K, giving s/(2K-s) >= t
    => s >= 2Kt/(1+t). Any pair below that bound CANNOT reach the threshold, so we can prune
    it without computing Jaccard. Returns a safe floor (>=1).
    """
    if max_set <= 0:
        return 1
    bound = (2 * max_set * thresh) / (1 + thresh)
    import math
    return max(1, math.ceil(bound - 1e-9))


def _build_adjacency(sets: list[set], thresh: float) -> dict[int, set]:
    """Adjacency via a reaction -> items inverted index.

    Scales to >100k items with a giant hub reaction (>10k members) by pruning on the number
    of SHARED reactions before ever computing Jaccard. For top-k sets of size <= K, a pair
    needs at least ``_min_shared_for_threshold`` shared reactions to possibly reach the
    Jaccard threshold; we count co-occurrences per candidate pair via the inverted index and
    only Jaccard-test the survivors. This turns the pathological ~10^9-pair hub into the small
    set of pairs that actually share enough reactions to matter.
    """
    inv: dict[str, list[int]] = defaultdict(list)
    max_set = 0
    for i, s in enumerate(sets):
        if len(s) > max_set:
            max_set = len(s)
        for r in s:
            inv[r].append(i)
    min_shared = _min_shared_for_threshold(thresh, max_set)

    # Per-item candidate generation (memory bounded by one item's candidates, never the
    # global ~10^9 pair space). For item i we only look at partners j < i that co-occur in
    # i's (<=K) reaction postings; a Counter tallies shared reactions and we keep only those
    # reaching min_shared before the (rare) Jaccard test. This is the prefix-style set-
    # similarity join and stays fast even when one reaction links >10k items.
    adj: dict[int, set] = defaultdict(set)
    from collections import Counter as _Counter
    for i in range(len(sets)):
        cand: _Counter = _Counter()
        for r in sets[i]:
            for j in inv[r]:
                if j < i:
                    cand[j] += 1
        si = sets[i]
        for j, c in cand.items():
            if c >= min_shared and _jaccard(si, sets[j]) >= thresh:
                adj[i].add(j)
                adj[j].add(i)
    return adj


def _connected_components(n: int, adj: dict[int, set]) -> list[list[int]]:
    seen = [False] * n
    comps: list[list[int]] = []
    for start in range(n):
        if seen[start]:
            continue
        stack, comp = [start], []
        seen[start] = True
        while stack:
            u = stack.pop()
            comp.append(u)
            for v in adj.get(u, ()):  # type: ignore[arg-type]
                if not seen[v]:
                    seen[v] = True
                    stack.append(v)
        comps.append(comp)
    return comps


def _components_at(sets: list[set], members: list[int], thresh: float) -> list[list[int]]:
    """Connected components within a subset of items, at a given threshold.
    Returns lists of ORIGINAL indices."""
    local = [sets[m] for m in members]
    adj = _build_adjacency(local, thresh)
    return [[members[p] for p in piece]
            for piece in _connected_components(len(local), adj)]


def _enforce_cap(sets: list[set], comp: list[int], thresh: float, cap: int,
                 step: float = 0.05, max_t: float = 0.97,
                 big: int = 4000) -> list[list[int]]:
    """Split an oversized component until every sub-piece has <= cap members.

    Strategy: tighten the Jaccard threshold and recompute connected components within the
    piece. To stay fast on a giant reaction-hub component (which can be tens of thousands of
    near-tied descriptions), pieces larger than ``big`` use an ACCELERATED schedule — the
    threshold jumps geometrically toward ``max_t`` instead of crawling by ``step`` — and any
    piece that is still larger than ``big`` once the threshold is near ``max_t`` (i.e. it is a
    genuinely dense blob that overlap can't separate) is finished by deterministic size-cap
    chunking. This guarantees termination + bounded work while still honouring the hard cap,
    and only the irreducible hub falls back to chunking (the council adjudicates each <=5
    group regardless).
    """
    out: list[list[int]] = []
    queue: list[tuple[list[int], float]] = [(comp, thresh)]
    while queue:
        members, t = queue.pop()
        if len(members) <= cap:
            out.append(members)
            continue
        # choose next threshold: accelerate hard on big pieces to avoid many full re-passes
        if len(members) > big:
            t2 = round(min(max_t, t + max(step, (max_t - t) * 0.5)), 4)
        else:
            t2 = round(t + step, 4)
        if t2 >= max_t:
            # near the ceiling: stop tightening, chunk deterministically (always <= cap)
            members_sorted = sorted(members)
            for k in range(0, len(members_sorted), cap):
                out.append(members_sorted[k:k + cap])
            continue
        pieces = _components_at(sets, members, t2)
        if len(pieces) == 1 and len(pieces[0]) == len(members):
            # tightening did not split it; try again at the (already accelerated) higher t
            queue.append((members, t2))
            continue
        for piece in pieces:
            queue.append((piece, t2))
    return out


# ---------------------------------------------------------------------------
# UUID + metadata
# ---------------------------------------------------------------------------
def _cluster_uuid(member_ids: list[str]) -> str:
    key = "|".join(sorted(member_ids))
    return str(uuid.uuid5(CLUSTER_NAMESPACE, key))


def _cohesion(members: list[int], sets: list[set]) -> float:
    if len(members) < 2:
        return 1.0
    sims = [_jaccard(sets[a], sets[b]) for a, b in itertools.combinations(members, 2)]
    return sum(sims) / len(sims) if sims else 1.0


def _finalize(comps: list[list[int]], ids: list[str], sets: list[set],
              params: dict) -> ClusterResult:
    assignments: dict[str, str] = {}
    clusters: dict[str, dict] = {}
    for comp in comps:
        member_ids = [ids[i] for i in comp]
        cid = _cluster_uuid(member_ids)
        rep = max(comp, key=lambda i: len(sets[i]))
        clusters[cid] = {
            "members": member_ids,
            "size": len(comp),
            "cohesion": round(_cohesion(comp, sets), 4),
            "representative": ids[rep],
        }
        for mid in member_ids:
            assignments[mid] = cid
    return ClusterResult(assignments=assignments, clusters=clusters, params=params)


# ---------------------------------------------------------------------------
# Public: reaction-output clustering (production)
# ---------------------------------------------------------------------------
CLUSTER_METHODS = ("cc", "louvain", "label_prop", "agglomerative", "hdbscan")
# Components larger than this are always handled by the cc-tighten splitter, regardless of
# method: O(m^2) pairwise methods (agglomerative/hdbscan) cannot build a distance matrix on
# the data's giant reaction-hub component (~30k nodes), and it is held constant for fairness.
_MAX_DENSE = 2000


def _refine_component(sets: list[set], comp: list[int], method: str,
                      threshold: float, cap: int) -> list[list[int]]:
    """Refine ONE connected component into sub-clusters using ``method``.

    All methods operate inside the natural Jaccard>=threshold component and return a list of
    member-index groups (pre-cap). The caller applies the hard cap. Components above _MAX_DENSE,
    or methods unavailable in the environment, fall back to the cc baseline (tighten-split).
    """
    if len(comp) <= 1:
        return [comp]
    if method == "cc" or len(comp) > _MAX_DENSE:
        return [comp]  # caller applies _enforce_cap; cc == the natural component as-is
    try:
        if method in ("louvain", "label_prop"):
            return _refine_graph(sets, comp, method, threshold)
        if method == "agglomerative":
            return _refine_agglomerative(sets, comp, threshold)
        if method == "hdbscan":
            return _refine_hdbscan(sets, comp)
    except Exception:
        return [comp]  # any backend hiccup -> safe cc fallback
    return [comp]


def _component_subgraph(sets: list[set], comp: list[int], threshold: float):
    import networkx as nx
    G = nx.Graph(); G.add_nodes_from(comp)
    inv: dict[str, list[int]] = defaultdict(list)
    for idx in comp:
        for r in sets[idx]:
            inv[r].append(idx)
    seen: set[tuple[int, int]] = set()
    for bucket in inv.values():
        if len(bucket) < 2:
            continue
        for a in range(len(bucket)):
            for b in range(a + 1, len(bucket)):
                i, j = bucket[a], bucket[b]
                key = (i, j) if i < j else (j, i)
                if key in seen:
                    continue
                seen.add(key)
                w = _jaccard(sets[i], sets[j])
                if w >= threshold:
                    G.add_edge(i, j, weight=w)
    return G


def _refine_graph(sets, comp, method, threshold):
    G = _component_subgraph(sets, comp, threshold)
    if method == "louvain":
        from networkx.algorithms.community import louvain_communities
        comms = louvain_communities(G, weight="weight", resolution=1.0, seed=17)
    else:  # label_prop
        from networkx.algorithms.community import asyn_lpa_communities
        comms = asyn_lpa_communities(G, weight="weight", seed=17)
    return [list(c) for c in comms]


def _distance_matrix(sets, comp):
    import numpy as np
    m = len(comp)
    D = np.zeros((m, m))
    for a in range(m):
        for b in range(a + 1, m):
            d = 1.0 - _jaccard(sets[comp[a]], sets[comp[b]])
            D[a, b] = D[b, a] = d
    return D


def _refine_agglomerative(sets, comp, threshold):
    if len(comp) < 3:
        return [comp]
    from scipy.cluster.hierarchy import linkage, fcluster
    from scipy.spatial.distance import squareform
    Z = linkage(squareform(_distance_matrix(sets, comp), checks=False), method="average")
    fl = fcluster(Z, t=1.0 - threshold, criterion="distance")
    sub: dict[int, list[int]] = defaultdict(list)
    for idx, lab in zip(comp, fl):
        sub[lab].append(idx)
    return list(sub.values())


def _refine_hdbscan(sets, comp):
    if len(comp) < 5:
        return [comp]
    from sklearn.cluster import HDBSCAN
    fl = HDBSCAN(metric="precomputed", min_cluster_size=2, allow_single_cluster=True,
                 copy=True).fit_predict(_distance_matrix(sets, comp))
    sub: dict = defaultdict(list)
    for idx, lab in zip(comp, fl):
        sub[lab if lab >= 0 else f"noise{idx}"].append(idx)
    return list(sub.values())


def cluster_reaction_sets(
    reaction_sets: dict[str, list[str]] | list[tuple[str, list[str]]],
    *,
    method: str = "cc",
    threshold: float = DEFAULT_THRESHOLD,
    cap: int = DEFAULT_CAP,
    topk: int = DEFAULT_TOPK,
) -> ClusterResult:
    """Cluster queries by Jaccard overlap of their top-k ModelSEED reaction predictions.

    Args:
        reaction_sets: mapping query_id -> ordered list of predicted reaction ids
            (rank order; only the top ``topk`` are used), or a list of (query_id,
            reaction_ids) pairs.
        method: how to refine each natural Jaccard component into sub-clusters. One of
            ``cluster.CLUSTER_METHODS``:
              - ``"cc"`` (default): connected components + hierarchical tighten-split.
                Best stability + simplest + the only method that scales to the giant
                reaction-hub component. The validated production method (step 55 bake-off).
              - ``"louvain"`` / ``"label_prop"``: graph community detection (slightly more
                aggressive merging; needs ``networkx``).
              - ``"agglomerative"`` / ``"hdbscan"``: pairwise-distance methods (need
                ``scipy`` / ``scikit-learn``). They fall back to ``cc`` on components larger
                than ``cluster._MAX_DENSE`` because an O(m^2) distance matrix cannot be built
                on the ~30k-node hub.
            All methods enforce the same hard ``cap`` and are within ~1.6% of each other on
            real data (step 55), so ``cc`` is the recommended default.
        threshold: Jaccard edge threshold. Lower => more / larger clusters. 0.3 is the
            validated production default.
        cap: hard maximum cluster size. Oversized pieces are split by hierarchical
            threshold-tightening, never random batching.
        topk: how many top reactions per query feed the Jaccard (default 20).

    Returns:
        ClusterResult with a stable UUID per cluster.

    Raises:
        ValueError: if ``cap < 1`` or ``method`` is not in ``CLUSTER_METHODS``.
    """
    if cap < 1:
        raise ValueError("cap must be >= 1")
    if method not in CLUSTER_METHODS:
        raise ValueError(f"method must be one of {CLUSTER_METHODS}, got {method!r}")
    items = reaction_sets.items() if isinstance(reaction_sets, dict) else list(reaction_sets)
    ids: list[str] = []
    sets: list[set] = []
    for qid, rxns in items:
        ids.append(qid)
        sets.append(set(list(rxns)[:topk]))

    adj = _build_adjacency(sets, threshold)
    base = _connected_components(len(sets), adj)

    final_comps: list[list[int]] = []
    for comp in base:
        for piece in _refine_component(sets, comp, method, threshold, cap):
            if len(piece) <= cap:
                final_comps.append(piece)
            else:
                final_comps.extend(_enforce_cap(sets, piece, threshold, cap))

    params = {"method": f"reaction_jaccard_{method}_capped", "algorithm": method,
              "threshold": threshold, "cap": cap, "topk": topk}
    return _finalize(final_comps, ids, sets, params)


def cluster_result_to_rows(result: "ClusterResult") -> list[dict]:
    """Flatten a ClusterResult to one row per (query_id, cluster) for a parquet/TSV
    cluster-UUID file — the artefact the genome annotation aggregator joins on."""
    rows = []
    for cid, c in result.clusters.items():
        for qid in c["members"]:
            rows.append({
                "query_id": qid,
                "cluster_id": cid,
                "cluster_size": c["size"],
                "cohesion": c["cohesion"],
                "representative": c["representative"],
                "is_representative": int(qid == c["representative"]),
            })
    return rows


def load_reaction_sets_from_predictions(path, *, topk: int = DEFAULT_TOPK) -> dict[str, list[str]]:
    """Load query_id -> ordered reaction-id list from an ontomap predictions artefact.

    Supports the shapes ontomap emits:
      - .sqlite/.db: reads the `predictions` table (query_id, rank, reaction_id).
      - .parquet: a table with query_id, rank, reaction_id columns.
      - .jsonl: one rich-dict per line ({query:{id}, predictions:[{reaction_id}]}) OR the
        compact {query_id, top_ids|predictions} shape.
      - .json: a JSON array of rich dicts.

    Raises FileNotFoundError if the path is missing, and a clear ValueError if a
    SQLite/parquet input lacks the expected predictions schema.
    """
    import json as _json
    from pathlib import Path as _Path
    p = _Path(path)
    if not p.exists():
        raise FileNotFoundError(f"predictions file not found: {p}")
    suffix = p.suffix.lower()

    def _from_rich(rec):
        qid = rec.get("query_id") or (rec.get("query") or {}).get("id")
        if "top_ids" in rec:
            rxns = list(rec["top_ids"])
        else:
            rxns = [pr["reaction_id"] for pr in rec.get("predictions", [])]
        return qid, rxns[:topk]

    if suffix in (".sqlite", ".db", ".sqlite3"):
        import sqlite3 as _sql
        conn = _sql.connect(str(p))
        try:
            has_tbl = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='predictions'"
            ).fetchone()
            if not has_tbl:
                raise ValueError(
                    f"{p.name} has no `predictions` table — is this an ontomap predictions "
                    "SQLite? (expected columns: query_id, rank, reaction_id)")
            rows = conn.execute(
                "SELECT query_id, rank, reaction_id FROM predictions WHERE rank<=? "
                "ORDER BY query_id, rank", (topk,)).fetchall()
        finally:
            conn.close()
        out: dict[str, list[str]] = {}
        for qid, _rank, rxn in rows:
            out.setdefault(qid, []).append(rxn)
        return out

    if suffix == ".parquet":
        try:
            import pyarrow.parquet as _pq
        except ImportError as e:
            raise ImportError("install pyarrow to read parquet predictions") from e
        tbl = _pq.read_table(p)
        cols = set(tbl.column_names)
        need = {"query_id", "rank", "reaction_id"}
        if not need.issubset(cols):
            raise ValueError(
                f"{p.name} missing prediction columns {need - cols}; has {sorted(cols)}")
        d = tbl.to_pydict()
        triples = sorted(zip(d["query_id"], d["rank"], d["reaction_id"]),
                         key=lambda t: (str(t[0]), t[1]))
        out = {}
        for qid, rank, rxn in triples:
            if rank <= topk:
                out.setdefault(str(qid), []).append(rxn)
        return out

    if suffix == ".jsonl" or suffix == ".ndjson":
        out = {}
        with p.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                qid, rxns = _from_rich(_json.loads(line))
                if qid:
                    out[qid] = rxns
        return out

    if suffix == ".json":
        data = _json.loads(p.read_text())
        out = {}
        for rec in data:
            qid, rxns = _from_rich(rec)
            if qid:
                out[qid] = rxns
        return out

    raise ValueError(f"unsupported predictions format for clustering: {p.name}")


# ---------------------------------------------------------------------------
# Public: embedding clustering (documented comparator from the meeting)
# ---------------------------------------------------------------------------
def cluster_embeddings(
    ids: list[str],
    embeddings,
    *,
    target_mean_size: int = 8,
    random_state: int = 17,
    reaction_sets: dict[str, list[str]] | None = None,
    topk: int = DEFAULT_TOPK,
) -> ClusterResult:
    """Embedding-based comparator: cosine k-means over description embeddings.

    Implemented because the meeting asked for a head-to-head of reaction-output vs
    embedding clustering. NOTE: the step-51 bake-off found this CANNOT respect a small
    hard size cap (k-means cluster sizes are highly uneven), so it is provided for
    comparison/diagnostics, not as the production path. ``cluster_reaction_sets`` is the
    production method.

    Args:
        ids: query ids, aligned row-for-row with ``embeddings``.
        embeddings: (n, d) array of L2-normalised description vectors.
        target_mean_size: k is chosen as n // target_mean_size.
        reaction_sets: optional, only used to report cohesion on the reaction sets.
    """
    import numpy as np
    from sklearn.cluster import MiniBatchKMeans

    emb = np.asarray(embeddings, dtype="float32")
    if emb.shape[0] != len(ids):
        raise ValueError("ids and embeddings must have the same length")
    k = max(2, min(emb.shape[0] - 1, emb.shape[0] // max(1, target_mean_size)))
    labels = MiniBatchKMeans(n_clusters=k, random_state=random_state, n_init=1,
                             batch_size=512).fit_predict(emb)
    groups: dict[int, list[int]] = defaultdict(list)
    for i, lab in enumerate(labels):
        groups[lab].append(i)

    # cohesion needs reaction sets; fall back to empty sets if not provided
    sets = ([set(list((reaction_sets or {}).get(q, []))[:topk]) for q in ids]
            if reaction_sets else [set() for _ in ids])
    comps = list(groups.values())
    params = {"method": "embedding_kmeans", "k": k,
              "target_mean_size": target_mean_size}
    return _finalize(comps, ids, sets, params)
