# Week 2 Complete Report: Data and Knowledge Processing

**Project:** CareConnect Navigator (healthcare MLOps and LLMOps portfolio project)
**Course schedule window:** 19 to 25 October 2026, followed self-paced without enrolling
**Work completed:** 9 October 2026, ahead of the course week, continuing directly from Week 1 (7 and 8 October); review and clean-up on 10 October
**Environment:** Windows laptop (PowerShell, uv, VS Code) connected to Databricks Free Edition
**Repository:** https://github.com/dmishra27/careconnect-navigator (branch `main`, pull request #2 merged)

## 1. Summary

Week 1 built the workbench: a laptop connected to Databricks, a Python project, a first traced LLM call, and a bundle that deploys jobs. Week 2 put real material on that workbench.

In plain terms, Week 2 did three things:

- **Built a library.** 28 healthcare documents (22 service leaflets and 6 Scottish Government policy documents) were read, cleaned, checked for personal data and cut into 353 small, labelled passages called chunks. These are stored as tables in Databricks.
- **Built a search engine over the library and measured how good it is.** An AI Search index finds the right passage for a patient's question. On 46 test questions it puts the right passage in the top 5 results 89% of the time and in the top 10 results 96% of the time. Two settings were chosen from evidence, not guesswork: the search method and the chunk size.
- **Started the numbers side of the project.** 145,789 rows of official Public Health Scotland waiting-times statistics (October 2012 to June 2026) were loaded and cleaned, with automatic data-quality checks recorded every run. This data feeds the forecasting work in later weeks.

Section 8 logs all 13 experiments with their numbers and conclusions, and section 9 sets out what the waiting-times data shows: in June 2026, 62.8% of inpatient and day-case waits in Scotland were over 12 weeks.

Everything runs as scheduled jobs on Databricks serverless compute, defined in the bundle, tested by 82 automated tests, and merged to `main` through pull request #2 and a follow-up clean-up pull request. All eight open items carried over from Week 1 are closed.

## 2. How Week 2 continues from Week 1

### 2.1 Where Week 1 finished

| Area | State at the end of Week 1 |
| --- | --- |
| Laptop setup | Python 3.12 project managed by uv, Ruff and pre-commit on every commit |
| Connection to Databricks | CLI profile `DEFAULT`, Databricks Connect 18 on serverless environment 5 |
| Configuration | `project_config.yml` per environment, loaded by `ProjectConfig` |
| LLM | One traced call to Llama 3.3 70B, logged in the MLflow experiment `careconnect-dev` |
| Deployment | Bundle with the template's sample taxi job; schema `dmishra27` created by hand |
| Data | None yet |
| Tests | 3 |

### 2.2 The open items Week 1 handed over, and how each was closed

| Week 1 open item | How it was closed in Week 2 | Evidence |
| --- | --- | --- |
| Define schemas in the bundle instead of by hand | `resources/schemas.yml` defines schema `careconnect_dev` (dev) and `careconnect_prod` (prod) | `bundle deploy` created the schema; old `dmishra27` schema deleted |
| Add a landing Volume for source documents | Managed Volume `landing` defined in the same file | `/Volumes/workspace/careconnect_dev/landing` holds all source files |
| Remove the template's sample taxi job and test | Job, `taxis.py`, `main.py` and the taxi test deleted | Commit `dc5a680` |
| Gather Scottish Government PDFs | 6 public documents chosen and recorded in a source manifest | `data/raw/policies/sources.csv` |
| Write about 20 synthetic leaflets | 22 leaflets for the fictional Firth Valley Health Board | `data/raw/leaflets/` |
| Make the Spark session in tests lazy | Spark starts only when a test asks for it; `integration` marker added | Offline tests run in seconds without Databricks |
| Decide on MLflow trace storage | Decision recorded: experiment storage now, Unity Catalog storage for the agent later | `docs/decisions/2026-10-09-mlflow-trace-storage.md` |
| Re-run environment setup for newer serverless versions | Still on serverless environment 5 (current); nothing to do | Jobs run on `environment_version: "5"` |

So Week 2 started by finishing Week 1's housekeeping (Steps 1 to 3), then moved on to the week's own work (Steps 4 to 11).

## 3. Week 2 in the course schedule

| Item | Detail |
| --- | --- |
| Course week | 19 to 25 October 2026 |
| Live session | Wednesday 21 October, 15:00 to 17:00 (UK time): "Data & knowledge processing" |
| Topic on the course page | Data and knowledge processing: chunking, vector search, pipeline design |
| Assignment | "Prepare data for your AI application" (submit by 28 October) |

As in Week 1, the course page lists titles only, so the objectives below were derived from the session topic and the assignment title, applied to this project.

## 4. Stated objectives and final status

**Week 2 goal, as stated at the start:** turn raw healthcare documents into a governed, searchable knowledge base. Files land in a Volume, an ingest job parses and chunks them into Delta tables, an AI Search index stays in sync with those tables, and retrieval quality is measured before any agent uses it. In parallel, start the MLOps track with clean waiting-times data.

| Step | Objective | What was delivered | Status |
| --- | --- | --- | --- |
| 0 | Work on a branch | `week2-data` branch, merged at the end | Done |
| 1 | Schemas and landing Volume in the bundle | `careconnect_dev` schema and `landing` Volume created by `bundle deploy` | Done |
| 2 | Remove the template's taxi job, code and test | All removed, bundle and tests clean | Done |
| 3 | Lazy Spark fixture in tests | Non-Spark tests run without starting serverless | Done |
| 4 | Source documents | 22 synthetic leaflets, 10-site clinics file, 6 public policy PDFs | Done |
| 5 | Upload sources to the Volume | Files in `landing/leaflets`, `landing/policies`, `landing/reference` | Done |
| 6 | Ingest pipeline: parse, clean, PII scan, chunk | `bronze_documents` (28), `silver_chunks` (353), `ops_pii_quarantine` (0) | Done |
| 7 | Ingest job on serverless | `ingest_job` runs green; a second task refreshes the search index | Done |
| 8 | AI Search endpoint and Delta Sync index | `careconnect-search` endpoint, `silver_chunks_index` with 353 rows | Done |
| 9 | Retrieval evaluation, recall@5 and MRR, chunk sizes | 46 labelled questions; 3 search methods and 3 chunk sizes compared; logged to MLflow | Done |
| 10 | MLOps track: PHS waiting times with data-quality checks | `silver_phs_ongoing_waits` (145,789 rows), rejects and DQ results tables, `phs_job` | Done |
| 11 | Tests, notes, pull request and merge | 82 unit tests, 4 decision records, `docs/week2.md`, PR #2 merged | Done |

