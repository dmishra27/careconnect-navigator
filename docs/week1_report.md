# Week 1 Complete Report: Introduction to LLMOps and Developing AI Applications on Databricks

**Project:** CareConnect Navigator (healthcare MLOps and LLMOps portfolio project)
**Course schedule window:** 12 to 18 October 2026, followed self-paced without enrolling
**Work completed:** Day 1 on 7 October 2026 (core setup), Day 2 on 8 October 2026 (gap closure)
**Environment:** Windows laptop (PowerShell, uv, VS Code) connected to Databricks Free Edition
**Repository:** https://github.com/dmishra27/careconnect-navigator (branch `main`, pull request #1 merged)

## 1. Summary

Every Week 1 objective is met. Day 1 delivered a working laptop-to-Databricks setup: authentication, a uv project, a traced LLM call, and a bundle that deploys and runs a job. A comparison with how the tutors ran Week 1 of their MLOps course then showed five gaps: project configuration, code-quality tooling, Databricks Connect, the VS Code extension, and notebooks stored as `.py` files. Day 2 closed all five on a feature branch, re-verified the whole chain, and merged it to `main` through a pull request.

## 2. Week 1 in the course schedule

| Date | Session | Length |
| --- | --- | --- |
| Mon 12 Oct, 15:00 to 16:00 | Course kick-off | 1 hour |
| Wed 14 Oct, 15:00 to 17:00 | Introduction to LLMOps and developing AI applications on Databricks | 2 hours |

The course page lists session titles only ("No module content yet") and no Week 1 assignment. The objectives below are inferred from the session titles, the original syllabus assignment ("Get started with developing on Databricks"), and the tutors' published approach to developing on Databricks in their MLOps course.

## 3. Objectives and final status

### 3.1 Core objectives (Day 1)

| Objective | Evidence | Status |
| --- | --- | --- |
| Understand what LLMOps adds to MLOps | Concepts summarised in section 4 | Done |
| Databricks workspace at no cost | Free Edition account and workspace URL | Done |
| Laptop authenticated to the workspace | `databricks current-user me` returns the user | Done |
| uv project pinned to the serverless Python version | Python 3.12, `requires-python = "==3.12.*"` | Done |
| First LLM call from the laptop, traced in MLflow | Trace in the `careconnect-dev` experiment | Done |
| A bundle validates, deploys and runs a job on serverless | `sample_job` ends `TERMINATED SUCCESS` | Done |
| Project under Git and on GitHub | Public repository, branch `main` | Done |

### 3.2 Gap objectives (Day 2)

| Gap | What was done | Evidence | Status |
| --- | --- | --- | --- |
| 1. Single project layout | Bundle and package moved to the repo root; one `pyproject.toml` | `bundle deploy` builds the wheel from the root | Closed |
| 2. Project configuration | `project_config.yml` per environment, loaded by a pydantic `ProjectConfig` | `tests/test_config.py`: 2 passed | Closed |
| 3. Code-quality tooling | Ruff (lint and format) and pre-commit hooks on every commit | `pre-commit run --all-files`: all Passed | Closed |
| 4. Databricks Connect | Spark code from the laptop on serverless, aligned to serverless environment 5 | `scripts/check_connect.py` prints user and 5 rows | Closed |
| 5. VS Code extension and `.py` notebook | Extension configured (dev target, DEFAULT profile, Serverless); notebook in `.py` format | `notebooks/00_hello.py` runs both cells on serverless | Closed |
| Final verification and merge | Full test suite, bundle validate, deploy, run; pull request merged | 3 tests passed; job `TERMINATED SUCCESS`; PR #1 merged | Done |

## 4. Learnings: concepts

### 4.1 What LLMOps adds to MLOps

- LLM applications fail in new ways: hallucination, prompt drift, non-deterministic outputs, runaway token cost and unsafe answers.
- The same MLOps principles still apply: reproducibility, traceability, reliable deployment, monitoring, and managing cost, performance and safety.
- More things need versioning and evaluation: prompts, retrieval settings, tools and LLM judges, not just model weights.
- The lifecycle is a loop: develop, evaluate, deploy, monitor, then feed failures back into the evaluation set.
- Tracing every call from the first day is what makes later evaluation and monitoring possible.

