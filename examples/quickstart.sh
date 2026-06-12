#!/usr/bin/env bash
# ontomap — minimal end-to-end demo
# Run from inside the ontomap/ folder after `pip install -e .`
set -e

cd "$(dirname "$0")"/..

echo "▶ Single-query map · SSO (text output to stdout)"
ontomap map --sso SSO:000000027 --top-k 5

echo ""
echo "▶ Single-query map · KO (full top-100 to JSON)"
ontomap map --ko K10046 --output /tmp/ontomap_k10046.json --top-k 100
echo "  → wrote /tmp/ontomap_k10046.json ($(wc -c </tmp/ontomap_k10046.json) bytes)"

echo ""
echo "▶ Batch map from CSV → SSSOM-TSV"
ontomap map --input examples/sample_ids.csv --id-column sso_id --direction sso \
            --output /tmp/ontomap_batch.sssom.tsv
echo "  → wrote /tmp/ontomap_batch.sssom.tsv"
head -5 /tmp/ontomap_batch.sssom.tsv

echo ""
echo "▶ Batch map → SQLite (3-table schema, queryable with sqlite3)"
ontomap map --input examples/sample_ids.csv --id-column sso_id --direction sso \
            --output /tmp/ontomap_batch.sqlite
echo "  → wrote /tmp/ontomap_batch.sqlite"
sqlite3 /tmp/ontomap_batch.sqlite \
  "SELECT query_id, rank, reaction_id, ROUND(fused_score, 3) AS score, predicate
   FROM top_n_with_meta WHERE rank <= 3 ORDER BY query_id, rank LIMIT 12;"

echo ""
echo "▶ Batch map → per-query JSON files in a directory"
rm -rf /tmp/ontomap_batch_dir
ontomap map --input examples/sample_ids.csv --id-column sso_id --direction sso \
            --output /tmp/ontomap_batch_dir
echo "  → wrote /tmp/ontomap_batch_dir/{sso/*.json, manifest.json}"
ls /tmp/ontomap_batch_dir/sso/ | head -5

echo ""
echo "▶ Bundled-weight + cached-embedding verification"
ontomap info --verify-manifest

echo ""
echo "▶ Reproducible scaling benchmark (small tier — to verify the install)"
ontomap bench --tiers 10,100 --direction sso

echo ""
echo "✓ done. See ontomap/README.md for CLI reference and ontomap/docs/ for deeper usage."
