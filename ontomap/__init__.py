"""ontomap — frozen pipeline-3 SSO/KO → ModelSEED reaction mapping.

Frozen pipeline:
    SapBERT-LoRA → multi-axis FAISS top-100 → MedCPT fused rerank → top-10

Direction-specific MedCPT fusion weights: σ_SSO = 0.3, σ_KO = 0.7.

Three input modes:
  1. SSO/KO id            — looked up in the bundled SSO/KO dictionary
  2. free-text description — bypasses the dictionary; EC numbers in the
     text are auto-extracted into the EC axis (production workflow for
     annotation dumps from RAST / BAKTA / dram / glm4ec / prokka / …)
  3. multi-source TSV aggregation — `ontomap aggregate-tsv` dedups a
     14-source-per-gene RAST-vault-style dump into a clean
     description-per-row file ready for the pipeline.

Public API:
    from ontomap import Pipeline, MapResult, __version__
    pipe = Pipeline.from_pretrained(direction="sso", device="cuda")
    result = pipe.map_one("SSO:000000027", top_k=10)
    results = pipe.map_descriptions(
        ["Enoyl-CoA hydratase (EC 4.2.1.17)",
         "ABC transporter substrate-binding protein"],
        top_k=10,
    )

CLI:
    ontomap map --sso SSO:000000027
    ontomap map --text "Enoyl-CoA hydratase (EC 4.2.1.17)" --top-k 10
    ontomap map --input ids.csv --output results.sssom.tsv
    ontomap map --text-input descriptions.tsv --output predictions.json
    ontomap aggregate-tsv -i raw_dump.tsv -o clean_descriptions.tsv \\
                          --provenance clean_descriptions.provenance.jsonl
    ontomap bench --tiers 10,100,1000

v1.5.0 — Compound & Reaction mapping for whole models (NEW, additive):
    Map the metabolites and reactions of an existing foreign-namespace
    metabolic model onto ModelSEED ids.

        from ontomap import CompoundMapper, ReactionMapper, map_model
        out = map_model(model_json, modelseed_dir="data/raw/modelseed")
        out["compounds"]["CPD_DASH_205_Cytosol"]   # ranked cpd ids
        out["reactions"]["rxn12357_c0"]            # ranked rxn ids

    See ontomap/docs/COMPOUND_REACTION_MAPPING.md for the validation
    study (held-out gold on a published A. baylyi/ADP1 model), data
    limitations, results, and figures.
"""

__version__ = "1.6.1"

from ontomap.pipeline import Pipeline, MapResult, PipelineConfig  # noqa: F401, E402
from ontomap.aggregate import aggregate_annotation_tsv  # noqa: F401, E402
from ontomap.io import write_sqlite, write_annotated_sqlite  # noqa: F401, E402
from ontomap.confidence_v2 import (  # noqa: F401, E402
    recalibrate_one,
    recalibrate_predictions,
    confidence_to_predicate_v2,
)
# v1.5.0 — compound & reaction mapping for whole metabolic models
# (added alongside the reaction Pipeline; see docs/COMPOUND_REACTION_MAPPING.md).
from ontomap.modelmap import (  # noqa: F401, E402
    CompoundMapper,
    ReactionMapper,
    map_model,
    map_model_to_sqlite,
    write_sqlite as write_model_sqlite,
)

__all__ = [
    "Pipeline", "MapResult", "PipelineConfig",
    "aggregate_annotation_tsv",
    "write_sqlite", "write_annotated_sqlite",
    "recalibrate_one", "recalibrate_predictions", "confidence_to_predicate_v2",
    "CompoundMapper", "ReactionMapper", "map_model",
    "map_model_to_sqlite", "write_model_sqlite",
    "__version__",
]