### 4.2 Databricks building blocks used this week

| Component | What it is | How it was used |
| --- | --- | --- |
| Free Edition | No-cost, serverless-only workspace for personal, non-commercial use | The project's workspace |
| Databricks CLI | Command-line tool for auth, resources and bundles | Login, endpoint listing, deploy, job runs |
| Unity Catalog | Governance layer: catalog, schema, table | Catalog `workspace`, personal schema `dmishra27` |
| Foundation Model APIs | Hosted LLMs and embedding models behind OpenAI-compatible endpoints | Llama 3.3 70B called from the laptop |
| MLflow 3 tracing | Records inputs, outputs, tokens and latency for each call | Traces in `careconnect-dev` |
| Declarative Automation Bundles | Infrastructure as code for workspace resources (formerly Databricks Asset Bundles) | Wheel build, dev deployment, job run |
| Lakeflow Jobs on serverless | Workloads without managing clusters | The template's `sample_job` |
| Databricks Connect | Runs local Spark code on remote Databricks compute | `check_connect.py` and the notebook |
| Serverless environment versions | Fixed sets of Python and library versions on serverless | Local environment pinned to version 5 |
| VS Code Databricks extension | IDE integration for auth, compute, bundles and notebooks | Configured against the dev target |

### 4.3 Free Edition versus the free trial

| | Free Edition | Free trial |
| --- | --- | --- |
| Cost | Free, no expiry, daily usage limits | Up to $400 credits for 14 days, then paid |
| Payment details | None needed | Card or cloud account to continue |
| Intended use | Learning and personal, non-commercial | Business evaluation |
| Compute | Serverless only, smaller sizes | Full platform |
| Data note | Databricks may train on your data, so use only synthetic or public data | Business terms |

Sign-up link used: https://www.databricks.com/signup/free-edition?provider=DB_FREE_TIER

### 4.4 Models available in the workspace

| Role in the project | Endpoint |
| --- | --- |
| Main agent answers | `databricks-meta-llama-3-3-70b-instruct` |
| Alternative main model to evaluate | `databricks-qwen3-next-80b-a3b-instruct` |
| Cheap judges and guardrail checks | `databricks-meta-llama-3-1-8b-instruct` |
| Embeddings for the search index | `databricks-gte-large-en` |

The GPT-OSS models are reasoning models with a different output shape, so they were not used for the first tests.

## 5. Day 1 activities: core setup (7 October)

### 5.1 Workspace and CLI

```powershell
winget install Databricks.DatabricksCLI
databricks -v
databricks auth login --host https://<your-workspace>.cloud.databricks.com
databricks current-user me
```

- CLI v1.19.0 installed.
- Profile name `DEFAULT`, so the CLI, SDK, MLflow and VS Code use it without flags. The profile name is a local label, not the email.

### 5.2 Python project

```powershell
cd C:\Users\<you>\projects
uv init careconnect-navigator
cd careconnect-navigator
uv python pin 3.12
uv add "mlflow[databricks]>=3" databricks-sdk openai databricks-openai
```

### 5.3 First traced LLM call

```powershell
databricks serving-endpoints list
uv run python hello_llm.py
```

The call returned a one-sentence answer, and MLflow logged a trace with prompt, response, tokens and latency.

### 5.4 Bundle

```powershell
databricks bundle init
databricks bundle validate
databricks bundle deploy -t dev
databricks schemas create dmishra27 workspace
databricks bundle run sample_job -t dev
```

| Template prompt | Answer | Reason |
| --- | --- | --- |
| Project name | `careconnect` | Project name |
| Job that runs a notebook | no | Own jobs come later |
| ETL pipeline | no | Own ingest job comes in Week 2 |
| Sample Python package (wheel) | yes | Jobs import project code from a package |
| Serverless compute | yes | Free Edition is serverless-only |
| Default catalog | `workspace` | Built-in catalog |
| Personal schema per user | yes | Isolates dev work in `workspace.dmishra27` |

