# Public Health Scotland waiting-times data

Downloaded by `uv run phs --env dev --download` (CSV files here are gitignored).
All files: Public Health Scotland, opendata.nhs.scot, UK Open Government Licence v3.0.

| File | Source |
|------|--------|
| `ongoing_waits.csv` | Stage of Treatment Waiting Times: Ongoing Waits - Long Trend (resource `5816ec92-66bf-4033-ae55-9df45ff19d49`, via the datastore dump) |
| `hb14_hb19.csv` | Geography Codes and Labels: Health Board 2014 - Health Board 2019 |
| `special_health_boards.csv` | Special Health Boards and National Facilities |
| `isd_health_board_of_treatment.csv` | ISD Health Board of Treatment (S27 codes, e.g. non-NHS providers) |
| `other_residential_categories.csv` | Other Residential Categories (RA27 codes) |
| `specialty_codes.csv` | Specialty Codes |
| `statistical_qualifiers.csv` | Statistical Qualifiers (meaning of the `*QF` columns) |

These are aggregate statistics (counts and wait percentiles by month, health board,
patient type and specialty). They contain no patient-level data.

## Known gaps in the lookups

- Specialty blank (`""`): NHS Greater Glasgow & Clyde patients under more than one
  specialty (PHS code `XSU`) are published with a blank specialty, as the PHS data
  dictionary explains. They are kept and pass the `known_specialty` check.
- Specialty `H3`: not in the current PHS specialty lookup (about 10 rows in the long
  trend), most likely a retired code. Kept, flagged by the `known_specialty` warning.
