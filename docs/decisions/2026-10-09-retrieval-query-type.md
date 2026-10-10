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
- Re-run on 10 October after removing contents-page chunks (357 to 353 chunks): ANN
  unchanged (R@1 0.783, R@5 0.891, R@10 0.957, MRR 0.828); HYBRID MRR 0.688; FULL_TEXT
  MRR 0.438. The decision stands.

---

# Chunking: keep 400 tokens with 60 overlap

- Date: 2026-10-09
- Status: accepted

## Evidence

Same 46 questions, chunk sets rebuilt from the landing Volume per config and ranked by
cosine similarity with one local embedding model (`BAAI/bge-base-en-v1.5`), because
Free Edition throttles direct calls to `databricks-gte-large-en`
(MLflow runs `chunks-*`):

| Max/overlap | Chunks | R@1   | R@5   | R@10  | MRR   | Doc R@5 | Tokens in top 5 |
|-------------|--------|-------|-------|-------|-------|---------|-----------------|
| 200/40      | 561    | 0.630 | 0.848 | 0.913 | 0.722 | 0.935   | 604             |
| **400/60**  | 355    | 0.717 | 0.891 | 0.935 | 0.787 | 0.957   | 909             |
| 800/120     | 277    | 0.717 | 0.891 | 0.935 | 0.788 | 0.935   | 1,286           |

## Decision

Keep 400/60. Going to 800/120 gains nothing on recall or MRR but sends about 40% more
text to the LLM for every answer. 200/40 is cheaper but loses the top result for four
more questions.

## Notes

- Median chunk size is not a useful comparison here: leaflet sections are short whatever
  the budget, so the size distribution has two groups and the median moves between them.
- The local model scores slightly below the index model on the same chunks
  (MRR 0.787 vs 0.828 for ANN), which is expected. The comparison between configs uses
  one model throughout, so it is fair.