### 5.5 Version control

Git initialised, `.gitattributes` added to enforce LF line endings, branch renamed to `main`, repository pushed to GitHub, and the hard-coded email removed from the script.

## 6. Day 2 activities: gap closure (8 October)

All work was done on a branch, `week1-gaps`, and merged at the end.

```powershell
git switch -c week1-gaps
```

### 6.1 Gap 1: single project layout

The bundle template had created a `careconnect/` subfolder with its own `pyproject.toml`. Everything was moved to the root with `git mv`, so history was kept as renames.

```powershell
git mv careconnect/databricks.yml .
git mv careconnect/resources .
git mv careconnect/src .
git mv careconnect/tests .
git mv careconnect/fixtures .
git mv careconnect/.vscode .
git mv hello_llm.py scripts/hello_llm.py
```

The two `pyproject.toml` files were merged into one, with the package build settings (hatchling, `src/careconnect`), the job entry point, runtime dependencies and a `dev` dependency group.

### 6.2 Gap 2: project configuration

`project_config.yml` holds settings per environment (dev and prod): catalog, schema, experiment name and the three model endpoints. `src/careconnect/config.py` loads and validates it.

```python
class ProjectConfig(BaseModel):
    env: str
    catalog: str
    schema_name: str
    experiment_name: str
    llm_endpoint: str
    judge_endpoint: str
    embedding_endpoint: str

    @classmethod
    def from_yaml(cls, path, env="dev"): ...
```

`scripts/hello_llm.py` now reads its model and experiment name from the config. `tests/test_config.py` checks that dev loads and that an unknown environment fails.

### 6.3 Gap 3: Ruff and pre-commit

`.pre-commit-config.yaml` runs trailing-whitespace, end-of-file, YAML and large-file checks, plus `ruff-check` and `ruff-format`. Ruff settings live in `pyproject.toml` (line length 100, Python 3.12, rules E, F, I, B and UP).

```powershell
uv run pre-commit autoupdate
uv run pre-commit install
uv run pre-commit run --all-files
```

The first run fixed formatting automatically and reported four issues in template code (three long lines and one `raise ... from` rule), which were fixed by hand.

### 6.4 Gap 4: Databricks Connect

```python
from databricks.connect import DatabricksSession

spark = DatabricksSession.builder.serverless(True).getOrCreate()
spark.sql("SELECT current_user() AS me, current_catalog() AS catalog").show()
spark.read.table("samples.nyctaxi.trips").limit(5).show()
```

The VS Code extension's environment setup then aligned the project with the workspace's serverless environment version 5. It changed `databricks-connect` from `~=17.3` to `~=18.0.0`, added `[tool.databricks.environment] environment_version = "5"`, and added about 250 `[tool.uv] constraint-dependencies` pins matching the packages serverless ships. All scripts and tests were re-run afterwards.

### 6.5 Gap 5: VS Code extension and `.py` notebook

| Extension setting | Value |
| --- | --- |
| Target | dev |
| Auth type | Profile `DEFAULT` |
| Compute | Serverless |
| Python environment | `.venv` (Python 3.12.10), ready |
| Status bar | Databricks Connect enabled |

`notebooks/00_hello.py` uses the Databricks notebook format (`# Databricks notebook source` header and `# COMMAND ----------` cell markers), so Git diffs and reviews stay clean. Ruff was told about the notebook globals:

```toml
[tool.ruff]
line-length = 100
target-version = "py312"
builtins = ["spark", "dbutils", "display", "displayHTML"]
```

The notebook was run from the terminal with a serverless session passed in, and both cells returned results.

### 6.6 Final verification and merge

```powershell
uv run pytest
databricks bundle validate
databricks bundle deploy -t dev
databricks bundle run sample_job -t dev
git push
gh pr create --base main --head week1-gaps --title "Close Week 1 gaps"
gh pr merge --merge
git switch main
git pull
git branch -d week1-gaps
git push origin --delete week1-gaps
```

