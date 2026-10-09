# Default retrieval query type: ANN

- Date: 2026-10-09
- Status: accepted (revisit when the question set grows)

## Context

The AI Search index over `silver_chunks` (managed embeddings, `databricks-gte-large-en`)
supports three query types: ANN (vector only), FULL_TEXT (keyword only) and HYBRID
(both, merged with Reciprocal Rank Fusion). The first retriever used HYBRID by default.

## Evidence

Retrieval eval, 46 labelled questions, chunking 400/60, index of 357 chunks, k=10
(MLflow experiment `careconnect-dev`, runs `index-*`):

| Query type | R@1   | R@3   | R@5   | R@10  | MRR   | Doc R@5 |
|------------|-------|-------|-------|-------|-------|---------|
| HYBRID     | 0.587 | 0.783 | 0.826 | 0.848 | 0.682 | 0.913   |
| ANN        | 0.783 | 0.826 | 0.891 | 0.957 | 0.828 | 0.978   |
| FULL_TEXT  | 0.370 | 0.565 | 0.609 | 0.717 | 0.473 | 0.717   |

ANN puts the right chunk first for 9 more questions than HYBRID (36 vs 27 of 46).
Keyword search on its own is weak here, and fusing it in pushes keyword-heavy policy
chunks (long passages that repeat words like "complaint" and "treatment") above the
short leaflet sections that actually answer the question.

## Decision

Default `search_query_type` is `ANN` (in `ProjectConfig`). HYBRID and FULL_TEXT stay
available through the retriever's `query_type` argument and `--type` on the CLI.

## Caveats

- The questions are deliberately paraphrased, which favours semantic search. Real users
  also type exact terms (CHI number, HC2, phone numbers, clinic names) where keyword
  matching helps. Add such questions before revisiting.
- 46 questions is small: one question moves a recall figure by about 2 points.
- A reranker on top of HYBRID was not tested.
