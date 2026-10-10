# FairTrial Track 1 — Pipeline A vs B

> [!WARNING]
> - 50 of 50 documents are **synthetic placeholders**. Replace data/docs/ with the real corpus before reporting anything.

## Run configuration

| Field | Value |
| --- | --- |
| run_name | track1_baseline |
| timestamp | 2026-10-09T18:56:39+00:00 |
| embedder | bge-m3:BAAI/bge-m3 |
| device | mps (arm64) |
| translator | marian:id=Helsinki-NLP/opus-mt-id-en,tr=Helsinki-NLP/opus-mt-tr-en |
| n_docs | 50 |
| n_chunks | 128 |
| n_queries | 30 |
| languages | id, tr |
| chunk_max_chars | 400 |
| bootstrap_samples | 10000 |

## Results

Delta is B − A (translate-first minus multilingual-first). CI is a 95% percentile interval from a paired bootstrap over queries.

| Metric | A (multilingual) | B (translate-first) | Δ (B−A) | 95% CI | p | B wins / A wins / ties | n |
| --- | --- | --- | --- | --- | --- | --- | --- |
| hit@1 | 0.8667 | 0.8000 | -0.0667 | [-0.233, 0.100] | 0.536 | 2 / 4 / 24 | 30 |
| recall_doc@1 | 0.4036 | 0.3397 | -0.0639 | [-0.161, 0.014] | 0.127 | 2 / 4 / 24 | 30 |
| mrr@1 | 0.8667 | 0.8000 | -0.0667 | [-0.233, 0.100] | 0.536 | 2 / 4 / 24 | 30 |
| evidence_recall@1 | 0.3286 | 0.3092 | -0.0194 | [-0.086, 0.033] | 0.587 | 2 / 2 / 26 | 30 |
| hit@3 | 0.9333 | 0.9667 | 0.0333 | [0.000, 0.100] | 0.723 | 1 / 0 / 29 | 30 |
| recall_doc@3 | 0.6847 | 0.6458 | -0.0389 | [-0.115, 0.039] | 0.323 | 3 / 6 / 21 | 30 |
| mrr@3 | 0.8944 | 0.8667 | -0.0278 | [-0.133, 0.083] | 0.622 | 2 / 5 / 23 | 30 |
| evidence_recall@3 | 0.5764 | 0.5569 | -0.0194 | [-0.109, 0.069] | 0.662 | 4 / 5 / 21 | 30 |
| hit@5 | 0.9667 | 0.9667 | 0.0000 | [0.000, 0.000] | 1.000 | 0 / 0 / 30 | 30 |
| recall_doc@5 | 0.7803 | 0.7497 | -0.0306 | [-0.092, 0.028] | 0.346 | 3 / 5 / 22 | 30 |
| mrr@5 | 0.9028 | 0.8667 | -0.0361 | [-0.139, 0.067] | 0.491 | 2 / 5 / 23 | 30 |
| evidence_recall@5 | 0.7303 | 0.6997 | -0.0306 | [-0.092, 0.028] | 0.346 | 3 / 5 / 22 | 30 |
| hit@10 | 0.9667 | 1.0000 | 0.0333 | [0.000, 0.100] | 0.734 | 1 / 0 / 29 | 30 |
| recall_doc@10 | 0.8725 | 0.8522 | -0.0203 | [-0.088, 0.043] | 0.547 | 4 / 5 / 21 | 30 |
| mrr@10 | 0.9028 | 0.8722 | -0.0306 | [-0.133, 0.072] | 0.554 | 3 / 5 / 22 | 30 |
| evidence_recall@10 | 0.8419 | 0.7856 | -0.0564 | [-0.128, 0.000] | 0.052 | 2 / 5 / 23 | 30 |

## Cost & latency

| Stage | Value |
| --- | --- |
| query_encode_seconds | 1.07 |
| A_chunk_chars | 43712 |
| A_encode_seconds | 5.94 |
| A_search_seconds | 0.004 |
| B_chunk_chars | 43997 |
| B_encode_seconds | 5.07 |
| B_search_seconds | 0.017 |
| translation_seconds | 76.48 |
| translation_src_chars | 38140 |

## How to read this

- A CI that straddles 0 means this query set cannot distinguish the two pipelines on that metric. With ~30 queries that is a likely outcome for small true differences; it is a statement about the experiment's power, not evidence of equivalence.
- `evidence_recall@k` is the metric that speaks to the actual research question (can the original evidence paragraph be found), so weight it above `hit@k`.
- Pipeline B's score is bounded by the translator's quality. A loss for B is a loss for *this* translator, not for translate-first in general — rerun with a stronger MT before concluding otherwise.
- Do **not** compare raw cosine scores across pipelines. English-to-English matching inflates similarity, so B's scores run systematically higher than A's at equal ranking quality. Only ranks and the metrics above are comparable, and a score threshold tuned on one pipeline does not transfer to the other.
