# FairTrial Track 1 — Pipeline A vs B

> [!WARNING]
> - 6 of 6 documents are **synthetic placeholders**. Replace data/docs/ with the real corpus before reporting anything.
> - Corpus has 6 documents; the design calls for 50.
> - Query set has 6 annotated queries; the design calls for 30.

## Run configuration

| Field | Value |
| --- | --- |
| run_name | _demo_synthetic |
| timestamp | 2026-10-09T18:24:08+00:00 |
| embedder | bge-m3:BAAI/bge-m3 |
| device | mps (arm64) |
| translator | marian:id=Helsinki-NLP/opus-mt-id-en,tr=Helsinki-NLP/opus-mt-tr-en |
| n_docs | 6 |
| n_chunks | 6 |
| n_queries | 6 |
| languages | id, tr |
| chunk_max_chars | 900 |
| bootstrap_samples | 10000 |

## Results

Delta is B − A (translate-first minus multilingual-first). CI is a 95% percentile interval from a paired bootstrap over queries.

| Metric | A (multilingual) | B (translate-first) | Δ (B−A) | 95% CI | p | B wins / A wins / ties | n |
| --- | --- | --- | --- | --- | --- | --- | --- |
| hit@1 | 0.8333 | 0.8333 | 0.0000 | [0.000, 0.000] | 1.000 | 0 / 0 / 6 | 6 |
| recall_doc@1 | 0.6667 | 0.6667 | 0.0000 | [0.000, 0.000] | 1.000 | 0 / 0 / 6 | 6 |
| mrr@1 | 0.8333 | 0.8333 | 0.0000 | [0.000, 0.000] | 1.000 | 0 / 0 / 6 | 6 |
| evidence_recall@1 | 0.6944 | 0.6944 | 0.0000 | [0.000, 0.000] | 1.000 | 0 / 0 / 6 | 6 |
| hit@3 | 1.0000 | 1.0000 | 0.0000 | [0.000, 0.000] | 1.000 | 0 / 0 / 6 | 6 |
| recall_doc@3 | 1.0000 | 1.0000 | 0.0000 | [0.000, 0.000] | 1.000 | 0 / 0 / 6 | 6 |
| mrr@3 | 0.8889 | 0.8889 | 0.0000 | [0.000, 0.000] | 1.000 | 0 / 0 / 6 | 6 |
| evidence_recall@3 | 1.0000 | 1.0000 | 0.0000 | [0.000, 0.000] | 1.000 | 0 / 0 / 6 | 6 |
| hit@5 | 1.0000 | 1.0000 | 0.0000 | [0.000, 0.000] | 1.000 | 0 / 0 / 6 | 6 |
| recall_doc@5 | 1.0000 | 1.0000 | 0.0000 | [0.000, 0.000] | 1.000 | 0 / 0 / 6 | 6 |
| mrr@5 | 0.8889 | 0.8889 | 0.0000 | [0.000, 0.000] | 1.000 | 0 / 0 / 6 | 6 |
| evidence_recall@5 | 1.0000 | 1.0000 | 0.0000 | [0.000, 0.000] | 1.000 | 0 / 0 / 6 | 6 |
| hit@10 | 1.0000 | 1.0000 | 0.0000 | [0.000, 0.000] | 1.000 | 0 / 0 / 6 | 6 |
| recall_doc@10 | 1.0000 | 1.0000 | 0.0000 | [0.000, 0.000] | 1.000 | 0 / 0 / 6 | 6 |
| mrr@10 | 0.8889 | 0.8889 | 0.0000 | [0.000, 0.000] | 1.000 | 0 / 0 / 6 | 6 |
| evidence_recall@10 | 1.0000 | 1.0000 | 0.0000 | [0.000, 0.000] | 1.000 | 0 / 0 / 6 | 6 |

## Cost & latency

| Stage | Value |
| --- | --- |
| query_encode_seconds | 2.94 |
| A_chunk_chars | 4989 |
| A_encode_seconds | 1.61 |
| A_search_seconds | 0.002 |
| B_chunk_chars | 4911 |
| B_encode_seconds | 0.76 |
| B_search_seconds | 0.001 |
| translation_seconds | 58.81 |
| translation_src_chars | 4579 |

## How to read this

- A CI that straddles 0 means this query set cannot distinguish the two pipelines on that metric. With ~30 queries that is a likely outcome for small true differences; it is a statement about the experiment's power, not evidence of equivalence.
- `evidence_recall@k` is the metric that speaks to the actual research question (can the original evidence paragraph be found), so weight it above `hit@k`.
- Pipeline B's score is bounded by the translator's quality. A loss for B is a loss for *this* translator, not for translate-first in general — rerun with a stronger MT before concluding otherwise.
