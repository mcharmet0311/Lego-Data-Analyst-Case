"""LEGO Digital Model Designer - usage insights dashboard (local only).

Run:  uv run python scripts/dashboard.py
Open: http://127.0.0.1:8050
"""

import base64
import json
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
from dash import ALL, Dash, Input, Output, State, ctx, dcc, html, no_update

from flask import send_file

from data import ROOT, load
from make_report import build_report, emphasise

D = load()
USAGE, TICKETS, SURVEY, USERS = D["usage"], D["tickets"], D["survey"], D["users"]
MONTHS = sorted(USAGE["month"].unique())
ROLES = ["Power User", "Occasional User", "New User"]
ANSWERS_FILE = ROOT / "answers.json"

# LEGO palette (keep in sync with assets/style.css)
RED, YELLOW, BLUE, GREEN, BLACK = "#E3000B", "#FFD500", "#006CB7", "#00852B", "#1B1B1B"
ROLE_COLORS = {"Power User": RED, "Occasional User": YELLOW, "New User": BLUE}
CATEGORY_COLORS = {"Bug": RED, "Performance": YELLOW, "Question": BLUE, "Feature Request": "#A0A0A0"}
RECOMMEND_COLORS = {"Yes": GREEN, "Maybe": YELLOW, "No": RED}
OUTLINE = dict(color=BLACK, width=1)

LOGO = "data:image/png;base64," + base64.b64encode((ROOT / "lego_logo.png").read_bytes()).decode()


def month_name(ym: str, year: bool = True) -> str:
    """'2025-10' -> 'October 2025' (or 'October')."""
    return datetime.strptime(ym, "%Y-%m").strftime("%B %Y" if year else "%B")


FIRST, LAST = month_name(MONTHS[0], year=False), month_name(MONTHS[-1], year=False)


# ---------------------------------------------------------------- charts

def style_fig(fig: go.Figure, y_title: str = "") -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        height=340,
        # Legend sits in the top margin, above the plot area, so it never covers data.
        margin=dict(l=55, r=15, t=45, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.04, xanchor="left", x=0, title=None),
        font=dict(family="Segoe UI, Helvetica, Arial", color=BLACK, size=13),
        hoverlabel=dict(bgcolor="white", bordercolor=BLACK, font_color=BLACK),
        bargap=0.3,
    )
    fig.update_xaxes(showline=True, linecolor=BLACK, linewidth=1, ticks="outside", showgrid=False)
    fig.update_yaxes(title=y_title, showline=True, linecolor=BLACK, linewidth=1, gridcolor="#ECECEC",
                     zeroline=False, rangemode="tozero")
    return fig


def add_version_bands(fig: go.Figure) -> None:
    """Shade the months each tool version was live (category axis: month i sits at x=i)."""
    versions = USAGE.groupby("tool_version")["month"].agg(["min", "max"])
    for i, (version, row) in enumerate(versions.iterrows()):
        fig.add_vrect(x0=MONTHS.index(row["min"]) - 0.5, x1=MONTHS.index(row["max"]) + 0.5,
                      fillcolor=["#FAFAFA", "#FFF8D6", "#FDE8E9"][i % 3], opacity=1, layer="below",
                      line_width=0, annotation_text=f"<b>{version}</b>", annotation_position="top left",
                      annotation_font=dict(size=11, color="#555"))


def role_lines(df, value: str, how: str, y_title: str, fmt: str) -> go.Figure:
    labels = [month_name(m) for m in MONTHS]
    fig = go.Figure()
    for role in ROLES:
        sub = df[df["user_role"] == role]
        if sub.empty:
            continue
        series = sub.groupby("month")[value].agg(how).reindex(MONTHS)
        fig.add_scatter(x=labels, y=series, name=role, mode="lines+markers",
                        line=dict(color=ROLE_COLORS[role], width=3),
                        marker=dict(size=9, color=ROLE_COLORS[role], line=OUTLINE),
                        hovertemplate=f"%{{y:{fmt}}}")
    add_version_bands(fig)
    fig.update_layout(hovermode="x unified")
    fig.update_xaxes(type="category")
    return style_fig(fig, y_title)


def tickets_chart(df) -> go.Figure:
    df = df.assign(month=df["ticket_date"].dt.strftime("%Y-%m"))
    months = sorted(df["month"].unique())
    fig = go.Figure()
    for cat, color in CATEGORY_COLORS.items():
        counts = df[df["category"] == cat].groupby("month").size().reindex(months, fill_value=0)
        fig.add_bar(x=[month_name(m) for m in months], y=counts, name=cat,
                    marker=dict(color=color, line=OUTLINE), hovertemplate="%{y}")
    fig.update_layout(barmode="stack", hovermode="x unified")
    fig.update_xaxes(type="category")
    return style_fig(fig, "Tickets")


