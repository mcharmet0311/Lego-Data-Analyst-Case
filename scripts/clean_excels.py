"""Turn the raw case Excel files into clean, readable Excel files.

The raw files store each row as one comma-separated string in column A.
This script splits them into real columns, fixes inconsistent casing,
sets proper data types, and saves formatted copies to output/.
"""

import csv
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT / "datasets"
OUTPUT_DIR = ROOT / "output"

# Text columns where the same value appears with different casing,
# e.g. "Power User" / "power user" / "POWER USER".
TITLE_CASE_COLUMNS = ["user_role", "category", "status", "would_recommend"]


def read_raw(path: Path) -> pd.DataFrame:
    """Split the one-column CSV-in-Excel layout into a proper table."""
    lines = pd.read_excel(path, header=None, dtype=str)[0].dropna()
    header, *rows = csv.reader(lines)
    return pd.DataFrame(rows, columns=header)


def clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.apply(lambda col: col.str.strip()).replace("", pd.NA)

    for col in TITLE_CASE_COLUMNS:
        if col in df:
            df[col] = df[col].str.title()

    for col in df.columns:
        if col.endswith("_date"):
            # A few dates are US-style (02/10/2026 = 10 Feb); neighbouring rows confirm month-first.
            # Written as ISO text so every viewer shows 2025-10-05, not a serial number or a time.
            dates = pd.to_datetime(df[col], format="mixed", dayfirst=False)
            df[col] = dates.dt.strftime("%Y-%m-%d")
        else:
            # Turn numeric-looking columns into numbers; leave text as-is.
            numbers = pd.to_numeric(df[col], errors="coerce")
            if numbers.notna().sum() == df[col].notna().sum():
                df[col] = numbers.astype("Int64")

    return df


def save_readable(df: pd.DataFrame, path: Path) -> None:
    """Write to Excel with a frozen header, filters and fitted column widths."""
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="data")
        sheet = writer.sheets["data"]
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for col_cells in sheet.columns:
            width = max(len(str(c.value)) if c.value is not None else 0 for c in col_cells)
            sheet.column_dimensions[col_cells[0].column_letter].width = min(width + 2, 60)


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.xlsx")):
        df = clean(read_raw(path))
        out = OUTPUT_DIR / path.name
        save_readable(df, out)
        print(f"{path.name}: {len(df)} rows, {len(df.columns)} columns -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
