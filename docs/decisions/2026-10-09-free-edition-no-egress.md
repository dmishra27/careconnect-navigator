# PHS files are downloaded from the laptop, not by the job

- Date: 2026-10-09
- Status: accepted

## Context

The PHS waiting-times job was first written to download the latest files from
opendata.nhs.scot itself. On Databricks Free Edition the run failed at the first request
with `URLError: [Errno -3] Temporary failure in name resolution`: serverless compute
has no outbound internet access.

## Decision

- Download on the laptop: `uv run phs --env dev --download` fetches the PHS files and
  uploads them to `/Volumes/<catalog>/<schema>/landing/phs/`.
- The bundle job `phs_job` loads from the Volume only. It skips the load when the source
  file hash is unchanged, so it is safe to run on its monthly schedule.
- If `--download` is used inside Databricks anyway, a failed download is a warning and
  the run continues with the files already in the Volume.

## Consequences

- One manual step a month (PHS publishes monthly). Acceptable for a portfolio project.
- On a paid workspace with internet access, add `--download` back to the job parameters;
  no code change is needed.
- The same restriction applies to anything else that needs the public internet from a job
  (for example the policy PDFs), so those are also fetched locally and uploaded.