def recommend_chart(df) -> go.Figure:
    latest = df[df["is_latest"]]
    fig = go.Figure()
    for answer, color in RECOMMEND_COLORS.items():
        counts = [((latest["user_role"] == r) & (latest["would_recommend"] == answer)).sum() for r in ROLES]
        fig.add_bar(y=ROLES, x=counts, name=answer, orientation="h",
                    marker=dict(color=color, line=OUTLINE), text=[c or "" for c in counts],
                    textposition="inside", insidetextanchor="middle",
                    hovertemplate="%{y}: %{x} designers<extra>" + answer + "</extra>")
    fig.update_layout(barmode="stack")
    fig.update_yaxes(autorange="reversed", rangemode="normal")
    fig = style_fig(fig)
    fig.update_xaxes(title="Designers", showgrid=True, gridcolor="#ECECEC")
    fig.update_yaxes(showgrid=False)
    return fig


def chart_card(title: str, graph_id: str) -> html.Div:
    return html.Div(className="card", children=[
        html.H2(title),
        dcc.Graph(id=graph_id, config={"displayModeBar": False}),
    ])


# ---------------------------------------------------------------- designer table

CRM_COLUMNS = [  # (column, header, numeric)
    ("user_id", "Designer", False),
    ("user_role", "Role", False),
    ("dept_code", "Department", False),
    ("sessions_first_month", f"Sessions {FIRST}", True),
    ("sessions_last_month", f"Sessions {LAST}", True),
    ("session_change_pct", "Change", True),
    ("errors_first_month", f"Errors {FIRST}", True),
    ("errors_last_month", f"Errors {LAST}", True),
    ("tickets", "Tickets", True),
    ("open_tickets", "Open tickets", True),
    ("satisfaction", "Satisfaction", True),
    ("would_recommend", "Recommend", False),
    ("at_risk", "Status", False),
]


def chip(text, kind: str) -> html.Span:
    return html.Span(text, className=f"chip {kind}")


def crm_cell(col: str, value):
    if pd.isna(value):
        return html.Span("–", className="muted")
    if col == "user_id":
        return html.B(value)
    if col == "user_role":
        return html.Span([html.Span(className="dot", style={"background": ROLE_COLORS[value]}), value])
    if col == "session_change_pct":
        up = value >= 0
        return html.Span(f"{'▲' if up else '▼'} {abs(value)}%", className="up" if up else "down")
    if col == "open_tickets":
        return html.B(value, className="down") if value else "0"
    if col == "satisfaction":
        return chip(f"{value} / 5", "good" if value >= 4 else "mid" if value == 3 else "bad")
    if col == "would_recommend":
        return chip(value, {"Yes": "good", "Maybe": "mid", "No": "bad"}[value])
    if col == "at_risk":
        return chip("At risk", "bad") if value else html.Span("–", className="muted")
    return str(value)


def crm_table(users: pd.DataFrame, sort: dict) -> html.Table:
    col, asc = sort.get("col"), sort.get("asc", True)
    if col:
        users = users.sort_values(col, ascending=asc, na_position="last", kind="stable")
    else:  # default: at-risk first, then least satisfied
        users = users.sort_values(["at_risk", "satisfaction"], ascending=[False, True])

    header = html.Tr([
        html.Th([name, html.Span("▲" if asc else "▼", className="arrow") if c == col else None],
                id={"type": "crm-sort", "index": c},
                className=("num " if numeric else "") + ("sorted" if c == col else ""),
                title="Click to sort")
        for c, name, numeric in CRM_COLUMNS
    ])
    rows = [
        html.Tr([html.Td(crm_cell(c, row[c]), className="num" if numeric else None)
                 for c, _, numeric in CRM_COLUMNS],
                id={"type": "crm-row", "index": row["user_id"]},
                className="risk" if row["at_risk"] else None)
        for _, row in users.iterrows()
    ]
    return html.Table(className="crm", children=[html.Thead(header), html.Tbody(rows)])


# ---------------------------------------------------------------- popup content

def ticket_table(tickets) -> html.Table:
    header = ["Ticket", "Date", "Issue", "Category", "Status", "Days to resolve", "Version"]
    rows = []
    for t in tickets.itertuples():
        ticket_cell = [t.ticket_id]
        if t.is_duplicate:
            ticket_cell.append(html.Span("!", className="flag",
                                         **{"data-tip": f"Duplicate of {t.duplicate_of}: same user, date and "
                                                        "issue. Left out of all counts."}))
        days = "" if pd.isna(t.resolution_days) else t.resolution_days
        rows.append(html.Tr(
            [html.Td(ticket_cell), html.Td(f"{t.ticket_date:%d %B %Y}"), html.Td(t.issue_description),
             html.Td(t.category), html.Td(t.status), html.Td(days), html.Td(t.tool_version)],
            className=" ".join(c for c in ["dup" if t.is_duplicate else "", "open" if t.is_open else ""] if c),
        ))
    return html.Table(className="tickets", children=[
        html.Thead(html.Tr([html.Th(h) for h in header])),
        html.Tbody(rows),
    ])


