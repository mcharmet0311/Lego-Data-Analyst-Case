# Digital Model Designer · Usage Insights

A data analysis case from LEGO: how are designers using the LEGO Digital Design tool, what is frustrating
them, and what should the product team focus on next?

The repo contains a local **Dash dashboard** with drill-down into individual designers, a generated
**PDF summary** of the findings, and the Python scripts behind both. All data in this repo is
**simulated** and was provided with the case.

![Python](https://img.shields.io/badge/python-3.15-blue) ![uv](https://img.shields.io/badge/managed%20with-uv-purple)

## Key findings

- **v2.3 is where it breaks.** Errors per session tripled from v2.1 to v2.3 (0.16 → 0.51), and 53 of 90
  unique support tickets were raised on v2.3.
- **Power users are leaving.** They account for 63% of all sessions, but their sessions fell 27% and all 8
  would not recommend the tool. None of the 45 v2.3 bug, performance or feature tickets has been resolved.
- **New users are thriving, occasional users are quietly fading.** New users' sessions grew 4.5× with
  4.5/5 satisfaction. Occasional users dropped 53% and have the highest v2.3 error rate, yet raise few
  tickets.

**Recommendation:** stabilise v2.3 before building new features.
The full write-up, including questions for the PM, data quality issues and the biggest risk, is in
[`reports/findings_summary.pdf`](reports/findings_summary.pdf).

## Run it

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync                                   # create .venv with the pinned packages
uv run python scripts/dashboard.py        # dashboard at http://127.0.0.1:8050 (local only)
uv run python scripts/make_report.py      # rebuild reports/findings_summary.pdf
```

The dashboard's **Summary report (PDF)** button rebuilds the PDF on demand. The answers to the case
questions are stored in [`answers.json`](answers.json), and both the dashboard and the PDF read them from
there.

## What's in the dashboard

- Headline numbers: satisfaction, errors per session, open tickets and designers at risk
- Trend charts by user role, with the months each tool version was live shaded
- The answers to the case questions (Q1–Q5), each next to the question it answers
- A sortable designer list. Clicking a designer opens their support tickets and survey answers.
- A role filter that updates everything

## Repository layout

| Path | Contents |
|---|---|
| `datasets/` | Raw case data, unchanged (usage logs, support tickets, survey) |
| `work_files/` | Cleaned copies used for manual review, with data issues highlighted |
| `scripts/clean_excels.py` | Turns the raw files into clean, readable Excel files |
| `scripts/data.py` | Loads the data and applies the analysis decisions as flags |
| `scripts/dashboard.py` | The Dash app |
| `scripts/assets/style.css` | Dashboard styling |
| `scripts/make_report.py` | Builds the PDF summary |
| `answers.json` | Answers to the case questions |
| `reports/findings_summary.pdf` | Generated summary of findings |

## How the data was handled

- The raw Excel files store each row as one comma-separated text cell; these are split into columns.
- Inconsistent capitalisation is normalised (`power user` → `Power User`). Four US-style dates are read
  month-first, which neighbouring rows confirm.
- **Flagged, not deleted:** 5 duplicate support tickets (T091–T095) and one implausible error count (520
  errors in a month where the designer otherwise logs 3–13) are excluded from all counts but stay
  visible in the dashboard.
- Survey averages use each designer's latest response, because some designers answered two or three
  times.
- No missing values are filled in.

## Disclaimer

The case and its data were provided by LEGO. The data is simulated and does not describe real users or
real usage. The analysis and conclusions are my own and are not an official LEGO publication. LEGO and
the LEGO logo are trademarks of the LEGO Group.
