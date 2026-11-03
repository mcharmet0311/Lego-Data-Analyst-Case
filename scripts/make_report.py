"""Build the findings summary PDF from the data and answers.json.

Run:  uv run python scripts/make_report.py   ->  reports/findings_summary.pdf
The dashboard also rebuilds it on demand at /summary.pdf, so it always matches the saved answers.
"""

import json
import re
import tempfile
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no GUI; safe inside the web server
import matplotlib.pyplot as plt  # noqa: E402
from fpdf import FPDF  # noqa: E402

from data import ROOT, load  # noqa: E402

REPORT_FILE = ROOT / "reports" / "findings_summary.pdf"
ANSWERS_FILE = ROOT / "answers.json"
FONT_DIR = Path(matplotlib.get_data_path()) / "fonts" / "ttf"  # DejaVu ships with matplotlib

RED, YELLOW, BLUE, GREEN, BLACK, GREY = "#E3000B", "#FFD500", "#006CB7", "#00852B", "#1B1B1B", "#F3F3F3"
ROLES = ["Power User", "Occasional User", "New User"]
ROLE_COLORS = {"Power User": RED, "Occasional User": YELLOW, "New User": BLUE}
CATEGORY_COLORS = {"Bug": RED, "Performance": YELLOW, "Question": BLUE, "Feature Request": "#A0A0A0"}


