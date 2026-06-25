"""BAKTA → ModelSEED reaction mapping.

Bakta emits a JSON file with annotation per CDS. Each CDS carries:
- `product` (free text, often UniRef-derived)
- structured dbxrefs: EC, KO (KOfam), Pfam, COG, RefSeq, UniRef
- per-source inference scores

Our mapping strategy is **anchor-first, then embedding-fallback**:

  1. If CDS has KO dbxref → use the curated KO ↔ ModelSEED rxn map
     (kegg_95_0_ko_seed.tsv).
  2. Elif CDS has EC dbxref → use ModelSEED EC alias table
     (Unique_ModelSEED_Reaction_ECs.txt).
  3. Else → embed the product text and retrieve top-k from the SSO dictionary,
     then resolve SSO → rxn via SSO_reactions.json.

This biases for high precision when dbxrefs exist (most CDS) and gracefully
degrades for the long-tail free-text products.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from . import data


# ----- Bakta JSON parsing -----

def parse_bakta_json(path: Path) -> list[dict]:
    """Parse a Bakta JSON output and return a list of CDS dicts.

    Output per CDS:
        {
          id: locus_tag or contig:start..stop,
          product: free-text product,
          ec: [EC numbers],
          ko: [KO ids without 'ko:' prefix],
          pfam: [Pfam ids],
          cog: [COG ids],
          ... other dbxref lists as found ...
        }
    """
    with Path(path).open() as f:
        bakta = json.load(f)
    features = bakta.get("features", [])
    cds_features = [f for f in features if f.get("type") == "cds"]
    out = []
    for f in cds_features:
        cds = {
            "id": f.get("locus") or f.get("id") or f"{f.get('contig')}:{f.get('start')}-{f.get('stop')}",
            "product": (f.get("product") or "").strip(),
            "ec": [], "ko": [], "pfam": [], "cog": [], "refseq": [],
            "uniref100": [], "uniparc": [],
        }
        dbxrefs = f.get("db_xrefs") or []
        for x in dbxrefs:
            if x.startswith("EC:"):
                cds["ec"].append(x[3:])
            elif x.startswith("KEGG:"):
                cds["ko"].append(x[5:])
            elif x.startswith("KO:"):
                cds["ko"].append(x[3:])
            elif x.startswith("PFAM:") or x.startswith("Pfam:"):
                cds["pfam"].append(x.split(":", 1)[1])
            elif x.startswith("COG:"):
                cds["cog"].append(x[4:])
            elif x.startswith("RefSeq:"):
                cds["refseq"].append(x[7:])
            elif x.startswith("UniRef100_"):
                cds["uniref100"].append(x.replace("UniRef100_", ""))
            elif x.startswith("UPI"):
                cds["uniparc"].append(x)
        out.append(cds)
    return out


# ----- Anchor-first mapping -----

class BaktaMapper:
    """Applies anchor-first + embedding-fallback to map a Bakta CDS to rxn IDs."""

    def __init__(self, embedder=None):
        # Lazy-loaded gold tables for anchor lookups.
        self._ko_to_rxn: dict[str, list[str]] | None = None
        self._ec_to_rxn: dict[str, list[str]] | None = None
        self._sso_to_rxn: dict[str, list[str]] | None = None
        self._sso_name_to_id: dict[str, str] | None = None
        self.embedder = embedder  # callable: (text) -> top-k SSO IDs

    def _ensure_loaded(self):
        if self._ko_to_rxn is None:
            ko_seed = data.load_kegg_ko_seed_gold()
            self._ko_to_rxn = {k: v["seed_ids"] for k, v in ko_seed.items()}
        if self._ec_to_rxn is None:
            # invert rxn -> EC mapping into EC -> [rxn]
            ec_map = data.load_modelseed_reaction_ecs()
            inv: dict[str, list[str]] = defaultdict(list)
            for rxn, ecs in ec_map.items():
                for ec in ecs:
                    inv[ec].append(rxn)
            self._ec_to_rxn = dict(inv)
        if self._sso_to_rxn is None:
            self._sso_to_rxn = data.load_sso_reactions_gold()
            sso_dict = data.load_sso_dictionary()
            self._sso_name_to_id = {(t.get("name") or "").lower(): sid
                                    for sid, t in sso_dict.items() if t.get("name")}

    def map_cds(self, cds: dict) -> dict:
        """Apply anchor-first mapping to a Bakta CDS feature dict.

        Returns:
            {
              cds_id, product, anchor: 'KO'|'EC'|'EMBEDDING'|'NONE',
              rxn_ids: [...], confidence: float, evidence: str
            }
        """
        self._ensure_loaded()

        # 1) KO anchor
        for ko in cds["ko"]:
            ko_id = ko.split(":")[-1].lstrip("K0")
            ko_id = f"K{int(ko_id):05d}" if ko_id.isdigit() else ko
            ko_id = ko if ko.startswith("K") and len(ko) == 6 else ko_id
            rxns = self._ko_to_rxn.get(ko_id)
            if rxns:
                return {
                    "cds_id": cds["id"], "product": cds["product"],
                    "anchor": "KO", "rxn_ids": rxns, "confidence": 1.0,
                    "evidence": f"KO {ko_id} → {len(rxns)} rxn via kegg_95_0_ko_seed.tsv",
                }

        # 2) EC anchor
        for ec in cds["ec"]:
            rxns = self._ec_to_rxn.get(ec)
            if rxns:
                return {
                    "cds_id": cds["id"], "product": cds["product"],
                    "anchor": "EC", "rxn_ids": rxns, "confidence": 0.85,
                    "evidence": f"EC {ec} → {len(rxns)} rxn via ModelSEED EC aliases",
                }

        # 3) Embedding fallback
        if self.embedder is not None and cds["product"]:
            top_sso_ids = self.embedder(cds["product"])
            for sid, score in top_sso_ids:
                rxns = self._sso_to_rxn.get(sid)
                if rxns:
                    return {
                        "cds_id": cds["id"], "product": cds["product"],
                        "anchor": "EMBEDDING", "rxn_ids": rxns,
                        "confidence": float(score),
                        "evidence": f"Embedding match → {sid} (score {score:.3f}) → {len(rxns)} rxn",
                    }

        # 4) No anchor available
        return {
            "cds_id": cds["id"], "product": cds["product"],
            "anchor": "NONE", "rxn_ids": [], "confidence": 0.0,
            "evidence": "no KO/EC dbxref and no embedding match above threshold",
        }
