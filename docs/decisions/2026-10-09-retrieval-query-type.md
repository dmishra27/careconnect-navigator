# Default retrieval query type: ANN

- Date: 2026-10-09
- Status: revised 10 October: AUTO replaces ANN as the default (see update)

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

## Update, 10 October: exact-term questions

The first caveat was tested by adding 15 questions that use the documents' own terms
(`kind: exact`: CHI, HC2, phone numbers, clinic names, a postcode, a bus route). Same
index, k=10 (MLflow runs `index-*`, metrics `exact_*` and `paraphrase_*`):

| Query type | Exact R@1 | Exact R@5 | Exact MRR | Paraphrase R@1 | Paraphrase MRR | All 61 MRR |
|------------|-----------|-----------|-----------|----------------|----------------|------------|
| ANN        | 0.533     | 0.733     | 0.632     | 0.783          | 0.828          | 0.780      |
| HYBRID     | 0.600     | 0.933     | 0.713     | 0.609          | 0.688          | 0.694      |
| FULL_TEXT  | 0.667     | 0.867     | 0.758     | 0.326          | 0.438          | 0.517      |

ANN misses 4 of 15 exact-term questions in the top 5; HYBRID misses 1. ANN still ranks
best on everyday wording and across all 61 questions. Each method wins on its own kind of
question, so an `AUTO` query type was added: HYBRID when the question contains digits,
an acronym other than NHS/GP/A&E, or a capitalised name mid-sentence; ANN otherwise. It
routes 13 of 15 exact-term and 6 of 46 paraphrased questions to HYBRID.

| Query type | All R@1 | All R@5 | All R@10 | All MRR | Exact R@5 | Paraphrase R@1 | Paraphrase MRR |
|------------|---------|---------|----------|---------|-----------|----------------|----------------|
| ANN        | 0.721   | 0.852   | 0.918    | 0.780   | 0.733     | 0.783          | 0.828          |
| HYBRID     | 0.607   | 0.852   | 0.869    | 0.694   | 0.933     | 0.609          | 0.688          |
| **AUTO**   | 0.705   | **0.902** | **0.934** | **0.781** | **0.933** | 0.739        | 0.803          |

In question counts (61): AUTO puts the right passage in the top 5 for 55 questions, ANN
and HYBRID for 52 each. AUTO matches HYBRID on every exact-term question (14 of 15 in the
top 5) and ANN on everyday questions in the top 5 (41 of 46), but puts the right passage
first for 2 fewer everyday questions than ANN (34 vs 36): those are among the 6 everyday
questions that mention a place or a named term and so go to HYBRID.

## Decision (revised 10 October)

Default `search_query_type` is `AUTO`. The agent will read the top 5 passages, and AUTO
finds the answer there for 3 more questions than either fixed method, with overall
ranking (MRR) level with ANN. ANN, HYBRID and FULL_TEXT stay available.

Caveats: the routing rules were written after seeing these 61 questions, so the gain may
be partly fitted to them; re-test on new questions written in Week 3 before trusting it.
15 exact-term questions is a small set (one question moves exact recall by about 7
points).

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