def rgb(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


# ---------------------------------------------------------------- numbers

def headline(d) -> dict:
    usage, tickets, users = d["usage"], d["tickets"], d["users"]
    real = tickets[~tickets["is_duplicate"]]
    open_t = real[real["is_open"]]
    eps = usage.groupby("tool_version")["errors_per_session"].mean()
    return {
        "satisfaction": f"{users['satisfaction'].mean():.1f} / 5",
        "not_recommend": f"{(users['would_recommend'] == 'No').sum()} of {len(users)} would not recommend",
        "eps": f"{eps.iloc[-1]:.2f}",
        "eps_sub": f"{eps.iloc[-1] / eps.iloc[0]:.1f}× as many as {eps.index[0]} ({eps.iloc[0]:.2f})",
        "eps_label": f"Errors per session, {eps.index[-1]}",
        "open": f"{len(open_t)}",
        "open_sub": f"{(open_t['tool_version'] == eps.index[-1]).sum()} of them on {eps.index[-1]}",
        "risk": f"{int(users['at_risk'].sum())} of {len(users)}",
    }


# ---------------------------------------------------------------- charts

def style_axes(ax, title: str, ylabel: str) -> None:
    ax.set_title(title, loc="left", fontsize=11, fontweight="bold", color=BLACK)
    ax.set_ylabel(ylabel, fontsize=9)
    ax.tick_params(labelsize=8)
    ax.grid(axis="y", color="#E6E6E6", linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.set_ylim(0, ax.get_ylim()[1] * 1.18)  # headroom so version labels don't touch the data


def version_bands(ax, usage, months) -> None:
    spans = usage.groupby("tool_version")["month"].agg(["min", "max"])
    for i, (version, row) in enumerate(spans.iterrows()):
        x0, x1 = months.index(row["min"]) - 0.5, months.index(row["max"]) + 0.5
        ax.axvspan(x0, x1, color=["#FAFAFA", "#FFF8D6", "#FDE8E9"][i % 3], zorder=0, linewidth=0)
        ax.text(x0 + 0.08, 0.97, version, transform=ax.get_xaxis_transform(), fontsize=8,
                fontweight="bold", color="#555", va="top")


def month_labels(months) -> list[str]:
    return [date.fromisoformat(m + "-01").strftime("%b\n%Y") for m in months]


def trend_chart(d, path: Path) -> None:
    usage = d["usage"]
    months = sorted(usage["month"].unique())
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
    for ax, value, how, title, ylabel in [
        (axes[0], "sessions_count", "sum", "Sessions per month", "Sessions"),
        (axes[1], "errors_per_session", "mean", "Errors per session", "Errors / session"),
    ]:
        version_bands(ax, usage, months)
        for role in ROLES:
            series = usage[usage["user_role"] == role].groupby("month")[value].agg(how).reindex(months)
            ax.plot(range(len(months)), series.astype(float), color=ROLE_COLORS[role], linewidth=2.5,
                    marker="o", markersize=6, markeredgecolor=BLACK, markeredgewidth=0.8, label=role)
        ax.set_xticks(range(len(months)), month_labels(months))
        style_axes(ax, title, ylabel)
    axes[0].legend(frameon=False, fontsize=8, ncols=3, loc="upper left", bbox_to_anchor=(0, -0.2))
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def tickets_chart(d, path: Path) -> None:
    t = d["tickets"]
    t = t[~t["is_duplicate"]].assign(month=t["ticket_date"].dt.strftime("%Y-%m"))
    months = sorted(t["month"].unique())
    fig, ax = plt.subplots(figsize=(10, 3.0))
    bottom = [0] * len(months)
    for cat, color in CATEGORY_COLORS.items():
        counts = t[t["category"] == cat].groupby("month").size().reindex(months, fill_value=0).tolist()
        ax.bar(range(len(months)), counts, bottom=bottom, color=color, edgecolor=BLACK, linewidth=0.8,
               width=0.65, label=cat)
        bottom = [b + c for b, c in zip(bottom, counts)]
    ax.set_xticks(range(len(months)), month_labels(months))
    style_axes(ax, "Support tickets per month by category (duplicates removed)", "Tickets")
    ax.legend(frameon=False, fontsize=8, ncols=4, loc="upper left")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


# ---------------------------------------------------------------- PDF

class Report(FPDF):
    def __init__(self):
        super().__init__(format="A4")
        self.add_font("DejaVu", "", FONT_DIR / "DejaVuSans.ttf")
        self.add_font("DejaVu", "B", FONT_DIR / "DejaVuSans-Bold.ttf")
        self.add_font("DejaVu", "I", FONT_DIR / "DejaVuSans-Oblique.ttf")
        self.add_font("DejaVu", "BI", FONT_DIR / "DejaVuSans-BoldOblique.ttf")
        self.set_margins(16, 16, 16)
        self.set_auto_page_break(True, margin=18)

    def footer(self):
        self.set_y(-12)
        self.set_font("DejaVu", "", 7.5)
        self.set_text_color(130, 130, 130)
        self.cell(0, 5, f"Digital Model Designer · data analysis case from LEGO · simulated data · generated "
                        f"{date.today():%d %B %Y}", align="L")
        self.cell(0, 5, f"Page {self.page_no()} / {{nb}}", align="R")

    def section(self, title: str, color: str = BLUE):
        if self.get_y() > self.h - 50:
            self.add_page()
        self.ln(3)
        y = self.get_y()
        self.set_fill_color(*rgb(color))
        self.rect(self.l_margin, y, 2.2, 7.5, style="F")
        self.set_xy(self.l_margin + 5, y)
        self.set_font("DejaVu", "B", 13)
        self.set_text_color(*rgb(BLACK))
        self.cell(0, 7.5, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(1.5)

    def paragraph(self, text: str, size: float = 10):
        self.set_font("DejaVu", "", size)
        self.set_text_color(*rgb(BLACK))
        self.multi_cell(0, 5.2, text, markdown=True, align="L", new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def full_width_image(self, path: Path, aspect: float):
        """Insert an image across the page, starting a new page if it wouldn't fit."""
        w = self.w - self.l_margin - self.r_margin
        if self.get_y() + w * aspect > self.page_break_trigger:
            self.add_page()
        self.image(str(path), w=w)
        self.ln(2)


def emphasise(paragraph: str) -> str:
    """Bold the lead sentence of numbered points and labels like 'Recommendation:'."""
    paragraph = paragraph.replace("**", "")
    m = re.match(r"^(\d+\.\s+.+?[.?!])(\s|$)", paragraph)
    if m:
        return f"**{m.group(1)}**{paragraph[m.end(1):]}"
    m = re.match(r"^([A-Z][^:.\n]{0,30}:)", paragraph)
    if m:
        return f"**{m.group(1)}**{paragraph[m.end(1):]}"
    return paragraph


def build_report(path: Path = REPORT_FILE) -> Path:
    d = load()
    answers = {a["id"]: a for a in json.loads(ANSWERS_FILE.read_text(encoding="utf-8"))}
    h = headline(d)
    months = sorted(d["usage"]["month"].unique())
    first = date.fromisoformat(months[0] + "-01").strftime("%B %Y")
    last = date.fromisoformat(months[-1] + "-01").strftime("%B %Y")

    pdf = Report()
    pdf.add_page()

    # --- header band
    pdf.set_fill_color(*rgb(RED))
    pdf.rect(0, 0, pdf.w, 34, style="F")
    pdf.set_fill_color(*rgb(YELLOW))
    pdf.rect(0, 34, pdf.w, 2.2, style="F")
    pdf.image(str(ROOT / "lego_logo.png"), x=16, y=6, h=22)
    pdf.set_xy(44, 9)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("DejaVu", "B", 18)
    pdf.cell(0, 9, "Digital Model Designer · Usage Insights", new_x="LEFT", new_y="NEXT")
    pdf.set_font("DejaVu", "", 10)
    pdf.cell(0, 6, f"Summary of findings · usage {first} to {last} · {len(d['users'])} designers")
    pdf.set_y(44)

    # --- KPI tiles
    tiles = [
        ("Avg. satisfaction", h["satisfaction"], h["not_recommend"], False),
        (h["eps_label"], h["eps"], h["eps_sub"], True),
        ("Open support tickets", h["open"], h["open_sub"], True),
        ("Designers at risk", h["risk"], "See definition in appendix", False),
    ]
    gap, width = 4, (pdf.w - pdf.l_margin - pdf.r_margin - 3 * 4) / 4
    y = pdf.get_y()
    for i, (label, value, sub, alert) in enumerate(tiles):
        x = pdf.l_margin + i * (width + gap)
        pdf.set_draw_color(*rgb(BLACK))
        pdf.set_line_width(0.5)
        pdf.rect(x, y, width, 26, round_corners=True, corner_radius=2)
        pdf.set_xy(x + 3, y + 3)
        pdf.set_font("DejaVu", "", 7.5)
        pdf.set_text_color(90, 90, 90)
        pdf.cell(width - 6, 4, label)
        pdf.set_xy(x + 3, y + 8)
        pdf.set_font("DejaVu", "B", 17)
        pdf.set_text_color(*rgb(RED if alert else BLACK))
        pdf.cell(width - 6, 8, value)
        pdf.set_xy(x + 3, y + 17)
        pdf.set_font("DejaVu", "", 6.8)
        pdf.set_text_color(100, 100, 100)
        pdf.multi_cell(width - 6, 3.4, sub, align="L")
    pdf.set_y(y + 31)

    # --- bottom line
    recommendation = next((p for p in answers["q4"]["text"].split("\n\n") if p.startswith("Recommendation")),
                          "")
    pdf.set_fill_color(255, 248, 204)
    pdf.set_draw_color(*rgb(BLACK))
    pdf.set_font("DejaVu", "", 10)
    pdf.set_text_color(*rgb(BLACK))
    pdf.multi_cell(0, 5.5, "**Bottom line:** v2.3 is driving crashes and errors, and the power users who do most "
                   "of the work are leaving while their tickets stay open. " + recommendation.replace(
                       "Recommendation: ", "**Recommendation:** "),
                   border=1, fill=True, padding=3, markdown=True, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    with tempfile.TemporaryDirectory() as tmp:
        trend_png, tickets_png = Path(tmp) / "trend.png", Path(tmp) / "tickets.png"
        trend_chart(d, trend_png)
        tickets_chart(d, tickets_png)

        # --- Q1-Q4 from answers.json
        for qid in ["q1", "q2", "q3", "q4"]:
            a = answers[qid]
            pdf.section(a["title"], RED if qid == "q4" else BLUE)
            for para in a["text"].split("\n\n"):
                pdf.paragraph(emphasise(para.strip()))

        # --- Q5 with the chart itself (figure sizes: 10x3.6 and 10x3.0 inches)
        pdf.section(answers["q5"]["title"])
        pdf.full_width_image(trend_png, 3.6 / 10)
        for para in answers["q5"]["text"].split("\n\n"):
            pdf.paragraph(emphasise(para.strip()))
        pdf.full_width_image(tickets_png, 3.0 / 10)

    # --- appendix (own page, so it never splits)
    pdf.add_page()
    pdf.section("Appendix · Data and method", "#8A8A8A")
    t, s, u = d["tickets"], d["survey"], d["usage"]
    for line in [
        f"**Sources:** usage logs ({len(u)} rows, {u['user_id'].nunique()} designers × {len(months)} months), "
        f"support tickets ({len(t)} rows) and a satisfaction survey ({len(s)} responses). All data is simulated.",
        "**Cleaning:** each Excel file stored rows as one comma-separated text cell; these were split into "
        "columns. Inconsistent capitalisation was normalised and four US-style dates (e.g. 02/10/2026) were "
        "read month-first, confirmed by neighbouring rows. No values were filled in.",
        f"**Excluded from counts:** {int(t['is_duplicate'].sum())} duplicate tickets (T091–T095) and one "
        "implausible error count (520 in one month). Both stay visible in the dashboard, marked as flagged.",
        "**Survey:** averages use each designer's latest response, because some answered two or three times.",
        "**Designers at risk:** latest satisfaction of 1 or 2 out of 5, and either sessions down 20% or more "
        f"from {first} to {last} or at least one open or in-progress ticket.",
        "**Reproduce:** run 'uv sync', then 'uv run python scripts/dashboard.py' (dashboard at "
        "http://127.0.0.1:8050) or 'uv run python scripts/make_report.py' (this PDF). Answer texts live in "
        "answers.json.",
    ]:
        pdf.paragraph(line, size=9)

    path.parent.mkdir(exist_ok=True)
    pdf.output(str(path))
    return path


if __name__ == "__main__":
    print("Wrote", build_report().relative_to(ROOT))