Two things turned out differently from the plan, both for good reasons:

- **Search method.** The plan said "hybrid query returns relevant chunks". The evaluation showed that plain vector search (ANN) clearly beats hybrid on this data, so ANN became the default and the reasoning was recorded.
- **PHS download.** The plan had the job download data from the internet. Free Edition jobs cannot reach the internet, so the download moved to the laptop and the job loads from the Volume.

## 5. The big picture: how the pieces fit together

```text
LLMOps track (knowledge base)

  Leaflets, policy PDFs, clinics CSV
      │
      ▼
  landing Volume
      │
      ▼
  ingest task ──► bronze_documents
      ├─────────► silver_chunks (353 chunks, change feed on)
      └─────────► ops_pii_quarantine
                       │
                       ▼
  sync_index task ──► AI Search index (managed embeddings)
                       │
                       ▼
  retriever (ANN, current documents only)
                       │
                       ▼
  retrieval evaluation ──► MLflow experiment

MLOps track (waiting-times statistics)

  PHS open data ──► laptop download ──► landing/phs
                                           │
                                           ▼
  phs job ──► bronze_phs_ongoing_waits
      ├─────► silver_phs_ongoing_waits
      ├─────► ops_phs_rejects
      └─────► ops_dq_results (appended every run)
```

The naming follows the "medallion" idea used in data engineering:

- **Bronze:** data as it arrived, kept for traceability.
- **Silver:** cleaned, typed and checked data that the rest of the project uses.
- **Gold:** summaries built for a specific use. These come in Week 3 for forecasting.
- **Ops:** operational records, such as quarantined documents, rejected rows and check results.

## 6. Data sources

All data is either synthetic (written for this project) or public. No real patient data is used anywhere. This matters because the Free Edition terms allow Databricks to use workspace data, and because a healthcare project should show safe data handling from the start.

### 6.1 Synthetic service leaflets (Firth Valley Health Board)

Firth Valley Health Board is a fictional NHS board created for the project. Its leaflets read like real patient information, with realistic rules, opening hours and phone numbers. Phone numbers use the Ofcom range reserved for drama (01632 960xxx), and email addresses use the reserved `.example` domain. Real national services (NHS 24, 999, NHS inform, PASS, SPSO, Care Opinion, Breathing Space, Samaritans) appear with their real public details.

Each leaflet is a Markdown file with a small header (front matter) recording its ID, title, service, status and dates.

| No. | Leaflet | Service |
| --- | --- | --- |
| 01 | About Firth Valley Health Board | General |
| 02 | Booking and changing your hospital appointment | Appointments |
| 02 (2024) | Booking and changing your hospital appointment, 2024 edition (superseded) | Appointments |
| 03 | What happens if you miss an appointment | Appointments |
| 04 | Our hospital sites and opening hours | Sites |
| 05 | Community clinics directory | Sites |
| 06 | Parking at our hospitals | Travel |
| 07 | Public transport and patient transport | Travel |
| 08 | Help with travel costs | Travel |
| 09 | Interpreting and translation services | Access |
| 10 | Additional support and accessibility | Access |
| 11 | Waiting times explained | Waiting times |
| 12 | How referrals from your GP work | Referrals |
| 13 | Your outpatient appointment: what to expect | Appointments |
| 14 | Preparing for day surgery | Surgery |
| 15 | Visiting patients in hospital | Inpatient |
| 16 | Making a complaint | Feedback |
| 17 | Giving feedback | Feedback |
| 18 | Patient Advice and Support Service (PASS) | Feedback |
| 19 | Accessing your health records | Records |
| 20 | When to call NHS 24 or 999 | Urgent care |
| 21 | Test results and follow-up | Results |

One leaflet deliberately has an out-of-date 2024 edition with different rules (it allows two changes instead of one, and has a different phone line). It tests that search never shows superseded guidance.

A companion file, `data/raw/reference/clinics.csv`, lists 10 fictional sites and clinics with addresses, phone numbers, opening hours and services, for lookup tools in later weeks.

Licence: CC0-1.0 (written for this project).

### 6.2 Scottish Government and NHS Scotland policy documents

| Document | Publisher | Licence |
| --- | --- | --- |
| Charter of Patient Rights and Responsibilities (revised June 2022) | Scottish Government | Open Government Licence v3.0 |
| NHSScotland Waiting Times Guidance (November 2023) | Scottish Government | Open Government Licence v3.0 |
| DL(2023)32 Waiting Times Guidance | Scottish Government Health Directorates | Open Government Licence v3.0 |
| NHS Scotland Model Complaints Handling Procedure | Scottish Public Services Ombudsman | Publisher's terms |
| Patient Rights (Scotland) Act 2011 | legislation.gov.uk | Open Government Licence v3.0 |
| Waiting for NHS Treatment (patient leaflet) | Scottish Government | Open Government Licence v3.0 |

The PDFs are downloaded from the publishers' websites and uploaded to the Volume. They are not stored in Git; `data/raw/policies/sources.csv` records the title, publisher, download address and licence of each.

### 6.3 Public Health Scotland waiting-times statistics

Source: Public Health Scotland open data portal (opendata.nhs.scot), UK Open Government Licence.

| File | What it contains |
| --- | --- |
| `ongoing_waits.csv` | Stage of Treatment Waiting Times: Ongoing Waits, Long Trend. For each month, health board, patient type and specialty: number waiting, number waiting over 12 weeks, median and 90th-percentile wait in days |
| `hb14_hb19.csv` | Health board codes and names |
| `special_health_boards.csv` | Special boards and national facilities, such as the Golden Jubilee |
| `isd_health_board_of_treatment.csv` | Extra board-of-treatment codes, such as non-NHS providers |
| `other_residential_categories.csv` | Catch-all residential codes used in place of a board |
| `specialty_codes.csv` | Specialty codes and names |
| `statistical_qualifiers.csv` | Meaning of PHS qualifier flags, such as "not available" or "derived" |

These are aggregate counts. They contain no information about individual patients. The CSV files are downloaded by the pipeline and not stored in Git; `data/raw/phs/README.md` records their origin.

### 6.4 Evaluation questions

`data/eval/retrieval_questions.yml` holds 46 test questions written the way a patient would ask them. For example, "Can I take the bus home after my day surgery?" rather than the leaflet's wording. Each question is labelled with the document that answers it and a short phrase that must appear in the retrieved passage. They cover 21 leaflets and 5 policy documents.

### 6.5 Where the data lives in Databricks

```text
/Volumes/workspace/careconnect_dev/landing/
├── leaflets/     22 Markdown files
├── policies/     6 PDFs + sources.csv
├── reference/    clinics.csv
└── phs/          7 PHS CSV files
```

