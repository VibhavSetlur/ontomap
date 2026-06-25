"""Context expansion: render an "expanded paragraph" per term in each ontology.

Two facet levels exposed:
- "bare": just the primary label (the control)
- "expanded": label + EC numbers + key biological facets (no AI inflation; deterministic)

The expanded text for a reaction draws on the ModelSEED reaction record
(equation in named compounds, EC list, pathway aliases).

The expanded text for an SSO role draws on the role name and parsed EC.
Crucially we do NOT pull SSO_reactions.json into the role expansion — that file
is the eval gold and would cause leakage.
"""

from __future__ import annotations

from . import data


# ---------- ModelSEED reactions ----------

DEFAULT_RXN_FACETS = frozenset({"name", "synonyms", "equation", "ec", "pathway", "aliases"})


def expand_reaction(
    rxn_row: dict,
    ec_list: list[str] | None,
    pathways: list[str] | None,
    aliases: dict[str, list[str]] | None,
    alt_names: list[str] | None,
    level: str = "expanded",
    facets: frozenset[str] | None = None,
) -> str:
    """Render a reaction's text expansion.

    level: 'bare' = name only, ignores facets. 'expanded' uses `facets` (defaults
    to DEFAULT_RXN_FACETS).
    """
    name = (rxn_row.get("name") or "").strip()
    if level == "bare":
        return name or rxn_row["id"]

    if facets is None:
        facets = DEFAULT_RXN_FACETS

    lines = []
    if "name" in facets:
        lines.append(f"Name: {name or rxn_row['id']}")

    if "synonyms" in facets and alt_names:
        unique_alts = [n for n in alt_names if n and n.lower() != name.lower()]
        if unique_alts:
            lines.append("Synonyms: " + "; ".join(unique_alts[:8]))

    if "equation" in facets:
        definition = (rxn_row.get("definition") or "").strip()
        if definition and definition not in {"null", "None"}:
            lines.append(f"Equation: {definition}")

    if "ec" in facets:
        inline_ecs = data.parse_ec_from_text(rxn_row.get("ec_numbers") or "")
        all_ecs = list(dict.fromkeys((ec_list or []) + inline_ecs))
        if all_ecs:
            lines.append("EC: " + ", ".join(all_ecs))

    if "pathway" in facets and pathways:
        unique_pw = list(dict.fromkeys(pathways))
        lines.append("Pathway: " + "; ".join(unique_pw[:10]))

    if "aliases" in facets and aliases:
        kegg = aliases.get("KEGG") or []
        if kegg:
            lines.append("KEGG reactions: " + ", ".join(kegg[:6]))
        metacyc = aliases.get("MetaCyc") or []
        if metacyc:
            lines.append("MetaCyc: " + ", ".join(metacyc[:6]))

    return "\n".join(lines) if lines else (name or rxn_row['id'])


# ---------- SSO functional roles ----------

def expand_sso_role(role_id: str, name: str, level: str = "expanded") -> str:
    name = (name or "").strip()
    if level == "bare":
        return name or role_id

    lines = [f"Name: {name or role_id}"]

    ecs = data.parse_ec_from_text(name)
    if ecs:
        lines.append("EC: " + ", ".join(ecs))

    if " / " in name:
        parts = [p.strip() for p in name.split(" / ") if p.strip()]
        if len(parts) > 1:
            lines.append("Component activities: " + "; ".join(parts))

    if " @ " in name:
        parts = [p.strip() for p in name.split(" @ ") if p.strip()]
        if len(parts) > 1:
            lines.append("Moonlighting roles: " + "; ".join(parts))

    return "\n".join(lines)


# ---------- bulk builders ----------

def build_all_reaction_expansions(
    level: str = "expanded",
    facets: frozenset[str] | None = None,
) -> dict[str, str]:
    """Return {rxn_id: expanded_text} for every non-obsolete reaction."""
    reactions = data.load_modelseed_reactions()
    ecs = data.load_modelseed_reaction_ecs()
    pathways = data.load_modelseed_reaction_pathways()
    aliases = data.load_modelseed_reaction_aliases()
    alt_names = data.load_modelseed_reaction_names()

    out: dict[str, str] = {}
    for rxn_id, row in reactions.items():
        if row.get("is_obsolete") in ("1", "true", "True"):
            continue
        out[rxn_id] = expand_reaction(
            row,
            ecs.get(rxn_id),
            pathways.get(rxn_id),
            aliases.get(rxn_id),
            alt_names.get(rxn_id),
            level=level,
            facets=facets,
        )
    return out


def build_sso_expansions(level: str = "expanded", subset_ids: list[str] | None = None) -> dict[str, str]:
    """Return {sso_id: expanded_text}. If subset_ids given, only those terms."""
    sso = data.load_sso_dictionary()
    ids = subset_ids if subset_ids else list(sso.keys())
    out: dict[str, str] = {}
    for sid in ids:
        term = sso.get(sid)
        if not term:
            continue
        out[sid] = expand_sso_role(sid, term.get("name", ""), level=level)
    return out
