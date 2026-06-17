"""ontomap.modelmap — compound & reaction mapping for whole metabolic models.

NEW in ontomap 1.5.0 (added alongside the existing SSO/KO/RAST → reaction
`Pipeline`, not replacing it).

Where `Pipeline` maps a *functional annotation* to ModelSEED reactions,
`modelmap` maps the *entities of an existing metabolic model* — every
metabolite and every reaction — from a foreign namespace onto ModelSEED
ids. This is the task of integrating a published model (e.g. an
*A. baylyi* / ADP1 reconstruction whose ids don't match ModelSEED) into a
ModelSEED-namespaced workflow.

Two mappers:

  CompoundMapper  — maps a metabolite *name* (+ optional formula/charge/
                    db-refs, + optional reaction-network context) to a
                    ranked list of ModelSEED compound ids. SapBERT
                    multi-synonym embedding + an exact normalized-synonym
                    index + an optional reaction-network consistency rerank.

  ReactionMapper  — maps a reaction (name + its metabolite set, the latter
                    mapped through CompoundMapper) to a ranked list of
                    ModelSEED reaction ids. SapBERT name embedding unioned
                    with a stoichiometric compound-set overlap signal,
                    over the ACTIVE reaction corpus.

Validated on the published ADP1 model (held-out gold, names only):
  compounds  hit@1 0.93, hit@10 1.00 (network rerank)
  reactions  hit@1 0.82, hit@10 0.97 (name + compound-set, active corpus)
See ontomap/docs/COMPOUND_REACTION_MAPPING.md for the full study, data
limitations, and figures.

Quick start
-----------
    from ontomap.modelmap import CompoundMapper, ReactionMapper, map_model

    cm = CompoundMapper.from_modelseed(modelseed_dir="data/raw/modelseed")
    cm.build()
    cm.map("pimelate")[0]            # -> ('cpd01727', score, signals)

    # or map an entire COBRA-style model dict in one call:
    out = map_model(model_json, modelseed_dir="data/raw/modelseed")
    out["compounds"]["CPD_DASH_205_Cytosol"]   # ranked cpd ids
    out["reactions"]["rxn12357_c0"]            # ranked rxn ids
"""
from __future__ import annotations

import csv
import json
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np

try:
    from ontomap import _paths
except Exception:  # pragma: no cover - allows standalone use
    _paths = None

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

# --------------------------------------------------------------------------
# Normalization
# --------------------------------------------------------------------------
_GREEK = {"α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon",
          "ζ": "zeta", "η": "eta", "θ": "theta", "κ": "kappa", "λ": "lambda",
          "μ": "mu", "ν": "nu", "π": "pi", "ρ": "rho", "σ": "sigma", "τ": "tau",
          "φ": "phi", "χ": "chi", "ψ": "psi", "ω": "omega", "→": " ", "’": "'"}

# Ubiquitous cofactors excluded from reaction compound-set overlap.
UBIQUITOUS = {"cpd00001", "cpd00067", "cpd00012", "cpd00009", "cpd00002",
              "cpd00008", "cpd00018", "cpd00003", "cpd00004", "cpd00005",
              "cpd00006", "cpd00010", "cpd00011", "cpd00013"}

EXACT_BONUS = 1.0
NETWORK_LAMBDA = 0.5


