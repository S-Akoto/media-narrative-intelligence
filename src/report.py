import html
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import plotly.express as px


def compute_kpis(raw_df, fact_df):
    ingested = int(len(raw_df))
    canonical = int(len(fact_df))
    if canonical == 0:
        return {
            "ingested": ingested,
            "canonical": 0,
            "top_domain": "N/A",
            "critical_pct": "0.0%",
        }
    top_domain = str(fact_df["policy_domain"].value_counts().idxmax())
    critical_count = int((fact_df["framing_stance"] == "Critical/Accountability").sum())
    critical_pct = f"{round((critical_count / canonical) * 100, 1)}%"
    return {
        "ingested": ingested,
        "canonical": canonical,
        "top_domain": top_domain,
        "critical_pct": critical_pct,
    }


def build_report():
    con = duckdb.connect("data/media_intel.duckdb")

    con.execute("""
        CREATE OR REPLACE TABLE raw_all_articles AS
        SELECT * FROM read_parquet('data/enriched_*.parquet', union_by_name=True)
    """)

    con.execute("""
        CREATE OR REPLACE TABLE fact_media_stories AS
        SELECT * FROM raw_all_articles
        WHERE is_canonical = TRUE
          AND COALESCE(is_relevant_policy_story, TRUE) = TRUE
    """)

    raw_df = con.execute("SELECT * FROM raw_all_articles").df()
    df = con.execute("SELECT * FROM fact_media_stories").df()
    if df.empty:
        print("No enriched stories found.")
        return

    kpi_data = {
        "all": compute_kpis(raw_df, df),
        "us_ct": compute_kpis(
            raw_df[raw_df["market_id"] == "us_ct"],
            df[df["market_id"] == "us_ct"],
        ),
        "ghana": compute_kpis(
            raw_df[raw_df["market_id"] == "ghana"],
            df[df["market_id"] == "ghana"],
        ),
    }

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
            title,
            url,
            unanswered_questions AS Strategic_Gap
        FROM fact_media_stories
        WHERE framing_stance IN ('Critical/Accountability', 'Neutral/Wire')
        ORDER BY outlet_reach_count DESC, published_at DESC
        LIMIT 50
    """).df()

    table_rows = []
    for _, row in opportunities.iterrows():
        market = html.escape(str(row["Market"]))
        domain = html.escape(str(row["Domain"]))
        initiator = html.escape(str(row["Initiator"]))
        framing = html.escape(str(row["Framing"]))
        outlets = html.escape(str(row["Outlets"]))
        safe_title = html.escape(str(row["title"]))
        safe_url = html.escape(str(row["url"]), quote=True)
        gap = html.escape(str(row["Strategic_Gap"]))

        table_rows.append(
            f'<tr data-market="{market}">'
            f"<td><strong>{market}</strong></td>"
            f"<td>{domain}</td>"
            f"<td>{initiator}</td>"
            f"<td>{framing}</td>"
            f"<td>{outlets}</td>"
            f'<td><a href="{safe_url}" target="_blank" rel="noopener noreferrer">{safe_title}</a></td>'
            f"<td>{gap}</td>"
            f"</tr>"
        )

    table_body_html = "\n".join(table_rows)
    updated_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    initial = kpi_data["all"]

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
    header {{ margin-bottom: 1.25rem; border-bottom: 2px solid #e2e8f0; padding-bottom: 1rem; display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-end; gap: 1rem; }}
    .tab-bar {{ display: inline-flex; background: #e2e8f0; padding: 0.25rem; border-radius: 8px; gap: 0.25rem; }}
    .tab-btn {{ border: none; background: transparent; padding: 0.55rem 1rem; border-radius: 6px; font-size: 0.9rem; font-weight: 600; color: #475569; cursor: pointer; transition: all 0.15s ease; }}
    .tab-btn:hover {{ color: #0f172a; }}
    .tab-btn.active {{ background: #ffffff; color: #1d4ed8; box-shadow: 0 1px 2px rgba(0,0,0,0.1); }}
    .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem; margin-bottom: 2rem; }}
    .kpi-card {{ background: #ffffff; border-radius: 8px; padding: 1.25rem; box-shadow: 0 1px 3px rgba(0,0,0,0.08); border-left: 4px solid #2563eb; }}
    .kpi-label {{ font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; color: #64748b; font-weight: 600; }}
    .kpi-value {{ font-size: 1.55rem; font-weight: 700; color: #0f172a; margin-top: 0.35rem; }}
    .card {{ background: #ffffff; border-radius: 8px; padding: 1.5rem; margin-bottom: 2rem; box-shadow: 0 1px 3px rgba(0,0,0,0.08); overflow-x: auto; }}
    .brief-table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
    .brief-table th, .brief-table td {{ padding: 0.75rem; text-align: left; border-bottom: 1px solid #e2e8f0; vertical-align: top; }}
    .brief-table th {{ background: #f1f5f9; font-weight: 600; }}
    .brief-table a {{ color: #1d4ed8; text-decoration: none; font-weight: 500; }}
    .brief-table a:hover {{ text-decoration: underline; }}
    .hidden {{ display: none !important; }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1 style="margin: 0 0 0.4rem 0;">Multi-Market Media & Narrative Intelligence Engine</h1>
        <p style="margin: 0; color: #475569;">Automated Agenda-Setting, Syndication Clustering & Policy Gap Tracker | Last Updated: <strong>{updated_ts}</strong></p>
      </div>
      <div class="tab-bar" role="tablist" aria-label="Market Filter">
        <button class="tab-btn active" data-filter="all" onclick="setMarket('all', this)">All Markets</button>
        <button class="tab-btn" data-filter="us_ct" onclick="setMarket('us_ct', this)">US & Connecticut</button>
        <button class="tab-btn" data-filter="ghana" onclick="setMarket('ghana', this)">Ghana</button>
      </div>
    </header>

    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-label">Articles Ingested (7-Day)</div>
        <div class="kpi-value" id="kpi-ingested">{initial["ingested"]}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Deduplicated Policy Stories</div>
        <div class="kpi-value" id="kpi-canonical">{initial["canonical"]}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Top Policy Domain</div>
        <div class="kpi-value" id="kpi-domain" style="font-size: 1.15rem;">{html.escape(initial["top_domain"])}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Accountability Framing</div>
        <div class="kpi-value" id="kpi-critical">{initial["critical_pct"]}</div>
      </div>
    </div>

    <div class="card" id="chart-us_ct">{fig_us.to_html(full_html=False, include_plotlyjs=False)}</div>
    <div class="card" id="chart-ghana">{fig_gh.to_html(full_html=False, include_plotlyjs=False)}</div>

    <div class="card">
      <h2 style="margin-top: 0;">Top Narrative Vulnerabilities & Underreported Policy Gaps</h2>
      <table class="brief-table">
        <thead>
          <tr>
            <th>Market</th>
            <th>Domain</th>
            <th>Initiator</th>
            <th>Framing</th>
            <th>Outlets</th>
            <th>Headline</th>
            <th>Strategic_Gap</th>
          </tr>
        </thead>
        <tbody id="brief-tbody">
          {table_body_html}
        </tbody>
      </table>
    </div>
  </div>

  <script>
    const KPI_DATA = {json.dumps(kpi_data)};

    function setMarket(market, btn) {{
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      const stats = KPI_DATA[market];
      document.getElementById('kpi-ingested').textContent = stats.ingested;
      document.getElementById('kpi-canonical').textContent = stats.canonical;
      document.getElementById('kpi-domain').textContent = stats.top_domain;
      document.getElementById('kpi-critical').textContent = stats.critical_pct;

      const usCard = document.getElementById('chart-us_ct');
      const ghCard = document.getElementById('chart-ghana');
      usCard.classList.toggle('hidden', market === 'ghana');
      ghCard.classList.toggle('hidden', market === 'us_ct');

      window.dispatchEvent(new Event('resize'));

      document.querySelectorAll('#brief-tbody tr').forEach(row => {{
        const rowMarket = row.getAttribute('data-market');
        row.classList.toggle('hidden', market !== 'all' && rowMarket !== market);
      }});
    }}
  </script>
</body>
</html>
"""
    Path("docs").mkdir(exist_ok=True)
    Path("docs/index.html").write_text(html_page, encoding="utf-8")
    print("Generated interactive GitHub Pages dashboard -> docs/index.html")


if __name__ == "__main__":
    build_report()