| Check | Result |
| --- | --- |
| `pytest` | 3 passed (config tests and the template's taxi test through Databricks Connect) |
| `bundle validate` | Validation OK |
| `bundle deploy` | Wheel built from the root, 26 files uploaded, job unchanged |
| `bundle run sample_job` | TERMINATED SUCCESS |
| Pull request | #1 merged into `main`; branch deleted |

| Commit | Content |
| --- | --- |
| `c944243` | Restructure repo, add config, Ruff and pre-commit |
| `efedbf9` | Add Databricks Connect check |
| `c346682` | Align local environment with serverless environment 5 |
| `b259858` | Add hello notebook in `.py` format; declare notebook globals for Ruff |
| `74acbbe` | Merge of pull request #1 into `main` |

## 7. Problems met and how they were fixed

### 7.1 Day 1

| Problem | Cause | Fix | Lesson |
| --- | --- | --- | --- |
| `uv add` failed building `whenever` | Python 3.14 had no ready-made Windows package, so uv tried to compile Rust | Pinned Python 3.12 | Match local Python to the serverless runtime |
| `uv python pin 3.12` refused | `requires-python` still said `>=3.14` | Edited `requires-python` first | uv enforces the declared Python range |
| `ModuleNotFoundError: httpx` | Deprecated `get_open_ai_client()` expected `httpx` | Used `DatabricksOpenAI` | Deprecation warnings usually name the fix |
| `SCHEMA_NOT_FOUND workspace.dmishra27` | Template assumes the personal schema exists | `databricks schemas create` | Define schemas in the bundle (Week 2) |
| CRLF warnings on `git add` | Windows line endings | `.gitattributes` with `* text=auto eol=lf` | Code runs on Linux in Databricks and CI |
| `Repository not found` on push | `git remote add` does not create the repo | Created the repo on GitHub first | Remote first, push second |
| Push returned `Internal Server Error` | GitHub recovering from an incident | Waited, then pushed | Check githubstatus.com; commits stay safe locally |
| Email visible in public code | Hard-coded experiment path | Built from `current_user.me()` | Keep personal data out of public repos |

### 7.2 Day 2

| Problem | Cause | Fix | Lesson |
| --- | --- | --- | --- |
| `.pre-commit-config.yaml is not a file` | `code <file>` returns at once; the file was never saved | Wrote the file from PowerShell | Save with Ctrl+S before running the next command |
| YAML error "mapping values are not allowed" | PowerShell code pasted into the YAML file | Rewrote the file with `WriteAllLines` | A PowerShell block runs in the terminal, not inside the file |
| Commands ran in the wrong folder | Shell was in `tests\` or `scripts\` | `cd ..`; removed stray files | Run every command from the project root |
| `scripts\scripts\check_connect.py` created | `code scripts\...` run from inside `scripts` | Moved the file up | Relative paths depend on the current folder |
| "ruff (legacy alias)" warning | Newer Ruff renamed the hook | `ruff` changed to `ruff-check` | Re-check hook names after `autoupdate` |
| Ruff E501 and B904 in template code | Long lines; `raise` inside `except` without `from` | Split lines; `raise ... from None` | Template code is not exempt from lint rules |
| Commits stopped with "files were modified" | `end-of-file-fixer` added missing final newlines | `git add` then commit again; VS Code "Insert Final Newline" on | Hooks fix files and expect a re-stage |
| "Invalid Python interpreter" in VS Code | Interpreter choice is stored per folder; Python 3.14 selected | Selected `.venv\Scripts\python.exe` | Open the project folder, then select the interpreter |
| Explorer showed "No Folder Opened" | Files opened one by one | File > Open Folder (or `code .`) | The extension needs the folder to find `databricks.yml` |
| Save conflict on another project's `main.py` | Stale unsaved edit restored from an earlier session | Kept the disk version; deleted an empty stray `main.py` | Check the breadcrumb before resolving conflicts |
| "Select compute" did not change | The label is not clickable | Used the gear icon, chose Serverless | Environment setup needs compute selected first |
| SSH tunnel prompt | Extension offers it by default | Skipped | Not needed with serverless and Databricks Connect |
| `pyproject.toml` rewritten by the extension | Environment setup aligned to serverless environment 5 | Reviewed the diff, kept it, removed the `.bak`, `uv sync` | Review automated changes before committing |
| `ImportError: DatabricksOpenAI` | Environment 5 pins an older `databricks-openai` | Optional import with fallback to `get_open_ai_client()` | Re-run every script after changing the environment |
| Ruff F821 "undefined name spark" | Notebook globals are injected at run time | `builtins` list in `[tool.ruff]` | Declare platform globals once, project-wide |

## 8. Key takeaways

- The laptop is the development machine and Databricks is the runtime. Databricks Connect makes that split seamless.
- Matching the local environment to the serverless environment version removes "works on my machine" problems, at the cost of sometimes older library versions.
- Configuration belongs in a validated file, not in code, so the same code runs in dev and prod.
- Pre-commit hooks enforce quality automatically; a stopped commit is a fix to review and re-stage, not a failure.
- Store notebooks as `.py` files so they diff, lint and review like normal code.
- Working on a branch and merging through a pull request keeps `main` stable and practises the flow CI will use from Week 5.
- Most issues came from folder context, editor state and version mismatches, not from Databricks itself.

## 9. Final state of the project

```text
careconnect-navigator/
├── databricks.yml
├── resources/sample_job.job.yml
├── src/careconnect/        # __init__.py, config.py, main.py, taxis.py
├── scripts/                # hello_llm.py, check_connect.py
├── notebooks/00_hello.py
├── tests/                  # conftest.py, test_config.py, sample_taxis_test.py
├── fixtures/
├── project_config.yml
├── pyproject.toml          # deps, dev group, ruff, serverless env 5 pins
├── uv.lock
├── .pre-commit-config.yaml
├── .gitattributes
├── .gitignore
└── .vscode/
```

| Item | Value |
| --- | --- |
| Python | 3.12.10 in `.venv`, managed by uv |
| Databricks Connect | 18.0, serverless environment 5 |
| Workspace | Databricks Free Edition, catalog `workspace`, schema `dmishra27` |
| MLflow experiment | `/Users/<you>/careconnect-dev` |
| Dev deployment | `/Workspace/Users/<you>/.bundle/careconnect/dev` |
| Repository | `github.com/dmishra27/careconnect-navigator`, branch `main` |

## 10. Open items carried into Week 2

- [ ] Define schemas, and later catalogs, in the bundle (`resources/schemas.yml`) instead of creating them by hand.
- [ ] Add a landing Volume for source documents.
- [ ] Remove the template's sample taxi job and test once real jobs exist.
- [ ] Gather 10 to 20 Scottish Government patient-rights and waiting-times PDFs.
- [ ] Write a first batch of about 20 synthetic Firth Valley Health Board service leaflets.
- [ ] Make the Spark session in `tests/conftest.py` lazy so non-Spark tests run faster.
- [ ] Decide whether to store MLflow traces in Unity Catalog (removes the 100,000-trace limit).
- [ ] Rerun the extension's environment setup when a newer serverless environment is released.

## Sources

- Databricks Free Edition: https://www.databricks.com/learn/free-edition
- Free Edition limitations: https://docs.databricks.com/aws/en/getting-started/free-edition-limitations
- Databricks Connect usage requirements: https://docs.databricks.com/aws/en/dev-tools/databricks-connect/requirements
- Serverless environment version 4: https://docs.databricks.com/aws/release-notes/serverless/environment-version/four
- Declarative Automation Bundles resources: https://docs.databricks.com/aws/en/dev-tools/bundles/resources
- Marvelous MLOps, developing on Databricks: https://marvelousmlops.substack.com/p/developing-on-databricks
- LLMOps with Databricks course page: https://maven.com/cauchy/llmops-with-databricks