def norm_display(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    for k, v in _GREEK.items():
        s = s.replace(k, v)
    return re.sub(r"\s+", " ", s).strip()


def norm_key(s: str) -> str:
    if not s:
        return ""
    s = norm_display(s).lower().replace("(+)", "").replace("(-)", "")
    return re.sub(r"[^a-z0-9]+", "", s)


def parse_aliases(field_val: str):
    """Return (synonym_names, {namespace: [ids]}) from a ModelSEED aliases field."""
    names, refs = [], {}
    if not field_val or field_val == "null":
        return names, refs
    for chunk in str(field_val).split("|"):
        if ":" not in chunk:
            continue
        ns, vals = chunk.split(":", 1)
        items = [v.strip() for v in vals.split(";") if v.strip()]
        if not items:
            continue
        if ns.strip().lower() == "name":
            names.extend(items)
        else:
            refs.setdefault(ns.strip(), []).extend(items)
    return names, refs


# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------
@dataclass
class CompoundRec:
    id: str
    name: str
    formula: str | None
    charge: int | None
    inchikey: str | None
    is_core: bool
    is_obsolete: bool
    synonyms: list[str] = field(default_factory=list)
    db_refs: dict[str, list[str]] = field(default_factory=dict)

    @property
    def inchikey_skeleton(self):
        return self.inchikey.split("-")[0] if self.inchikey else None


@dataclass
class ReactionRec:
    id: str
    name: str
    ec: list[str]
    pathways: list[str]
    compound_ids: set
    status: str | None
    is_obsolete: bool
    synonyms: list[str] = field(default_factory=list)


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _resolve_modelseed_dir(modelseed_dir=None) -> Path:
    """Resolve the ModelSEED biochemistry dir (compounds.tsv + reactions.tsv).

    Order: explicit arg → $ONTOMAP_MODELSEED → bundled ontomap/data/modelseed
    (see SETUP_ASSETS.md to populate it). Raises with guidance if not found.
    """
    import os
    if modelseed_dir is not None:
        return Path(modelseed_dir)
    env = os.environ.get("ONTOMAP_MODELSEED")
    if env:
        return Path(env)
    if _paths is not None:
        try:
            cand = _paths.data_dir() / "modelseed"
            if (cand / "compounds.tsv").exists():
                return cand
        except Exception:
            pass
    # file-relative fallback: packaged ontomap/data/modelseed (robust to import-name collisions)
    cand = Path(__file__).resolve().parent.parent / "data" / "modelseed"
    if (cand / "compounds.tsv").exists():
        return cand
    raise FileNotFoundError(
        "ModelSEED dir not found. Pass modelseed_dir=, set $ONTOMAP_MODELSEED, "
        "or populate ontomap/data/modelseed/{compounds,reactions}.tsv "
        "(see ontomap/SETUP_ASSETS.md).")


def load_compounds(modelseed_dir=None) -> dict[str, CompoundRec]:
    modelseed_dir = _resolve_modelseed_dir(modelseed_dir)
    out = {}
    with open(Path(modelseed_dir) / "compounds.tsv") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            syn, refs = parse_aliases(row.get("aliases", ""))
            name = (row.get("name") or "").strip()
            abbr = (row.get("abbreviation") or "").strip()
            allsyn = [s for s in dict.fromkeys([name, abbr, *syn]) if s and s != "null"]
            ik = (row.get("inchikey") or "").strip()
            out[row["id"]] = CompoundRec(
                id=row["id"], name=name,
                formula=(row.get("formula") or "").strip() or None,
                charge=_int(row.get("charge")), inchikey=ik or None,
                is_core=row.get("is_core") == "1",
                is_obsolete=row.get("is_obsolete") == "1",
                synonyms=allsyn, db_refs=refs)
    return out


def load_reactions(modelseed_dir=None) -> dict[str, ReactionRec]:
    modelseed_dir = _resolve_modelseed_dir(modelseed_dir)
    out = {}
    with open(Path(modelseed_dir) / "reactions.tsv") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            syn, _ = parse_aliases(row.get("aliases", ""))
            name = (row.get("name") or "").strip()
            ec_raw = (row.get("ec_numbers") or "").strip()
            ec = [e.strip() for e in re.split(r"[|;]", ec_raw) if e.strip()] \
                if ec_raw and ec_raw != "null" else []
            cids = {c.strip() for c in (row.get("compound_ids") or "").split(";") if c.strip()}
            pw = (row.get("pathways") or "").strip()
            pathways = [p.strip() for p in pw.split(";") if p.strip()] if pw and pw != "null" else []
            allsyn = [s for s in dict.fromkeys([name, *syn]) if s and s != "null"]
            out[row["id"]] = ReactionRec(
                id=row["id"], name=name, ec=ec, pathways=pathways, compound_ids=cids,
                status=(row.get("status") or "").strip() or None,
                is_obsolete=row.get("is_obsolete") == "1", synonyms=allsyn)
    return out


# --------------------------------------------------------------------------
# Encoder
# --------------------------------------------------------------------------
class _SapBERT:
    def __init__(self, device="auto", weights_dir: Path | None = None):
        from sentence_transformers import SentenceTransformer
        import torch
        if device == "auto":
            device = "cuda:0" if torch.cuda.is_available() else "cpu"
        self.device = device
        if weights_dir is None and _paths is not None:
            weights_dir = _paths.sapbert_dir()
        try:
            self.model = SentenceTransformer(str(weights_dir), device=device)
        except Exception:
            self.model = SentenceTransformer(
                "cambridgeltl/SapBERT-from-PubMedBERT-fulltext", device=device)

    def encode(self, texts, batch_size=512):
        return self.model.encode([norm_display(t) or " " for t in texts],
                                 batch_size=batch_size, show_progress_bar=False,
                                 normalize_embeddings=True,
                                 convert_to_numpy=True).astype("float32")


def _faiss_topk(q, corpus, k):
    import faiss
    idx = faiss.IndexFlatIP(corpus.shape[1])
    idx.add(corpus)
    return idx.search(q.astype("float32"), k)


# --------------------------------------------------------------------------
# Compound mapper
# --------------------------------------------------------------------------
class CompoundMapper:
    """Map metabolite names to ModelSEED compound ids."""

    def __init__(self, compounds: dict[str, CompoundRec], encoder: _SapBERT,
                 include_obsolete: bool = False):
        self.compounds = compounds
        self.enc = encoder
        self.include_obsolete = include_obsolete
        self._built = False

    @classmethod
    def from_modelseed(cls, modelseed_dir=None, device="auto", weights_dir=None,
                       include_obsolete=False) -> "CompoundMapper":
        return cls(load_compounds(modelseed_dir), _SapBERT(device, weights_dir),
                   include_obsolete)

    def build(self) -> "CompoundMapper":
        cids, txt, exact, seen = [], [], {}, set()
        for cid, c in self.compounds.items():
            if c.is_obsolete and not self.include_obsolete:
                continue
            for syn in c.synonyms:
                k = norm_key(syn)
                if not k:
                    continue
                exact.setdefault(k, set()).add(cid)
                if (cid, k) in seen:
                    continue
                seen.add((cid, k))
                cids.append(cid)
                txt.append(syn)
        self.syn_cid = np.array(cids)
        self.exact = exact
        self.syn_emb = self.enc.encode(txt)
        self._built = True
        return self

    def map_many(self, names: list[str], top_k=20, n_retrieve=200, use_exact=True):
        if not self._built:
            self.build()
        q = self.enc.encode(names)
        # retrieve enough synonym vectors that, after dedup to unique cpd ids,
        # the candidate pool comfortably exceeds top_k (each cpd has many synonyms)
        k_ret = min(max(n_retrieve, top_k * 4), len(self.syn_emb))
        sims, idx = _faiss_topk(q, self.syn_emb, k_ret)
        out = []
        for qi, name in enumerate(names):
            cid_sim = {}
            for j in range(idx.shape[1]):
                cid = str(self.syn_cid[idx[qi, j]])
                s = float(sims[qi, j])
                if s > cid_sim.get(cid, -1):
                    cid_sim[cid] = s
            exact_cids = self.exact.get(norm_key(name), set()) if use_exact else set()
            for cid in exact_cids:
                cid_sim.setdefault(cid, 0.0)
            scored = []
            for cid, s in cid_sim.items():
                c = self.compounds[cid]
                sc = s + (EXACT_BONUS if cid in exact_cids else 0.0) \
                    + 0.001 * c.is_core - 0.002 * c.is_obsolete
                scored.append((cid, sc, {"emb": s, "exact": int(cid in exact_cids)}))
            scored.sort(key=lambda x: -x[1])
            out.append(scored[:top_k])
        return out

    def map(self, name: str, top_k=20):
        return self.map_many([name], top_k=top_k)[0]

    # -- network-aware mapping for a whole model --
    def map_model_compounds(self, local_names: dict[str, str],
                            local_to_neighbors: dict[str, set[str]],
                            top_k=20, network=True):
        """Map every local metabolite, optionally reranking by reaction-network
        consistency.

        local_names          : local_id -> name
        local_to_neighbors   : local_id -> set of neighbour local_ids (co-reactants)
        """
        if not self._built:
            self.build()
        ids = list(local_names)
        base = self.map_many([local_names[i] for i in ids], top_k=max(top_k, 20))
        ranked = {lid: r for lid, r in zip(ids, base)}
        if not network:
            return {lid: r[:top_k] for lid, r in ranked.items()}
        top1 = {lid: (r[0][0] if r else None) for lid, r in ranked.items()}
        # ModelSEED neighbour sets per candidate compound
        inv = defaultdict(set)
        # build reaction-membership lazily via compound co-occurrence is expensive;
        # instead use the model's own neighbour predictions vs candidate co-members.
        ms_neighbors = self._compound_cooccurrence()
        out = {}
        for lid in ids:
            npred = {top1[n] for n in local_to_neighbors.get(lid, set())
                     if top1.get(n) and top1[n] not in UBIQUITOUS}
            rescored = []
            for cid, sc, sig in ranked[lid]:
                nn = ms_neighbors.get(cid, set())
                net = (len(npred & nn) / max(1, len(npred))) if npred else 0.0
                rescored.append((cid, sc + NETWORK_LAMBDA * net, {**sig, "net": net}))
            rescored.sort(key=lambda x: -x[1])
            out[lid] = rescored[:top_k]
        return out

    def _compound_cooccurrence(self):
        if getattr(self, "_cooc", None) is not None:
            return self._cooc
        self._cooc = {}
        return self._cooc  # filled by ReactionMapper.attach_cooccurrence if available


# --------------------------------------------------------------------------
# Reaction mapper
# --------------------------------------------------------------------------
class ReactionMapper:
    """Map reactions (name + metabolite set) to ModelSEED reaction ids."""

    def __init__(self, reactions: dict[str, ReactionRec], encoder: _SapBERT,
                 include_obsolete: bool = False):
        self.reactions = reactions
        self.enc = encoder
        self.include_obsolete = include_obsolete
        self._built = False

    @classmethod
    def from_modelseed(cls, modelseed_dir=None, device="auto", weights_dir=None,
                       include_obsolete=False) -> "ReactionMapper":
        return cls(load_reactions(modelseed_dir), _SapBERT(device, weights_dir),
                   include_obsolete)

    def build(self) -> "ReactionMapper":
        rids, txt, inv, comp_of, seen = [], [], defaultdict(set), {}, set()
        for rid, r in self.reactions.items():
            if r.is_obsolete and not self.include_obsolete:
                continue
            comp_of[rid] = set(r.compound_ids)
            for cid in r.compound_ids:
                inv[cid].add(rid)
            for syn in (r.synonyms or [r.name]):
                k = norm_key(syn)
                if not k or (rid, k) in seen:
                    continue
                seen.add((rid, k))
                rids.append(rid)
                txt.append(syn)
        self.syn_rid = np.array(rids)
        self.inv = inv
        self.comp_of = comp_of
        self.syn_emb = self.enc.encode(txt)
        self._built = True
        return self

    def cooccurrence(self) -> dict[str, set]:
        """compound id -> set of compounds it co-occurs with in reactions (for CompoundMapper network rerank)."""
        cooc = defaultdict(set)
        for rid, cset in self.comp_of.items():
            core = [c for c in cset if c not in UBIQUITOUS]
            for c in core:
                cooc[c].update(x for x in core if x != c)
        return cooc

    @staticmethod
    def _core(s):
        return {c for c in s if c not in UBIQUITOUS}

    def _canon(self, rid):
        r = self.reactions[rid]
        if r.is_obsolete:
            return -1.0
        s = r.status or ""
        if s.startswith("OK"):
            return 1.0
        if "CPDFORMERROR" in s:
            return -0.3
        if s.startswith(("MI", "CI")):
            return 0.0
        return 0.3

    def map_many(self, names: list[str], compound_sets: list[set], top_k=20,
                 n_name=100, w_name=1.0, w_set=1.5, canon=True):
        """names[i] paired with compound_sets[i] = set of ModelSEED cpd ids for that reaction."""
        if not self._built:
            self.build()
        q = self.enc.encode(names)
        # scale name retrieval with top_k so the (name ∪ compound-set) pool can fill top_k
        k_name = min(max(n_name, top_k * 3), len(self.syn_emb))
        sims, idx = _faiss_topk(q, self.syn_emb, k_name)
        out = []
        for qi in range(len(names)):
            name_sim = {}
            for j in range(idx.shape[1]):
                rid = str(self.syn_rid[idx[qi, j]])
                s = float(sims[qi, j])
                if s > name_sim.get(rid, -1):
                    name_sim[rid] = s
            mapped_core = self._core(compound_sets[qi])
            # set candidates: reactions sharing >=2 mapped compounds
            from collections import Counter
            cnt = Counter()
            for cid in compound_sets[qi]:
                for rid in self.inv.get(cid, ()):
                    cnt[rid] += 1
            set_cands = {rid for rid, c in cnt.items() if c >= 2 or c == len(compound_sets[qi])}
            cand = set(name_sim) | set_cands
            scored = []
            for rid in cand:
                ccore = self._core(self.comp_of.get(rid, set()))
                inter = len(mapped_core & ccore)
                union = len(mapped_core | ccore) or 1
                jac = inter / union
                exact = 1.0 if (mapped_core and mapped_core == ccore) else 0.0
                nsim = name_sim.get(rid, 0.0)
                fused = w_name * nsim + w_set * (jac + 0.5 * exact)
                if canon:
                    fused += 0.30 * self._canon(rid)
                scored.append((rid, fused, {"name": nsim, "set_jac": jac, "exact_set": exact}))
            scored.sort(key=lambda x: -x[1])
            out.append(scored[:top_k])
        return out


# --------------------------------------------------------------------------
# Whole-model convenience
# --------------------------------------------------------------------------
def map_model(model_json, modelseed_dir=None, device="auto", weights_dir=None,
              top_k=100, network=True):
    """Map every metabolite and reaction of a COBRA-style model dict to ModelSEED.

    model_json: dict with 'metabolites' [{id,name,...}] and
                'reactions' [{id,name,metabolites:{met_id:coef}}].
    Returns {'compounds': {local_id: [(cpd_id, score, signals)...]},
             'reactions': {local_id: [(rxn_id, score, signals)...]}}.
    """
    if isinstance(model_json, (str, Path)):
        model_json = json.loads(Path(model_json).read_text())
    enc = _SapBERT(device, weights_dir)
    cmap = CompoundMapper(load_compounds(modelseed_dir), enc).build()
    rmap = ReactionMapper(load_reactions(modelseed_dir), enc).build()
    cmap._cooc = rmap.cooccurrence()

    mets = model_json["metabolites"]
    local_names = {m["id"]: (m.get("name") or "").strip() for m in mets}
    # neighbour sets from reactions
    neigh = defaultdict(set)
    for r in model_json["reactions"]:
        members = list(r.get("metabolites", {}))
        for a in members:
            for b in members:
                if a != b:
                    neigh[a].add(b)
    comp_ranked = cmap.map_model_compounds(local_names, neigh, top_k=top_k, network=network)
    local_top1 = {lid: (r[0][0] if r else None) for lid, r in comp_ranked.items()}

    rxn_names = [(r.get("name") or "").strip() for r in model_json["reactions"]]
    rxn_sets = [{local_top1[m] for m in r.get("metabolites", {}) if local_top1.get(m)}
                for r in model_json["reactions"]]
    rxn_ranked_list = rmap.map_many(rxn_names, rxn_sets, top_k=top_k)
    rxn_ranked = {r["id"]: ranked for r, ranked in zip(model_json["reactions"], rxn_ranked_list)}

    return {"compounds": comp_ranked, "reactions": rxn_ranked}


# --------------------------------------------------------------------------
# Rich SQLite export (shareable, self-contained)
# --------------------------------------------------------------------------
MODELMAP_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS run_metadata (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS performance (
  phase            TEXT PRIMARY KEY,
  n_queries        INTEGER,
  wall_seconds     REAL,
  queries_per_sec  REAL,
  ms_per_query     REAL,
  peak_rss_mb      REAL,
  peak_gpu_mb      REAL,
  notes            TEXT
);

CREATE TABLE IF NOT EXISTS compound_targets (
  cpd_id    TEXT PRIMARY KEY,
  name      TEXT, formula TEXT, charge INTEGER, mass REAL,
  inchikey  TEXT, is_core INTEGER, source_db TEXT DEFAULT 'ModelSEED'
);
CREATE TABLE IF NOT EXISTS compound_queries (
  local_id    TEXT PRIMARY KEY,
  name        TEXT, compartment TEXT, gold_ids TEXT,
  n_candidates INTEGER, top1_id TEXT, top1_score REAL,
  top1_correct INTEGER, top1_chem_correct INTEGER
);
CREATE TABLE IF NOT EXISTS compound_predictions (
  local_id          TEXT NOT NULL,
  rank              INTEGER NOT NULL,
  modelseed_cpd_id  TEXT NOT NULL,
  score             REAL,
  emb_sim           REAL,
  exact_match       INTEGER,
  network_score     REAL,
  is_gold           INTEGER,
  PRIMARY KEY (local_id, rank),
  FOREIGN KEY (local_id) REFERENCES compound_queries(local_id),
  FOREIGN KEY (modelseed_cpd_id) REFERENCES compound_targets(cpd_id)
);

CREATE TABLE IF NOT EXISTS reaction_targets (
  rxn_id    TEXT PRIMARY KEY,
  name      TEXT, ec TEXT, equation TEXT, definition TEXT,
  pathways  TEXT, status TEXT, is_obsolete INTEGER, source_db TEXT DEFAULT 'ModelSEED'
);
CREATE TABLE IF NOT EXISTS reaction_queries (
  local_id     TEXT PRIMARY KEY,
  name         TEXT, gold_id TEXT, n_metabolites INTEGER, is_exchange INTEGER,
  n_candidates INTEGER, top1_id TEXT, top1_score REAL,
  top1_correct INTEGER, top1_equiv INTEGER
);
CREATE TABLE IF NOT EXISTS reaction_predictions (
  local_id          TEXT NOT NULL,
  rank              INTEGER NOT NULL,
  modelseed_rxn_id  TEXT NOT NULL,
  score             REAL,
  name_sim          REAL,
  set_jaccard       REAL,
  exact_set         INTEGER,
  is_gold           INTEGER,
  PRIMARY KEY (local_id, rank),
  FOREIGN KEY (local_id) REFERENCES reaction_queries(local_id),
  FOREIGN KEY (modelseed_rxn_id) REFERENCES reaction_targets(rxn_id)
);

CREATE INDEX IF NOT EXISTS idx_cpred_local ON compound_predictions(local_id);
CREATE INDEX IF NOT EXISTS idx_cpred_cpd   ON compound_predictions(modelseed_cpd_id);
CREATE INDEX IF NOT EXISTS idx_rpred_local ON reaction_predictions(local_id);
CREATE INDEX IF NOT EXISTS idx_rpred_rxn   ON reaction_predictions(modelseed_rxn_id);

CREATE VIEW IF NOT EXISTS compound_top_n AS
SELECT q.local_id, q.name AS query_name, q.compartment, q.gold_ids,
       p.rank, p.modelseed_cpd_id, p.score, p.emb_sim, p.exact_match,
       p.network_score, p.is_gold,
       t.name AS cpd_name, t.formula, t.charge, t.inchikey, t.is_core
FROM compound_queries q
JOIN compound_predictions p ON q.local_id = p.local_id
JOIN compound_targets t ON p.modelseed_cpd_id = t.cpd_id
ORDER BY q.local_id, p.rank;

CREATE VIEW IF NOT EXISTS reaction_top_n AS
SELECT q.local_id, q.name AS query_name, q.gold_id, q.n_metabolites, q.is_exchange,
       p.rank, p.modelseed_rxn_id, p.score, p.name_sim, p.set_jaccard,
       p.exact_set, p.is_gold,
       t.name AS rxn_name, t.ec, t.equation, t.pathways, t.status
FROM reaction_queries q
JOIN reaction_predictions p ON q.local_id = p.local_id
JOIN reaction_targets t ON p.modelseed_rxn_id = t.rxn_id
ORDER BY q.local_id, p.rank;
"""


def write_sqlite(path, payload: dict) -> str:
    """Serialize a model→ModelSEED mapping payload to a rich, self-contained SQLite DB.

    payload keys (all optional except compounds/reactions):
      run_metadata        : {key: value} dict (versions, device, model id, counts, runtime)
      performance         : list of per-phase dicts (phase, n_queries, wall_seconds,
                            queries_per_sec, ms_per_query, peak_rss_mb, peak_gpu_mb, notes)
      compound_targets    : {cpd_id: {name, formula, charge, mass, inchikey, is_core}}
      reaction_targets    : {rxn_id: {name, ec, equation, definition, pathways, status, is_obsolete}}
      compounds           : list of {local_id, name, compartment, gold_ids[list], top1_correct,
                            top1_chem_correct, predictions:[{rank,id,score,emb,exact,net,is_gold}]}
      reactions           : list of {local_id, name, gold_id, n_metabolites, is_exchange,
                            top1_correct, top1_equiv, predictions:[{rank,id,score,name,set_jac,exact_set,is_gold}]}
    Returns the path written.
    """
    import sqlite3
    path = str(path)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(MODELMAP_SQLITE_SCHEMA)
        rm = payload.get("run_metadata") or {}
        conn.executemany("INSERT OR REPLACE INTO run_metadata VALUES (?,?)",
                         [(str(k), str(v)) for k, v in rm.items()])
        perf = payload.get("performance") or []
        conn.executemany(
            "INSERT OR REPLACE INTO performance VALUES (?,?,?,?,?,?,?,?)",
            [(p.get("phase"), p.get("n_queries"), p.get("wall_seconds"),
              p.get("queries_per_sec"), p.get("ms_per_query"), p.get("peak_rss_mb"),
              p.get("peak_gpu_mb"), p.get("notes")) for p in perf])
        ct = payload.get("compound_targets") or {}
        conn.executemany(
            "INSERT OR REPLACE INTO compound_targets VALUES (?,?,?,?,?,?,?,?)",
            [(c, m.get("name"), m.get("formula"), m.get("charge"), m.get("mass"),
              m.get("inchikey"), int(bool(m.get("is_core"))), "ModelSEED") for c, m in ct.items()])
        rt = payload.get("reaction_targets") or {}
        conn.executemany(
            "INSERT OR REPLACE INTO reaction_targets VALUES (?,?,?,?,?,?,?,?,?)",
            [(r, m.get("name"), m.get("ec"), m.get("equation"), m.get("definition"),
              m.get("pathways"), m.get("status"), int(bool(m.get("is_obsolete"))), "ModelSEED")
             for r, m in rt.items()])
        for q in payload.get("compounds") or []:
            preds = q.get("predictions") or []
            top1 = preds[0] if preds else {}
            conn.execute(
                "INSERT OR REPLACE INTO compound_queries VALUES (?,?,?,?,?,?,?,?,?)",
                (q["local_id"], q.get("name"), q.get("compartment"),
                 ";".join(q.get("gold_ids") or []) or None, len(preds),
                 top1.get("id"), top1.get("score"),
                 int(bool(q.get("top1_correct"))), int(bool(q.get("top1_chem_correct")))))
            conn.executemany(
                "INSERT OR REPLACE INTO compound_predictions VALUES (?,?,?,?,?,?,?,?)",
                [(q["local_id"], p["rank"], p["id"], p.get("score"), p.get("emb"),
                  int(bool(p.get("exact"))), p.get("net"), int(bool(p.get("is_gold")))) for p in preds])
        for q in payload.get("reactions") or []:
            preds = q.get("predictions") or []
            top1 = preds[0] if preds else {}
            conn.execute(
                "INSERT OR REPLACE INTO reaction_queries VALUES (?,?,?,?,?,?,?,?,?,?)",
                (q["local_id"], q.get("name"), q.get("gold_id"), q.get("n_metabolites"),
                 int(bool(q.get("is_exchange"))), len(preds), top1.get("id"), top1.get("score"),
                 int(bool(q.get("top1_correct"))), int(bool(q.get("top1_equiv")))))
            conn.executemany(
                "INSERT OR REPLACE INTO reaction_predictions VALUES (?,?,?,?,?,?,?,?)",
                [(q["local_id"], p["rank"], p["id"], p.get("score"), p.get("name"),
                  p.get("set_jac"), int(bool(p.get("exact_set"))), int(bool(p.get("is_gold")))) for p in preds])
        conn.commit()
    finally:
        conn.close()
    return path


def _cpd_target_meta(c: CompoundRec) -> dict:
    return {"name": c.name, "formula": c.formula, "charge": c.charge,
            "mass": None, "inchikey": c.inchikey, "is_core": c.is_core}


def _rxn_target_meta(r: ReactionRec) -> dict:
    return {"name": r.name, "ec": ";".join(r.ec) or None,
            "equation": None, "definition": None,
            "pathways": ";".join(r.pathways) or None, "status": r.status,
            "is_obsolete": r.is_obsolete}


def map_model_to_sqlite(model_json, modelseed_dir=None, path="model_mapping.sqlite", *, device="auto",
                        weights_dir=None, top_k=100, network=True,
                        run_metadata=None):
    """Map a whole model and write a rich, self-contained SQLite DB in one call.

    Convenience wrapper: runs `map_model` then serializes via `write_sqlite`,
    denormalizing ModelSEED target metadata so the DB needs no external files
    to consume. (No gold / performance columns — for a benchmarked, gold-scored
    DB drive `write_sqlite` directly; see the research workspace step 49.)
    """
    if isinstance(model_json, (str, Path)):
        model_json = json.loads(Path(model_json).read_text())
    compounds = load_compounds(modelseed_dir)
    reactions = load_reactions(modelseed_dir)
    out = map_model(model_json, modelseed_dir, device=device, weights_dir=weights_dir,
                    top_k=top_k, network=network)
    met_meta = {m["id"]: m for m in model_json["metabolites"]}
    ct, rt = {}, {}
    comp_rows, rxn_rows = [], []
    for lid, ranked in out["compounds"].items():
        preds = []
        for i, (cid, score, sig) in enumerate(ranked, start=1):
            preds.append({"rank": i, "id": cid, "score": score,
                          "emb": sig.get("emb"), "exact": sig.get("exact"),
                          "net": sig.get("net"), "is_gold": False})
            if cid in compounds and cid not in ct:
                ct[cid] = _cpd_target_meta(compounds[cid])
        m = met_meta.get(lid, {})
        comp_rows.append({"local_id": lid, "name": (m.get("name") or "").strip(),
                          "compartment": m.get("compartment"), "gold_ids": [],
                          "predictions": preds})
    for lid, ranked in out["reactions"].items():
        preds = []
        for i, (rid, score, sig) in enumerate(ranked, start=1):
            preds.append({"rank": i, "id": rid, "score": score,
                          "name": sig.get("name"), "set_jac": sig.get("set_jac"),
                          "exact_set": sig.get("exact_set"), "is_gold": False})
            if rid in reactions and rid not in rt:
                rt[rid] = _rxn_target_meta(reactions[rid])
        rxn_rows.append({"local_id": lid, "predictions": preds})
    payload = {"run_metadata": run_metadata or {}, "compound_targets": ct,
               "reaction_targets": rt, "compounds": comp_rows, "reactions": rxn_rows}
    return write_sqlite(path, payload)
