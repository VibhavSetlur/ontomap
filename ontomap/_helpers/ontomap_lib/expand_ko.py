"""KO-side expansion using the kegg_95_0_ko_seed.tsv definitions (no live KEGG REST).

The TSV's `definition` column already contains the canonical KEGG NAME (with EC
in brackets and ` / ` multifunctionality), so we can use it directly without
hitting the live KEGG REST API. This is intentional: the experiment evaluates
whether expansion *as available* helps, and definition-text + parsed EC is the
useful per-KO context we can derive from the gold TSV alone.
"""

from __future__ import annotations

from . import data


def expand_ko(ko_id: str, definition: str, level: str = "expanded") -> str:
    definition = (definition or "").strip()
    if level == "bare":
        # Strip the EC bracketed part to keep bare close to name-only.
        bare = definition.split(" [EC")[0].strip() or ko_id
        return bare

    lines = [f"Name: {definition or ko_id}"]
    ecs = data.parse_ec_from_text(definition)
    if ecs:
        lines.append("EC: " + ", ".join(ecs))

    base_name = definition.split(" [EC")[0].strip()
    if " / " in base_name:
        parts = [p.strip() for p in base_name.split(" / ") if p.strip()]
        if len(parts) > 1:
            lines.append("Component activities: " + "; ".join(parts))

    return "\n".join(lines)


def build_ko_expansions(level: str = "expanded") -> tuple[dict[str, str], dict[str, list[str]]]:
    """Return ({ko_id: expanded_text}, {ko_id: [gold_rxn_ids]})."""
    gold = data.load_kegg_ko_seed_gold()
    expansions: dict[str, str] = {}
    gold_map: dict[str, list[str]] = {}
    for ko, row in gold.items():
        expansions[ko] = expand_ko(ko, row["definition"], level=level)
        gold_map[ko] = row["seed_ids"]
    return expansions, gold_map
