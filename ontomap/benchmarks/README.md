# Filipe GO benchmark harness

`filipe-go-v1.metrics.json` is the accepted public-safe metric record, schema version 1.
The full benchmark requires excluded source data and is deliberately not part of runtime.
It records 130,061 entities, a 104,032/26,029 train/test split, 4,588 candidates, no entity overlap,
top-1/5/20/100 of .7989/.9218/.9502/.9705, MRR .8570, and coverage .9856. Scores are not calibrated probabilities.