def user_detail(user_id: str) -> html.Div:
    user = USERS.set_index("user_id").loc[user_id]
    tickets = TICKETS[TICKETS["user_id"] == user_id].sort_values("ticket_date")
    n_dup = int(tickets["is_duplicate"].sum())

    answers = SURVEY[SURVEY["user_id"] == user_id].sort_values("survey_date")
    quotes = [
        html.Div(className="quote", children=[
            html.B(f"{r.survey_date:%d %B %Y} · satisfaction {r.satisfaction_score}/5 · "
                   f"recommend: {r.would_recommend}"),
            html.Div(f"Frustration: {r.primary_frustration if isinstance(r.primary_frustration, str) else '–'}"),
            html.Div(f"Works well: {r.what_works_well if isinstance(r.what_works_well, str) else '–'}"),
        ])
        for r in answers.itertuples()
    ]

    risk = chip("At risk", "bad") if user["at_risk"] else None
    return html.Div([
        html.H2([f"{user_id} · {user['user_role']} · Department {user['dept_code']} ", risk]),
        html.H3(f"Support tickets ({len(tickets) - n_dup}"
                + (f", plus {n_dup} duplicate{'s' if n_dup > 1 else ''})" if n_dup else ")")),
        ticket_table(tickets) if len(tickets) else html.P("No support tickets."),
        html.H3("Survey answers"),
        *(quotes or [html.P("No survey answers.")]),
    ])


# ---------------------------------------------------------------- layout

def kpi(label: str, value: str, sub: str, alert: bool = False) -> html.Div:
    return html.Div(className="card kpi" + (" alert" if alert else ""), children=[
        html.Div(label, className="label"),
        html.Div(value, className="value"),
        html.Div(sub, className="sub"),
    ])


def load_answers() -> list[dict]:
    return json.loads(ANSWERS_FILE.read_text(encoding="utf-8"))


def answers_card(answers: list[dict]) -> html.Div:
    """One card, one row per case question: question on the left, answer on the right."""
    rows = []
    for a in answers:
        number, _, topic = a["title"].partition(" · ")
        paragraphs = [emphasise(p.strip()) for p in a["text"].split("\n\n")]
        rows.append(html.Div(className="qa-row" + (" risk" if a["id"] == "q4" else ""), children=[
            html.Div(className="qa-question", children=[
                html.Span(number, className="qa-number"),
                html.Div([html.B(topic), html.Div(a.get("question", ""), className="qa-asked")]),
            ]),
            dcc.Markdown("\n\n".join(paragraphs), className="qa-answer"),
        ]))
    return html.Div(className="card answers", children=[
        html.H2("Answers to the case questions"),
        *rows,
    ])


def serve_layout() -> html.Div:
    """A function, so a page reload picks up edits to answers.json."""
    answers = load_answers()
    return html.Div([
        html.Div(className="header", children=[
            html.Img(src=LOGO, alt="LEGO logo"),
            html.Div([
                html.H1("Digital Model Designer · Usage Insights"),
                html.P(f"Usage {month_name(MONTHS[0])} to {month_name(MONTHS[-1])} · {len(USERS)} designers · "
                       "support tickets and satisfaction survey"),
            ]),
            html.A("Summary report (PDF)", href="/summary.pdf", target="_blank", className="btn header-btn",
                   title="Built fresh from the data and answers.json"),
        ]),
        html.Div(className="page", children=[
            html.Div(className="filters", children=[
                html.Label("User role:"),
                dcc.Checklist(id="roles", options=ROLES, value=ROLES, inline=True, className="pills"),
                html.Span("Flagged data (5 duplicate tickets, 1 implausible error count) is excluded.",
                          className="note"),
            ]),
            html.Div(id="kpis", className="kpis"),
            html.Div(className="charts", children=[
                chart_card("Sessions per month by user role", "sessions-chart"),
                chart_card("Errors per session by user role", "errors-chart"),
                chart_card("Support tickets per month (duplicates removed)", "tickets-chart"),
                chart_card("Would you recommend the tool? (latest answer per designer)", "recommend-chart"),
            ]),
            answers_card(answers),
            html.Div(className="card", children=[
                html.H2("Designers"),
                html.P("Click a column header to sort, click a designer to see their tickets and survey answers.",
                       className="crm-hint"),
                dcc.Store(id="crm-sort", data={}),
                html.Div(id="crm-wrap", className="table-wrap"),
            ]),
        ]),
        html.Div(id="modal", className="modal-backdrop", hidden=True, children=[
            html.Div(className="modal", role="dialog", children=[
                html.Button("×", id="modal-close", className="modal-close", title="Close"),
                html.Div(id="modal-body"),
            ]),
        ]),
    ])


