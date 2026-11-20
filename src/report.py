from datetime import datetime, timezone
from pathlib import Path

import duckdb
import plotly.express as px


def build_report():
    con = duckdb.connect("data/media_intel.duckdb")
    con.execute("""
        CREATE OR REPLACE TABLE fact_media_stories AS
        SELECT * FROM read_parquet('data/enriched_*.parquet')
        WHERE is_canonical = TRUE
    """)

    df = con.execute("SELECT * FROM fact_media_stories").df()
    if df.empty:
        print("No enriched stories found.")
        return

    domain_summary = (
        df.groupby(["market_id", "policy_domain", "agenda_initiator"], as_index=False)
        .size()
        .rename(columns={"size": "unique_stories"})
    )

    fig_us = px.bar(
        domain_summary[domain_summary["market_id"] == "us_ct"],
        x="policy_domain",
        y="unique_stories",
        color="agenda_initiator",
        title="US National & Connecticut: Policy Coverage by Agenda Initiator",
        barmode="stack",
        template="plotly_white",
    )

    fig_gh = px.bar(
        domain_summary[domain_summary["market_id"] == "ghana"],
        x="policy_domain",
        y="unique_stories",
        color="agenda_initiator",
        title="Ghana Political Media: Policy Coverage by Agenda Initiator",
        barmode="stack",
        template="plotly_white",
    )

    opportunities = con.execute("""
        SELECT
            market_id AS Market,
            policy_domain AS Domain,
            agenda_initiator AS Initiator,
            framing_stance AS Framing,
            outlet_reach_count AS Outlets,
            title AS Headline,
            unanswered_questions AS Strategic_Gap
        FROM fact_media_stories
        WHERE framing_stance IN ('Critical/Accountability', 'Neutral/Wire')
        ORDER BY outlet_reach_count DESC, published_at DESC
        LIMIT 20
    """).df()

    table_html = opportunities.to_html(index=False, classes="brief-table", border=0)
    updated_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    html_page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Multi-Market Political Media & Narrative Intelligence</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 2rem; background: #f8fafc; color: #0f172a; }}
    .container {{ max-width: 1200px; margin: auto; }}
    header {{ margin-bottom: 2rem; border-bottom: 2px solid #e2e8f0; padding-bottom: 1rem; }}
    .card {{ background: #ffffff; border-radius: 8px; padding: 1.5rem; margin-bottom: 2rem; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
    .brief-table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
    .brief-table th, .brief-table td {{ padding: 0.75rem; text-align: left; border-bottom: 1px solid #e2e8f0; }}
    .brief-table th {{ background: #f1f5f9; font-weight: 600; }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>Multi-Market Media & Narrative Intelligence Engine</h1>
      <p>Automated Agenda-Setting, Syndication Clustering & Policy Gap Tracker | Last Updated: <strong>{updated_ts}</strong></p>
    </header>
    <div class="card">{fig_us.to_html(full_html=False, include_plotlyjs=False)}</div>
    <div class="card">{fig_gh.to_html(full_html=False, include_plotlyjs=False)}</div>
    <div class="card">
      <h2>Top Narrative Vulnerabilities & Underreported Policy Gaps</h2>
      {table_html}
    </div>
  </div>
</body>
</html>
"""
    Path("docs").mkdir(exist_ok=True)
    Path("docs/index.html").write_text(html_page, encoding="utf-8")
    print("Generated interactive GitHub Pages dashboard -> docs/index.html")


if __name__ == "__main__":
    build_report()