## 7. How it was built, step by step

### 7.1 Steps 0 to 3: finishing the foundations

The schema and Volume moved into the bundle, so the workspace is now fully defined by code:

```yaml
resources:
  schemas:
    careconnect:
      catalog_name: ${var.catalog}
      name: ${var.schema}
  volumes:
    landing:
      catalog_name: ${var.catalog}
      schema_name: ${resources.schemas.careconnect.name}
      name: landing
      volume_type: MANAGED
```

A setting in `databricks.yml` (`experimental: skip_name_prefix_for_schema: true`) stops development mode renaming the schema to `dev_dmishra27_careconnect_dev`, so the name matches `project_config.yml` exactly. The template's taxi job and its code and test were deleted. The test setup now only starts a Spark session when a test needs one, and such tests are marked `integration`, so everyday tests run offline in seconds.

```powershell
databricks bundle validate
databricks bundle deploy -t dev
databricks schemas get workspace.careconnect_dev
databricks volumes read workspace.careconnect_dev.landing
```

### 7.2 Steps 4 and 5: gathering and uploading the sources

The leaflets, clinics file and policy manifest were committed to `data/raw/`. The PDFs were downloaded locally, then everything was copied into the Volume:

```powershell
databricks fs cp -r data/raw/leaflets dbfs:/Volumes/workspace/careconnect_dev/landing/leaflets
databricks fs cp -r data/raw/policies dbfs:/Volumes/workspace/careconnect_dev/landing/policies
databricks fs cp -r data/raw/reference dbfs:/Volumes/workspace/careconnect_dev/landing/reference
```

### 7.3 Step 6: the ingest pipeline

The pipeline (`src/careconnect/ingest/`) turns files into searchable passages in five stages:

1. **Read.** It reads files from the Volume, or from a local folder for testing. The same code works on the laptop and in a Databricks job.
2. **Parse and clean.**
   - **Leaflets:** the header fields become metadata, and the headings define sections such as "Making a complaint > Time limits".
   - **PDFs:** the text is extracted with pypdf, then cleaned. Repeating headers and footers, page numbers and contents-page lines are removed; words broken across lines are re-joined; numbered headings such as "2. Purpose" and "Annex 4" become section titles.
   - **Page tracking:** each PDF chunk records the page it starts on, so answers can later cite "see page 7".
3. **Check for personal data.**
   - **Quarantined (never indexed):** documents containing a patient identifier: a CHI number, a National Insurance number, or a labelled field such as "Date of birth: ...".
   - **Recorded only:** personal-looking email addresses. Organisational addresses such as `nhs.scot` are allowed.
   - **Masking:** the findings never store the value itself, only a masked excerpt.
4. **Chunk.**
   - **Size:** each section is cut into chunks of up to 400 tokens, roughly 300 words, with 60 tokens of overlap so that no sentence loses its context at a boundary.
   - **Boundaries:** chunks never cross from one section to another.
   - **Labels:** every chunk starts with a context line such as "Making a complaint > Time limits", so it makes sense on its own.
5. **Write.**
   - **Tables:** results go to Delta tables. Change Data Feed is switched on for `silver_chunks`, so the search index can follow every change.
   - **Unchanged files:** each file's fingerprint (hash) is compared with the last run, so unchanged files are skipped.
   - **After a code change:** `--full-refresh` rebuilds everything.

```powershell
uv run ingest --env dev --dry-run        # parse and chunk only, no writes
uv run ingest --env dev                  # write the tables
uv run ingest --env dev --full-refresh   # rebuild after a code change
uv run python scripts/check_ingest.py    # inspect counts, pages and quarantine
```

| Result | Value |
| --- | --- |
| Documents | 28 (22 leaflets, 6 policies) |
| Chunks | 353 (106 from leaflets, 247 from policies) |
| Chunk size | 5 to 400 tokens, median 209 |
| Quarantined documents | 0 |
| Low-severity findings | 6 (email addresses in the policy PDFs) |
| Second run with no changes | 0 documents rewritten |

### 7.4 Step 7: the ingest job

`resources/ingest_job.job.yml` runs the pipeline as a serverless job, using the project's own Python package (wheel). It has two tasks: `ingest`, then `sync_index` (Step 8). It is scheduled daily at 06:00 UK time, paused in dev.

```powershell
databricks bundle deploy -t dev
databricks bundle run ingest_job -t dev
```

Final run: both tasks succeeded in 2 minutes 15 seconds. 28 documents were unchanged, and the index reported 357 rows (353 after the 10 October clean-up, section 7.9).

### 7.5 Step 8: the search index

**What it does.** A search index stores a numerical "meaning fingerprint" (an embedding) for each chunk. A question is turned into the same kind of fingerprint, and the closest chunks are returned. Databricks AI Search (formerly Vector Search) does this.

- **Endpoint:** `careconnect-search`, the single AI Search endpoint Free Edition allows.
- **Index:** `workspace.careconnect_dev.silver_chunks_index`, a Delta Sync index. It follows `silver_chunks` through its change feed.
- **Embeddings:** managed. Databricks creates them with `databricks-gte-large-en`, so no vectors are stored in our tables.
- **Refresh:** triggered by the job's `sync_index` task, rather than continuously, to keep Free Edition usage low.
- **Filtering:** the retriever always asks for current documents only, so the superseded leaflet never appears.

```powershell
uv run python -m careconnect.search.index --env dev
uv run python -m careconnect.search.retriever "Can I change my appointment online?"
```

The first build took about 24 minutes, because the endpoint's machine had to start up. Later refreshes take 1 to 5 minutes.

### 7.6 Step 9: measuring retrieval quality

A search engine that looks plausible can still miss the right answer, so it was measured before any agent relies on it.

- **Recall@k:** for how many questions the right passage appears in the top k results.
- **MRR (mean reciprocal rank):** rewards putting the right passage first. It scores 1 for rank 1, 0.5 for rank 2, 0.33 for rank 3, and so on, averaged over all questions.

A retrieved chunk counts as correct if it comes from the labelled document and contains the labelled phrase. Because the labels don't refer to chunk IDs, the same questions can score any chunk size.

**Search methods on the live index:**

| Method | What it does | R@1 | R@5 | R@10 | MRR |
| --- | --- | --- | --- | --- | --- |
| ANN | Meaning-based (vector) search | 0.783 | 0.891 | 0.957 | 0.828 |
| Hybrid | Meaning plus keywords, merged | 0.587 | 0.826 | 0.848 | 0.682 |
| Full text | Keywords only | 0.370 | 0.609 | 0.717 | 0.473 |

**Chunk sizes, compared offline with one embedding model:**

