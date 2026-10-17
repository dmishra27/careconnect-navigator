# The system prompt in the Prompt Registry, promoted only through an evaluation gate

- Date: 2026-10-17
- Status: proposed (accepted once version 1 is registered as production and a candidate has
  been through the gate on Databricks)

## Context

Until Week 3 the agent's system prompt was a Python string in `src/careconnect/agent/prompts.py`.
Changing it meant a code change and a redeploy, and nothing recorded which wording produced a
given answer except the commit history. Week 3 showed how sensitive the agent is to wording:
fixing 3 failing questions by adding rules broke 3 others (round 1, 15 October), and only a
second round reached 28 of 28 in three runs.

MLflow 3.12 on serverless environment 6 offers the Prompt Registry in Unity Catalog
(`mlflow.genai.register_prompt`, `load_prompt`, `set_prompt_alias`), checked by
`scripts/check_week4.py` on 16 October.

## Decision

- The prompt is registered as `<catalog>.<schema>.careconnect_agent_prompt`. Each wording is a
  numbered, immutable version, tagged with its 12-character hash, its source and the Git commit.
  Registering identical wording again returns the existing version.
- The agent loads the version behind the alias **`production`**. If the registry cannot be
  reached it uses the copy in `prompts.py` and says so; answers never stop because of the
  registry. A version asked for explicitly (`--prompt 2`, and every promotion run) must load,
  or the command fails: a promotion must never compare against the fallback.
- `production` can be set directly only once, for the first version. After that it moves only
  through `prompt_registry promote --candidate N`, which runs the 28-question evaluation 3
  times with production and 3 times with the candidate (same backend, same questions) and
  promotes only if:
  - the candidate's worst pass rate and urgent recall are at least production's worst;
  - its worst false-alarm and violation rates are no higher than production's worst;
  - every candidate run catches every urgent case.

  It prints one line per check, so a refusal says why. The replaced version keeps the alias
  **`previous`**, so `rollback` is one command.
- Every trace is tagged with `prompt_version` (a number, or `code` for the fallback) and
  `prompt_source`, alongside the Step 1 `prompt_hash`. Traces from before the registry show
  as version `code` in `trace_report`'s prompts table.

## Why worst run against worst run

The evaluation is deterministic (temperature 0, rule-based checks), but tool latency and
model serving still vary, and Week 3 saw one run differ from the others. Comparing worst
runs means one lucky candidate run cannot win, and one unlucky production run does not set
an easy bar. Three runs each is the same rule used to close Week 3.

## Consequences

- A prompt change is now data, not a deployment: register, promote, and every later answer
  and trace carries the version.
- `prompts.py` stays the place where wording is written and reviewed in a pull request. After
  a promotion, `prompts.py` on `main` should match production (`prompt_registry show` reports
  whether it does), so the fallback is the production wording.
- A promotion costs 6 evaluation runs (about 15 to 20 minutes and 6 x 28 agent calls).
- The gate uses the rule-based checks only. Step 3 adds LLM judges (correctness, groundedness,
  safety); when they are stable they can join the gate.
