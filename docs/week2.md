# Week 2: Data, ingestion, search and evaluation

CareConnect Navigator, following the Maven "LLMOps with Databricks" schedule on
Databricks Free Edition. Week 2 turns raw documents into a searchable, evaluated
knowledge base (LLMOps track) and starts the waiting-times data pipeline (MLOps track).

## Outcome

| Area | Result |
|------|--------|
| Sources | 21 current and 1 superseded synthetic leaflets, 6 public Scottish Government PDFs |
| Ingest | `bronze_documents` (28 docs), `silver_chunks` (357 chunks, Change Data Feed on), `ops_pii_quarantine` (empty) |
| Search | AI Search endpoint `careconnect-search`, Delta Sync index `silver_chunks_index`, managed embeddings (`databricks-gte-large-en`) |
| Retrieval quality | ANN search: recall@5 0.891, recall@10 0.957, MRR 0.828 on 46 labelled questions |
| PHS waiting times | `silver_phs_ongoing_waits`: 145,789 rows, Oct 2012 to Jun 2026, 0 rejected, all checks logged to `ops_dq_results` |
| Jobs | `ingest_job` (ingest, then index sync) and `phs_job`, both serverless, deployed with the bundle |
| Tests | 79 unit tests, plus 2 integration tests against Databricks |

## Open items from Week 1 (closed)

- Schemas and the landing Volume defined in the bundle (`resources/schemas.yml`).
- Template sample job, code and test removed.
- Lazy Spark fixture and an `integration` marker, so offline tests run without Databricks.
- Decision records for the workspace layout and MLflow trace storage (below).

## LLMOps track

### Ingest (`src/careconnect/ingest/`)

Markdown leaflets (front matter plus headings) and PDFs (pypdf) are parsed into
sections, scanned for personal data, chunked and written to Delta tables.

- **PDF cleaning:** running headers and footers, page numbers and contents-page entries
  are removed; hyphenated line breaks are re-joined; numbered and "Annex"/"Appendix"
  headings are detected, but a "heading" followed by a lowercase line is treated as a
  wrapped sentence.
- **Page numbers:** inline page markers let every PDF chunk record the page it starts
  on, so answers can cite "page 7" instead of page 1 for everything.
- **PII scan:** CHI numbers, National Insurance numbers and labelled personal fields
  quarantine a document; email addresses are recorded only.
- **Chunking:** heading-aware, 400 tokens with 60 overlap, never crossing a section,
  each chunk prefixed with a "Title > Section" line.
- **Incremental:** documents are skipped when their content hash is unchanged;
  `--full-refresh` rewrites everything after a code change.

### Search (`src/careconnect/search/`)

- Delta Sync index on `silver_chunks`, triggered pipeline (refreshed by the job's
  `sync_index` task), managed embeddings on the `text` column.
- Retriever always filters to `status = 'current'`, so superseded leaflets never appear.
- Default query type is ANN (see decisions).

### Retrieval evaluation (`src/careconnect/evals/retrieval.py`)

46 questions in patients' own words (`data/eval/retrieval_questions.yml`), each labelled
with a document and an evidence phrase rather than a chunk id, so the same labels score
any chunking.

| Query type | R@1 | R@5 | R@10 | MRR |
|------------|-----|-----|------|-----|
| ANN | 0.783 | 0.891 | 0.957 | 0.828 |
| HYBRID | 0.587 | 0.826 | 0.848 | 0.682 |
| FULL_TEXT | 0.370 | 0.609 | 0.717 | 0.473 |

| Chunking | R@5 | MRR | Tokens in top 5 |
|----------|-----|-----|-----------------|
| 200/40 | 0.848 | 0.722 | 604 |
| 400/60 | 0.891 | 0.787 | 909 |
| 800/120 | 0.891 | 0.788 | 1,286 |

All runs are logged to the MLflow experiment `careconnect-dev` with per-question tables.

## MLOps track: PHS waiting times (`src/careconnect/phs/`)

- **Source:** Public Health Scotland "Stage of Treatment Waiting Times: Ongoing Waits -
  Long Trend" plus health board, special board, ISD board, residential-category and
  specialty lookups (Open Government Licence).
- **Tables:** `bronze_phs_ongoing_waits` (raw text plus file hash and load time),
  `silver_phs_ongoing_waits` (typed, named, Scotland and all-specialty flags, share over
  12 weeks), `ops_phs_rejects`, `ops_dq_results` (appended every run).
- **Checks that remove rows:** invalid or future month, blank board, negative counts,
  waits over 12 weeks above the total, duplicate keys.
- **Checks that warn:** blank counts (11,236 rows that PHS did not publish), unknown
  board or specialty codes (10 rows with retired specialty `H3`), median above the 90th
  percentile, data more than 120 days old.
- PHS revises past months, so each load is a full refresh, skipped when the file hash
  is unchanged.

## Decisions

All in `docs/decisions/`:

- `2026-10-09-workspace-layout.md`: one schema per environment, medallion layers as
  table prefixes, no dev prefix on schemas.
- `2026-10-09-retrieval-query-type.md`: ANN as the default query type; keep 400/60
  chunks.
- `2026-10-09-free-edition-no-egress.md`: serverless jobs cannot reach the internet, so
  PHS files are downloaded on the laptop and the job loads from the Volume.
- `2026-10-09-mlflow-trace-storage.md`: experiment storage now, Unity Catalog storage
  for the agent's traces when it is served.

## Problems and fixes

| Problem | Fix |
|---------|-----|
| Chunks went over the 400-token budget, and some PDF chunks had 1 token | Measure the joined chunk instead of summing units; trim overlap; merge PDF sections under 4 words |
| Every PDF chunk said page 1 | Inline page markers, chunk page = page of its first unit |
| Contents-page lines and wrapped sentences became section headings | Drop dot-leader contents lines; reject a heading followed by a lowercase line |
| AI Search index took about 24 minutes the first time | Normal for a new endpoint; re-runs wait instead of re-syncing a building index |
| Embedding endpoint rate-limited direct calls | Cached, paced embeddings; chunking comparison run with a local model |
| PHS lookup file was not UTF-8 | Fall back to Windows-1252 and normalise non-breaking spaces |
| 5,401 rows with unnamed board codes | Added the ISD board-of-treatment and RA27 residential-category lookups |
| PHS job could not resolve opendata.nhs.scot | Free Edition serverless has no internet: download locally, job loads from the Volume |

## How to run

```powershell
uv run pytest -m "not integration"            # unit tests
uv run ingest --env dev                        # documents -> Delta tables
uv run python -m careconnect.search.index --env dev        # create or sync the index
uv run python -m careconnect.search.retriever "How do I complain?"
uv run python -m careconnect.evals.retrieval --env dev --mode index
uv run phs --env dev --download                # PHS files -> Volume -> tables (monthly)
databricks bundle deploy -t dev
databricks bundle run ingest_job -t dev
databricks bundle run phs_job -t dev
```

## Carried into Week 3

- Answer generation with citations on top of the retriever, and answer-quality
  evaluation (LLM judge on faithfulness and relevance).
- Questions with exact terms (CHI, HC2, clinic names) to re-test HYBRID search.
- A gold waiting-times table and a first forecasting model on the Scotland series.
- Agent traces in a Unity Catalog-bound experiment.