| Chunk size / overlap | Chunks | R@5 | MRR | Tokens an LLM reads for the top 5 |
| --- | --- | --- | --- | --- |
| 200 / 40 | 561 | 0.848 | 0.722 | 604 |
| 400 / 60 | 355 | 0.891 | 0.787 | 909 |
| 800 / 120 | 277 | 0.891 | 0.788 | 1,286 |

The chunk counts above cover current documents only, which is what search can return; that is why 400/60 shows 355 rather than the 357 in the table at the time, which included the superseded leaflet.

What the results mean:

- **ANN wins clearly.** It puts the right passage first for 36 of 46 questions; hybrid manages 27. Keyword matching on its own is weak here, and merging it in pulls long policy passages full of words like "complaint" above the short leaflet sections that actually answer the question.
- **400/60 is the sweet spot.** 800/120 finds nothing more but sends about 40% more text to the LLM. 200/40 is cheaper but misses the top result more often.
- **Logging:** every run is logged to MLflow with its settings, scores and a per-question table.

```powershell
uv run python -m careconnect.evals.retrieval --env dev --mode index
uv run --with sentence-transformers python -m careconnect.evals.retrieval --env dev --mode chunks --embedder local
```

### 7.7 Step 10: the waiting-times pipeline (MLOps track)

The PHS pipeline (`src/careconnect/phs/`) works like this:

1. **Download.** `uv run phs --env dev --download` fetches the latest PHS files to the laptop and uploads them to `landing/phs`.
2. **Bronze.** The raw file is stored as text, with its fingerprint and load time.
3. **Silver.** Columns are renamed and typed, codes are given names from the lookups, and rows are flagged for Scotland totals and "all specialties" totals. The share waiting over 12 weeks is also calculated.
4. **Data-quality checks.**
   - **Remove a row:** an unreadable or future month, a missing board, negative counts, more people over 12 weeks than in total, or duplicate rows.
   - **Warn but keep:** blank counts, unknown codes, a median above the 90th percentile, or data more than 120 days old.
5. **Record.** Removed rows go to `ops_phs_rejects`, and every check's result is appended to `ops_dq_results`, so data quality can be tracked over time.
6. **Skip if unchanged.** PHS revises past months, so each load replaces the tables in full, but it is skipped when the file is identical to the last one.

| Result | Value |
| --- | --- |
| Rows loaded | 145,789 (0 rejected) |
| Period | October 2012 to June 2026 (165 months) |
| Coverage | 19 board codes, 98 specialties, 2 patient types (Inpatient/Day case, New Outpatient) |
| Scotland totals | 330 rows (165 months × 2 patient types): the series for forecasting |
| Warnings | 11,236 blank counts that PHS did not publish; 10 rows with retired specialty `H3` |
| Job run on serverless | Succeeded in 1 minute 4 seconds; correctly skipped an unchanged file |

### 7.8 Step 11: wrap-up and merge

The index refresh became the second task of the ingest job. Four decision records and `docs/week2.md` were written. The work was merged to `main`:

```powershell
git push
# pull request #2 created and merged on GitHub
git switch main
git pull
git branch -d week2-data
git push origin --delete week2-data
```

### 7.9 Review and clean-up (10 October)

Every claim in this report was checked directly in Databricks (SQL editor, Jobs and MLflow). The check confirmed all the figures and found one gap: 13 policy chunks under 20 tokens. Nine were in the Waiting Times Guidance, where its contents page (entries such as "4.1 Communication with Patients 7", with no dot leaders) and a "DRAFT" watermark had been read as section headings. The other four were genuine one-line sections of the Patient Rights (Scotland) Act.

The PDF cleaner now drops numbered or Annex-style lines that end in a page number, and stand-alone watermarks. The tables and index were rebuilt and the evaluation re-run:

| Measure | 9 October | 10 October |
| --- | --- | --- |
| Chunks | 357 | 353 |
| Policy chunks | 251 | 247 |
| Tiny chunks, Waiting Times Guidance | 9 | 4 |
| Tiny chunks, Patient Rights Act | 4 | 4 (genuine short sections) |
| ANN R@1 / R@5 / R@10 / MRR | 0.783 / 0.891 / 0.957 / 0.828 | 0.783 / 0.891 / 0.957 / 0.828 |
| Hybrid R@1 / R@5 / MRR | 0.587 / 0.826 / 0.682 | 0.609 / 0.826 / 0.688 |
| Full text R@1 / R@5 / MRR | 0.370 / 0.609 / 0.473 | 0.326 / 0.609 / 0.438 |

What this shows:

- **ANN, the search method the project uses, is unchanged.** The noise chunks were never what it returned, so removing them is a clean-up with no cost.
- **Keyword search lost a little.** The contents lines repeated section titles word for word ("Treatment Time Guarantee 31"), which happened to help keyword matching. That reinforces the decision to use ANN.
- The PHS download also gained automatic retries after the portal dropped a connection once.

## 8. Experiment log

Every experiment run during Week 2, in the order it happened, each in the same shape: the question it answered, how it was run, what came out (with the actual numbers) and what was concluded. All figures come from the run outputs and from MLflow.

### E1. Do chunks stay within the 400-token budget?

- **Question:** does the chunker respect its limits on real documents?
- **Setup:** dry run of the ingest pipeline over all 28 documents (`uv run ingest --dry-run`).
- **Result:** 386 chunks, but the largest was 416 tokens (over budget) and the smallest was 1 token. Token counts had been added up piece by piece, which undercounts the joined chunk, and stray lines between PDF headings became one-word chunks.
- **Change:** measure the joined chunk instead of summing pieces, trim the carried-over overlap when needed, and merge PDF sections of under 4 words into the next section.
- **Re-run:** 374 chunks, smallest 5 tokens, largest exactly 400.
- **Conclusion:** unit tests on invented text had passed; only real documents exposed the problem. Limits must be tested on the real corpus.

### E2. Does the load skip unchanged files?

- **Question:** is the pipeline safe to run every day?
- **Setup:** full load, then the same command again with no file changes.
- **Result:** first run wrote 28 documents and 374 chunks; second run changed 0 documents. The same held later inside the Databricks job (28 unchanged, 0 chunks written).
- **Conclusion:** file fingerprints work; daily scheduled runs cost almost nothing when nothing changes.

### E3. Do PDF chunks get the right page number?

- **Question:** can an answer cite the page a passage comes from?
- **Setup:** count distinct pages per policy document in `silver_chunks`.
- **Result before:** every chunk of the Charter showed page 1, because a chunk took the page where its section began.
- **Change:** an invisible page marker is placed wherever a section runs onto a new page; each chunk takes the page of its first sentence.
- **Result after:**