app = Dash(__name__, title="LEGO DMD Insights")
app.layout = serve_layout


@app.server.route("/summary.pdf")
def summary_pdf():
    """Rebuild the report on every request, so it always matches the data and answers.json."""
    return send_file(build_report(), mimetype="application/pdf", download_name="findings_summary.pdf")


# ---------------------------------------------------------------- callbacks

@app.callback(
    Output("kpis", "children"),
    Output("sessions-chart", "figure"),
    Output("errors-chart", "figure"),
    Output("tickets-chart", "figure"),
    Output("recommend-chart", "figure"),
    Input("roles", "value"),
)
def update_overview(roles):
    roles = roles or []
    usage = USAGE[USAGE["user_role"].isin(roles)]
    tickets = TICKETS[TICKETS["user_role"].isin(roles) & ~TICKETS["is_duplicate"]]
    survey = SURVEY[SURVEY["user_role"].isin(roles)]
    users = USERS[USERS["user_role"].isin(roles)]

    eps = usage.groupby("tool_version")["errors_per_session"].mean()
    open_t = tickets[tickets["is_open"]]
    if len(eps):
        v_first, v_last = eps.index.min(), eps.index.max()
        errors_kpi = kpi(f"Errors per session, {v_last}", f"{eps[v_last]:.2f}",
                         f"{eps[v_last] / eps[v_first]:.1f}× as many as {v_first} ({eps[v_first]:.2f} per session)",
                         alert=True)
    else:
        errors_kpi = kpi("Errors per session", "–", "", alert=True)
    kpis = [
        kpi("Avg. satisfaction (latest answer)",
            f"{users['satisfaction'].mean():.1f} / 5" if len(users) else "–",
            f"{(users['would_recommend'] == 'No').sum()} of {len(users)} would not recommend"),
        errors_kpi,
        kpi("Open support tickets", f"{len(open_t)}",
            f"{(open_t['tool_version'] == 'v2.3').sum()} of them on v2.3", alert=True),
        kpi("Designers at risk", f"{int(users['at_risk'].sum())} of {len(users)}",
            html.Span([
                "Counted when ", html.B("both"), " apply:", html.Br(),
                "1. Latest survey satisfaction is 1 or 2 out of 5", html.Br(),
                "2. Sessions fell 20% or more from ", f"{FIRST} to {LAST}, ", html.B("or"),
                " they have at least 1 open or in-progress support ticket (duplicates not counted)",
            ])),
    ]
    return (
        kpis,
        role_lines(usage, "sessions_count", "sum", "Sessions", ",.0f"),
        role_lines(usage, "errors_per_session", "mean", "Errors per session", ".2f"),
        tickets_chart(tickets),
        recommend_chart(survey),
    )


@app.callback(Output("crm-wrap", "children"), Input("roles", "value"), Input("crm-sort", "data"))
def update_table(roles, sort):
    return crm_table(USERS[USERS["user_role"].isin(roles or [])], sort or {})


@app.callback(
    Output("crm-sort", "data"),
    Input({"type": "crm-sort", "index": ALL}, "n_clicks"),
    State("crm-sort", "data"),
    prevent_initial_call=True,
)
def sort_table(_clicks, sort):
    # The table re-renders after sorting, which resets n_clicks; ignore those empty triggers.
    if not isinstance(ctx.triggered_id, dict) or not ctx.triggered[0]["value"]:
        return no_update
    col = ctx.triggered_id["index"]
    if sort.get("col") == col:
        return {"col": col, "asc": not sort.get("asc", True)}
    numeric = next(n for c, _, n in CRM_COLUMNS if c == col)
    return {"col": col, "asc": not numeric}  # numbers start high-to-low, text A-Z


@app.callback(
    Output("modal", "hidden"),
    Output("modal-body", "children"),
    Input({"type": "crm-row", "index": ALL}, "n_clicks"),
    Input("modal-close", "n_clicks"),
    prevent_initial_call=True,
)
def toggle_modal(_row_clicks, _close_clicks):
    if ctx.triggered_id == "modal-close":
        return True, no_update
    if isinstance(ctx.triggered_id, dict) and ctx.triggered[0]["value"]:
        return False, user_detail(ctx.triggered_id["index"])
    return no_update, no_update


if __name__ == "__main__":
    # Local only: 127.0.0.1 is not reachable from other machines.
    app.run(host="127.0.0.1", port=8050, debug=False)
