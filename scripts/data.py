"""Load the case data once, with analysis decisions applied as flags.

Reads the raw files in datasets/ (never work_files/ or output/) and reuses
the parsing from clean_excels.py, so every number in the dashboard traces
back to the original data.
"""

from pathlib import Path

import pandas as pd

from clean_excels import INPUT_DIR, clean, read_raw

ROOT = Path(__file__).resolve().parent.parent

# Tickets T091-T095 are re-entered copies of these originals (same user, date, text).
DUPLICATE_TICKETS = {"T091": "T024", "T092": "T038", "T093": "T036", "T094": "T040", "T095": "T043"}

# Keyword themes for survey free text. First match wins, so order matters.
THEMES = {
    "No complaints": ["nothing major", "none", "no complaints"],
    "Crash / bugs": ["crash", "bug", "broke", "error", "unusable", "can't complete", "terrible"],
    "Performance": ["slow", "perform", "faster", "forever"],
    "Learning / docs": ["learn", "tutorial", "training", "example", "documentation",
                        "confus", "guide", "practice", "shortcut", "navigation"],
}


def theme(text) -> str:
    if not isinstance(text, str):
        return "No answer"
    text = text.lower()
    for name, words in THEMES.items():
        if any(w in text for w in words):
            return name
    return "Other"


def load() -> dict[str, pd.DataFrame]:
    usage = clean(read_raw(INPUT_DIR / "dmd_usage_data.xlsx"))
    tickets = clean(read_raw(INPUT_DIR / "support_tickets.xlsx"))
    survey = clean(read_raw(INPUT_DIR / "user_survey_responses.xlsx"))

    # --- usage: flag the implausible 520 errors (user's other months are 3-13) ---
    usage["error_count_raw"] = usage["error_count"]
    usage["suspect_errors"] = usage["error_count"] > 100
    usage.loc[usage["suspect_errors"], "error_count"] = pd.NA
    usage["errors_per_session"] = usage["error_count"] / usage["sessions_count"]

    # --- tickets: flag duplicates, parse dates ---
    tickets["ticket_date"] = pd.to_datetime(tickets["ticket_date"])
    tickets["duplicate_of"] = tickets["ticket_id"].map(DUPLICATE_TICKETS)
    tickets["is_duplicate"] = tickets["duplicate_of"].notna()
    tickets["is_open"] = tickets["status"].isin(["Open", "In Progress"])

    # --- survey: mark each user's latest response, tag frustration themes ---
    survey["survey_date"] = pd.to_datetime(survey["survey_date"])
    survey = survey.sort_values(["user_id", "survey_date", "response_id"])
    survey["is_latest"] = ~survey.duplicated("user_id", keep="last")
    survey["frustration_theme"] = survey["primary_frustration"].map(theme)

    users = build_users(usage, tickets, survey)
    return {"usage": usage, "tickets": tickets, "survey": survey, "users": users}


def build_users(usage, tickets, survey) -> pd.DataFrame:
    """One row per user for the CRM list."""
    months = sorted(usage["month"].unique())
    first, last = months[0], months[-1]
    by_user = usage.groupby("user_id")

    users = by_user.agg(
        user_role=("user_role", "first"),
        dept_code=("dept_code", "first"),
        total_sessions=("sessions_count", "sum"),
        total_errors=("error_count", "sum"),
    )
    start = usage[usage["month"] == first].set_index("user_id")
    end = usage[usage["month"] == last].set_index("user_id")
    users["sessions_first_month"] = start["sessions_count"]
    users["sessions_last_month"] = end["sessions_count"]
    users["session_change_pct"] = (
        (users["sessions_last_month"] / users["sessions_first_month"] - 1) * 100
    ).round(0).astype("Int64")
    users["errors_first_month"] = start["error_count"]
    users["errors_last_month"] = end["error_count"]

    real = tickets[~tickets["is_duplicate"]]
    users["tickets"] = real.groupby("user_id").size()
    users["open_tickets"] = real[real["is_open"]].groupby("user_id").size()

    latest = survey[survey["is_latest"]].set_index("user_id")
    users["satisfaction"] = latest["satisfaction_score"]
    users["would_recommend"] = latest["would_recommend"]
    users["survey_responses"] = survey.groupby("user_id").size()

    count_cols = ["tickets", "open_tickets", "survey_responses"]
    users[count_cols] = users[count_cols].fillna(0).astype(int)

    # Simple, explainable risk flag: unhappy AND (losing usage OR waiting on tickets).
    users["at_risk"] = (users["satisfaction"] <= 2) & (
        (users["session_change_pct"] <= -20) | (users["open_tickets"] > 0)
    )
    return users.reset_index()


if __name__ == "__main__":
    d = load()
    for name, df in d.items():
        print(name, df.shape)
    print(d["users"].to_string())