| Document | Chunks | Distinct pages | Page range |
| --- | --- | --- | --- |
| Charter of Patient Rights | 40 | 26 | 1 to 29 |
| NHS Model Complaints Procedure | 87 | 55 | 1 to 62 |
| Waiting Times Guidance | 80 | 43 | 1 to 49 |
| Patient Rights (Scotland) Act | 43 | 16 | 1 to 16 |
| DL(2023)32 | 16 | 6 | 1 to 7 |
| Waiting for NHS Treatment | 3 | 2 | 1 to 2 |

- **Conclusion:** citations like "see page 7" are now possible. Chunk counts moved from 374 to 375 because a page break became a valid split point.

### E4. Do the first searches return sensible results?

- **Question:** before measuring anything, does the index answer real questions?
- **Setup:** three searches with the first retriever (hybrid at that time) over 375 chunks.
- **Result:**

| Question | What came back | Verdict |
| --- | --- | --- |
| "How do I make a complaint and how long do I have?" | Charter (pages 22 and 23), the complaints procedure labelled "Appendix 3 ... 46", and the leaflet's "How we handle complaints" at rank 4. The leaflet's "Time limits" section did not appear. | Partly right; exposed a contents-page heading and a missed section |
| "What is the 12 week treatment time guarantee?" (policies only) | Waiting Times Guidance pages 4, 41 and 44; the Act, sections 8 and 9 | All five relevant, with pages |
| "Can I change my appointment online?" | Current booking leaflet first; superseded edition never shown; two unrelated Charter passages at ranks 2 and 4 | Right answer first; filter works |

- **Conclusion:** search worked, but looking at results by eye found two problems the counts had hidden (contents-page headings, a missed short section). That motivated the cleaning work in E5 and the measured evaluation in E7.

### E5. How much did each PDF cleaning rule change the chunks?

- **Question:** which cleaning rules matter, and by how much?
- **Setup:** re-ingest after each rule; compare chunk counts, median size and the labels search returns.
- **Result:**

| Step | Rule added | Chunks | Median tokens | Effect seen in search |
| --- | --- | --- | --- | --- |
| Start | Budget fix and fragment merge (E1) | 374 | not recorded | – |
| +page markers | Page breaks become split points (E3) | 375 | 155 | – |
| +dot-leader contents | Drop lines like "Appendix 3 ... 46" | 373 | 155 | "Appendix 3 ... 46" label gone, replaced by "1 On receiving a complaint, you must first decide whether the issue can indeed be" |
| +wrapped sentences | A "heading" followed by a lowercase line is part of a sentence | 357 | 209 | That half-sentence label gone; the procedure's text keeps its real section |
| +contents without dots, watermarks (10 October) | Drop "4.1 Communication with Patients 7" and "DRAFT" | 353 | 213 | Tiny Guidance chunks 9 to 4 (see section 7.9) |

- **Conclusion:** the biggest single change was the wrapped-sentence rule: false headings had been cutting sections into small pieces, and fixing it removed 16 chunks and raised the median from 155 to 209 tokens. Cleaning rules for PDF structure mattered more than any chunk-size setting.

### E6. How long does the search index take to build and refresh?

- **Question:** what does keeping the index in sync cost in time?
- **Setup:** time each `build-index` run from start to "ready".
- **Result:**

| Run | Change in the table | Time to ready |
| --- | --- | --- |
| First build (new endpoint) | 375 rows added | about 24 minutes (16 waiting for the endpoint's machine, 8 indexing) |
| Refresh after dot-leader rule | 375 to 373 | about 4.5 minutes |
| Refresh after wrapped-sentence rule | 373 to 357 | about 8 minutes |
| Refresh in the ingest job | no changes | under a minute |
| Refresh after 10 October clean-up | 357 to 353 | about 10 minutes |

- **Conclusion:** the first build is slow because the endpoint starts up; refreshes take minutes and scale with the amount of change, including deletions. A triggered refresh after each ingest is the right fit for Free Edition.

### E7. Which search method finds the right passage most often?

- **Question:** ANN (meaning), full text (keywords) or hybrid (both)?
- **Setup:** 46 labelled questions against the live index (357 chunks), top 10 results each, all three methods; logged to MLflow as `index-*`.
- **Result:**

| Method | R@1 | R@3 | R@5 | R@10 | MRR | Right document in top 5 |
| --- | --- | --- | --- | --- | --- | --- |
| ANN | 0.783 | 0.826 | 0.891 | 0.957 | 0.828 | 0.978 |
| Hybrid | 0.587 | 0.783 | 0.826 | 0.848 | 0.682 | 0.913 |
| Full text | 0.370 | 0.565 | 0.609 | 0.717 | 0.473 | 0.717 |

- **Conclusion:** ANN puts the right passage first for 36 of 46 questions, against 27 for hybrid, and finds the right document in the top 5 for 45 of 46. Merging in keyword results lets long policy passages full of matching words push short, precise leaflet sections down. ANN became the default (decision record). Caveat: questions were deliberately written in patients' own words, which favours meaning-based search.

### E8. Can the chunk-size comparison use the index's own embedding model?

- **Question:** can chunk sets be embedded directly with `databricks-gte-large-en`?
- **Setup:** call the embedding endpoint directly for 46 questions and about 1,200 chunk texts.
- **Result:** refused with "Exceeded workspace QPS rate limit" even for the first 46 texts, after the SDK's 5 minutes of retries; slower pacing did not help.
- **Change:** run the comparison with an open model on the laptop (`BAAI/bge-base-en-v1.5`), the same model for every chunk size, with embeddings cached to disk.
- **Check:** with 400/60 chunks the laptop model reached the same R@5 as the live index (0.891), with a slightly lower MRR (0.787 against 0.828).
- **Conclusion:** Free Edition throttles direct embedding calls; a local model is a fair way to compare chunk sizes against each other, though not to compare against the index.

### E9. Which chunk size works best?

- **Question:** small (200/40), medium (400/60) or large (800/120) chunks?
- **Setup:** rebuild chunks at each size from the Volume, embed with the laptop model, rank by similarity, same 46 questions; logged as `chunks-*`.
- **Result:**

| Size / overlap | Chunks | R@1 | R@3 | R@5 | R@10 | MRR | Right document in top 5 | Tokens in top 5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 200 / 40 | 561 | 0.630 | 0.761 | 0.848 | 0.913 | 0.722 | 0.935 | 604 |
| 400 / 60 | 355 | 0.717 | 0.826 | 0.891 | 0.935 | 0.787 | 0.957 | 909 |
| 800 / 120 | 277 | 0.717 | 0.826 | 0.891 | 0.935 | 0.788 | 0.935 | 1,286 |

- **Conclusion:** 800/120 finds nothing extra but sends about 40% more text to the LLM per answer and finds the right document slightly less often; 200/40 is cheapest but misses the top result for 4 more questions. 400/60 kept. The median chunk size (212, 164, 95) is not a useful comparison: leaflet sections are short at any setting, so the distribution has two groups.

### E10. What do individual questions show?

- **Question:** where does search fail, and why?
- **Setup:** the per-question table attached to each MLflow run (`per_question.json`): rank of the first correct passage, and whether the right document was in the top 5.
- **Result (examples from the 800/120 run):**

| Question | First correct rank | Right document in top 5 | Reading |
| --- | --- | --- | --- |
| q01 "Is there a deadline for raising a complaint...?" | not in top 10 | no | Long complaints-procedure passages crowd out the leaflet's short "Time limits" section |
| q35 "Is there an independent service...?" | not in top 10 | yes | Right leaflet found, but not the passage with the evidence |
| q02 "How long does a full investigation take?" | 2 | yes | Close miss |
| q07 "If my child misses a hospital appointment...?" | 2 | yes | Close miss |

- **Conclusion:** the q01 failure is the same weakness first seen by eye in E4, now measured. Questions that fail under every setting point to content or labelling gaps rather than search settings; these are the starting point for Week 3.

### E11. Do the PHS lookups name every code?

- **Question:** does every board and specialty code in the waiting-times file have a name?
- **Setup:** dry runs of the PHS pipeline, adding lookups until the `known_board` check passed.
- **Result:**

| Run | Change | Rows with an unnamed board code |
| --- | --- | --- |
| 1 | Health board and special board lookups | failed to read: a lookup file was Windows-1252, not UTF-8 |
| 2 | Encoding fallback added | 5,401 |
| 3 | + ISD health board of treatment lookup | 1,813 (codes RA2704: 1,617; RA2702: 196) |
| 4 | + Other residential categories lookup | 0 |

- **Also found:** 72 rows with a blank specialty (NHS Greater Glasgow and Clyde patients under several specialties, as the PHS dictionary explains) and 10 rows with specialty `H3`, missing from the current lookup.
- **Conclusion:** the warning-level checks did their job: each one pointed to the next missing lookup, and no row had to be removed.

### E12. Can a Databricks job download from the internet?

- **Question:** can the monthly PHS job fetch new files itself?
- **Setup:** run `phs_job` on serverless compute with the download switched on.
- **Result:** failed after about 90 seconds with "Temporary failure in name resolution": the job could not even look up opendata.nhs.scot. Without the download, the job succeeded in 1 minute 4 seconds and correctly skipped an unchanged file.
- **Conclusion:** Free Edition serverless compute has no internet access. Files are downloaded on the laptop and the job loads from the Volume (decision record). A later laptop download also met a dropped connection from the portal, so downloads now retry automatically.

### E13. Does every figure in this report match Databricks?

- **Question:** are the report's claims true in the workspace itself?
- **Setup:** on 10 October, each summary claim was checked in the SQL editor, the Jobs pages and the MLflow experiment.
- **Result:** every figure matched: 28 documents (21 current leaflets, 1 superseded, 6 policies), 0 quarantined, 106 leaflet and 251 policy chunks with a maximum of 400 tokens, 145,789 waiting-times rows from October 2012 to June 2026, 11 data-quality results with 0 rejected rows, both jobs successful, and the evaluation scores in MLflow. The check also found 13 policy chunks under 20 tokens, fixed in section 7.9.
- **Conclusion:** checking outputs against the source, not only running tests, found the one remaining cleaning gap.

## 9. What the waiting-times data shows

The PHS series is the input for forecasting in later weeks, but it already gives a clear picture of the current position. Scotland-wide, all specialties:

| Month | Patient type | Waiting | Over 12 weeks | Share over 12 weeks | Median wait (days) |
| --- | --- | --- | --- | --- | --- |
| April 2026 | Inpatient/Day case | 157,169 | 96,441 | 61.4% | 128 |
| May 2026 | Inpatient/Day case | 157,293 | 98,829 | 62.8% | 125 |
| June 2026 | Inpatient/Day case | 157,191 | 98,657 | 62.8% | 130 |
| April 2026 | New Outpatient | 489,120 | 248,666 | 50.8% | 86 |
| May 2026 | New Outpatient | 495,813 | 254,254 | 51.3% | 88 |
| June 2026 | New Outpatient | 496,349 | 251,503 | 50.7% | 89 |

What it shows:

- **About 653,000 waits were ongoing in June 2026:** 157,191 for inpatient or day-case treatment and 496,349 for a first outpatient appointment.
- **Most inpatient waits are past the 12-week mark.** 62.8% of inpatient and day-case waits were over 12 weeks, the Treatment Time Guarantee set out in the Patient Rights (Scotland) Act. Just over half of outpatient waits (50.7%) were over the 12-week standard.
- **The typical wait is long.** The median ongoing inpatient wait was 130 days (about 19 weeks); for outpatients, 89 days (about 13 weeks).
- **The three months shown are stable.** Totals moved by under 2%, so there is no sign of a sudden change in this short window.

How to read it:

- These are counts of people still waiting at the end of each month (ongoing waits), as published by PHS. The pipeline types and checks them but does not change them.
- Three months show a level, not a trend. The full series runs back to October 2012 (165 months, 330 Scotland-level rows), which is what the forecasting work will use.
- The data links the two halves of the project: the knowledge base explains the rules (the 12-week guarantee and standard), and this table shows how the system is doing against them.

## 10. Results at a glance

### 10.1 Databricks objects (dev environment)

| Object | Name | Contents |
| --- | --- | --- |
| Schema | `workspace.careconnect_dev` | All tables below |
| Volume | `landing` | 37 source files |
| Table | `bronze_documents` | 28 documents with metadata and hash |
| Table | `silver_chunks` | 353 chunks, change feed on |
| Table | `ops_pii_quarantine` | 0 documents |
| Table | `bronze_phs_ongoing_waits` | 145,789 raw rows |
| Table | `silver_phs_ongoing_waits` | 145,789 clean rows |
| Table | `ops_phs_rejects` | 0 rows |
| Table | `ops_dq_results` | 11 check results per run |
| AI Search endpoint | `careconnect-search` | Standard, 1 search unit |
| AI Search index | `silver_chunks_index` | 353 rows, managed embeddings |
| Job | `[dev dmishra27] careconnect-ingest-dev` | `ingest` → `sync_index`, daily 06:00 (paused) |
| Job | `[dev dmishra27] careconnect-phs-dev` | Monthly on the 5th, 07:00 (paused) |
| MLflow experiment | `careconnect-dev` | 9 evaluation runs with per-question tables (6 on 9 October, 3 re-runs on 10 October) |

### 10.2 Code and tests

| Item | Value |
| --- | --- |
| Python source | 2,147 lines across 4 packages: `ingest`, `search`, `evals`, `phs` |
| Tests | 82 unit tests plus 2 integration tests (up from 3 in Week 1) |
| Commits | 36 in pull request #2 (73 files changed), plus the clean-up pull request |
| Decision records | 4 |

## 11. Tech stack

### 11.1 On the laptop

| Tool | Version | Role |
| --- | --- | --- |
| Windows, PowerShell | | Operating system and terminal |
| VS Code with the Databricks extension | | Editor, connected to the dev target |
| Git and GitHub | | Version control, branches and pull requests |
| uv | | Python versions, virtual environment and dependencies |
| Python | 3.12.10 | Same version as Databricks serverless |
| Databricks CLI | 1.19 | Sign-in, file copies, bundle deploy and job runs |
| Ruff | 0.16.10 | Lint and format |
| pre-commit | 4.6.2 | Runs checks on every commit |
| pytest | 8.3.5 | Unit and integration tests |
| hatchling | | Builds the project's Python package (wheel) |

### 11.2 Python libraries

| Library | Version | Used for |
| --- | --- | --- |
| databricks-sdk | 0.148.0 | Files API, AI Search endpoints and indexes, serving endpoints, jobs |
| databricks-connect | 18.0.9 | Running Spark from the laptop on serverless compute |
| mlflow | 3.8.1 | Experiment tracking, evaluation runs and tables, tracing |
| pypdf | 6.20.0 | Extracting text from policy PDFs |
| pandas | 2.2.3 | PHS transforms and data-quality checks |
| numpy | 2.1.3 | Similarity scores in the chunk-size evaluation |
| pydantic | 2.10.6 | Validated project configuration |
| PyYAML | 6.0.3 | Config, leaflet headers and evaluation questions |
| openai, databricks-openai | 2.14.0, 0.6.1 | Calling Databricks-hosted LLMs (from Week 1) |
| sentence-transformers | | Local embedding model for the chunk-size evaluation only (`BAAI/bge-base-en-v1.5`) |

### 11.3 Databricks platform

| Service | Role in the project |
| --- | --- |
| Databricks Free Edition | Workspace; serverless compute only |
| Unity Catalog | Governs the catalog `workspace`, schemas, tables and Volume |
| Volumes | Landing area for raw files |
| Delta Lake with Change Data Feed | Table storage; the change feed keeps the index in sync |
| Lakeflow Jobs on serverless (environment 5) | Runs the ingest and PHS pipelines |
| Declarative Automation Bundles | Defines schemas, Volume and jobs as code; deploys dev and prod |
| AI Search (formerly Vector Search) | Endpoint and Delta Sync index for retrieval |
| Foundation Model APIs | `databricks-gte-large-en` embeddings; Llama 3.3 70B and 3.1 8B for later weeks |
| MLflow on Databricks | Experiment `careconnect-dev` with evaluation runs |
| SQL editor | Spot-checking tables |

## 12. Concepts learned this week, in plain language

| Concept | Plain explanation |
| --- | --- |
| Chunking | Cutting documents into passages small enough to search precisely and to fit into an LLM prompt |
| Overlap | Repeating the end of one chunk at the start of the next, so ideas split at a boundary aren't lost |
| Heading-aware chunking | Never mixing two sections in one chunk, and labelling each chunk with its section |
| Embedding | A list of numbers that captures what a passage means; similar meanings give similar numbers |
| Vector search (ANN) | Finding the passages whose embeddings are closest to the question's embedding |
| Full-text search | Classic keyword matching |
| Hybrid search | Combining both result lists (here with Reciprocal Rank Fusion) |
| Delta Sync index | A search index that follows a Delta table automatically through its change feed |
| Recall@k and MRR | How often the right passage is found in the top k, and how near the top it usually is |
| Medallion layers | Bronze (raw), silver (clean), gold (purpose-built) data stages |
| Data-quality expectations | Automatic rules that remove bad rows or raise warnings, with results recorded every run |
| Incremental load | Processing only what changed, detected with file fingerprints (hashes) |
| PII quarantine | Keeping documents with personal identifiers out of the knowledge base entirely |
| Infrastructure as code | Workspace objects defined in files, reviewed and deployed like code |

## 13. Decisions made and recorded

All decisions are in `docs/decisions/` in the repository.

| Decision | Choice | Why |
| --- | --- | --- |
| Workspace layout | One schema per environment; bronze, silver and gold as table prefixes; no dev prefix on schema names | Simple, within Free Edition limits, names match the config |
| Search method | ANN by default; hybrid kept as an option | MRR 0.828 against 0.682 on the evaluation |
| Chunk size | Keep 400 tokens with 60 overlap | Same accuracy as 800/120 for about 30% less text per answer |
| PHS download | From the laptop; the job loads from the Volume | Free Edition serverless compute has no internet access |
| MLflow trace storage | Experiment storage now; Unity Catalog storage for the agent | Unity Catalog storage can only be chosen when an experiment is created |

## 14. Problems met and how they were fixed

| Problem | Cause | Fix | Lesson |
| --- | --- | --- | --- |
| `databricks.yml` seemed missing | The terminal was looking in the wrong place | Confirmed the file at the root and pasted its contents | Check the current folder first |
| Dev and prod schema names swapped in `project_config.yml` | Editing slip | Replaced the whole file with a corrected version | Paste full files for config changes |
| Tests still used the old template setup | The new `conftest.py` was never saved | Wrote the file from PowerShell | Save before running |
| Commits stopped by pre-commit hooks | `end-of-file-fixer` added missing final newlines | `git add` again and commit | A stopped commit is a fix to re-stage |
| A personal-data test used an invalid NI number | `QQ` is not a valid prefix | Used `AB 12 34 56 C` | Test data must be valid to be meaningful |
| Zip files of new code never reached the laptop | File delivery from the session failed | Code pushed to a GitHub branch and merged locally | Git is the reliable channel |
| First push from the session was refused | GitHub App not installed for the repo | Installed the app | Grant access once, then pushes work |
| Chunks over the 400-token budget, and some 1-token PDF chunks | Token counts summed per piece; tiny fragments between headings | Measure the whole chunk; trim overlap; merge fragments under 4 words | Test limits on real documents |
| Every PDF chunk said page 1 | The page came from the section start | Inline page markers; chunk page = page of its first sentence | Citations need fine-grained metadata |
| Contents-page lines became section headings | Lines such as "Appendix 3 ... 46" looked like headings | Drop dot-leader contents lines | PDFs need cleaning rules for structure, not just text |
| Wrapped sentences became headings | A numbered line wrapping onto the next line looked like a heading | Reject a heading followed by a lowercase line | Look at what the parser produced, not only the counts |
| A pushed fix had an indentation error | The lint failure didn't stop the push command | Fixed and re-pushed within minutes | Chain commands so a failure stops them |
| Search index took about 24 minutes the first time | A new endpoint must provision its machine | Waited; re-runs now wait instead of re-syncing | First builds are slow; refreshes are fast |
| Embedding model refused direct calls | Free Edition rate limit | Cached, paced calls; chunk comparison run with a local model | Design evaluations for platform limits |
| Browser login said "not a member of this account" | Signed in with a different email from the workspace owner | Signed in with the workspace email in a private window | The workspace belongs to one email |
| A PHS lookup file failed to read | It was Windows-1252, not UTF-8 | Fall back to Windows-1252; normalise non-breaking spaces | Public data comes in mixed encodings |
| 5,401 rows had board codes with no name | Two extra PHS lookups were needed | Added the ISD and residential-category lookups; warning now 0 | Data-quality warnings point to the fix |
| PHS job could not reach the internet | Free Edition serverless has no outbound access | Download on the laptop; job loads from the Volume | Know the platform's network limits |
| Long "table not found" message on the first PHS load | The client logged a handled error | Check that the table exists first | Clean logs make real errors visible |
| Contents entries without dot leaders and a "DRAFT" watermark became tiny chunks (found while checking the report in Databricks) | Lines such as "4.1 Communication with Patients 7" looked like numbered headings | Drop numbered lines that end in a page number, and stand-alone watermarks | Checking the output against the source finds what tests miss |
| PHS download stopped with "Remote end closed connection" | Temporary fault on the open-data portal | Downloads retry up to 4 times with increasing waits | External sources fail; retry before failing |

## 15. Key takeaways

- **Measure before you trust.** The search setting that sounded best (hybrid) lost clearly once it was measured. A small labelled question set changed a design decision.
- **Clean input decides output quality.** Most of the effort went into cleaning PDFs: headers, page numbers, contents pages and wrapped headings. Every fix improved the chunks the search engine sees.
- **Safety first with healthcare data.** Synthetic and public data only, and an automatic personal-data scan that quarantines documents before they can be indexed.
- **Data quality should be visible.** The PHS checks are stored every run, so quality can be tracked and questioned, not assumed.
- **Pipelines should be safe to re-run.** File fingerprints make both pipelines skip unchanged data, so scheduled jobs are cheap and predictable.
- **Free Edition has real limits, and they shaped the design.** One search endpoint, rate-limited embeddings and no internet from jobs. Each limit has a recorded workaround.
- **Decisions belong in writing.** Four short decision records explain why things are the way they are.

## 16. Final state of the project

```text
careconnect-navigator/
├── databricks.yml                # bundle, dev and prod targets
├── resources/
│   ├── schemas.yml               # schema and landing Volume
│   ├── ingest_job.job.yml        # ingest -> sync_index
│   └── phs_job.job.yml           # PHS waiting times
├── src/careconnect/
│   ├── config.py                 # ProjectConfig
│   ├── ingest/                   # parsing, PII scan, chunking, Delta writes
│   ├── search/                   # AI Search index and retriever
│   ├── evals/                    # retrieval evaluation
│   └── phs/                      # PHS download, transform, data-quality checks
├── data/
│   ├── raw/                      # leaflets, policy manifest, clinics, PHS notes
│   └── eval/retrieval_questions.yml
├── docs/
│   ├── week2.md
│   └── decisions/                # 4 decision records
├── scripts/                      # hello_llm.py, check_connect.py, check_ingest.py
├── notebooks/00_hello.py
├── tests/                        # 82 unit tests, 2 integration tests
├── project_config.yml
└── pyproject.toml                # dependencies, entry points: ingest, phs, build-index
```

| Command | What it does |
| --- | --- |
| `uv run pytest -m "not integration"` | Runs the unit tests |
| `uv run ingest --env dev` | Ingests documents into the tables |
| `uv run build-index --env dev` | Creates or refreshes the search index |
| `uv run python -m careconnect.search.retriever "question"` | Searches the knowledge base |
| `uv run python -m careconnect.evals.retrieval --env dev` | Runs the retrieval evaluation |
| `uv run phs --env dev --download` | Monthly: fetch PHS data and load it |
| `databricks bundle deploy -t dev` | Deploys the bundle |
| `databricks bundle run ingest_job -t dev` | Runs ingest and index refresh on serverless |

## 17. Open items carried into Week 3

The Week 3 course topic is MCP, tool calling and agent orchestration. Its work builds directly on Week 2:

- [ ] Generate answers with citations on top of the retriever (chunk, section and page).
- [ ] Evaluate answer quality with an LLM judge (faithfulness and relevance), alongside the retrieval scores.
- [ ] Add questions with exact terms (CHI, HC2, clinic names) and re-test hybrid search.
- [ ] Build a gold waiting-times table and a first forecasting model on the Scotland series.
- [ ] Create the agent's MLflow experiment with traces stored in Unity Catalog.
- [ ] Each month, after PHS publishes: run `uv run phs --env dev --download`.

## Sources

- LLMOps with Databricks course page: https://maven.com/cauchy/llmops-with-databricks
- Databricks Free Edition limitations: https://docs.databricks.com/aws/en/getting-started/free-edition-limitations
- Create and query an AI Search index: https://docs.databricks.com/aws/generative-ai/create-query-vector-search
- Query an AI Search index: https://docs.databricks.com/aws/en/ai-search/query-ai-search
- Store MLflow traces in Unity Catalog: https://docs.databricks.com/aws/en/mlflow3/genai/tracing/trace-unity-catalog
- PHS Stage of Treatment Waiting Times: https://www.opendata.nhs.scot/dataset/stage-of-treatment-waiting-times
- PHS Geography Codes and Labels: https://www.opendata.nhs.scot/dataset/geography-codes-and-labels
- Charter of Patient Rights and Responsibilities: https://www.gov.scot/publications/charter-patient-rights-responsibilities-revised-june-2022/documents/
- NHSScotland Waiting Times Guidance: https://www.gov.scot/publications/nhsscotland-waiting-times-guidance-november-2023/documents/
- Patient Rights (Scotland) Act 2011: https://www.legislation.gov.uk/asp/2011/5/contents/enacted
- NHS Scotland Model Complaints Handling Procedure: https://www.spso.org.uk
