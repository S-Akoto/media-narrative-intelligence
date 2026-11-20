import html
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px


FRAMING_COLORS = {
    "Critical/Accountability": "#dc2626",
    "Opposition-Led": "#d97706",
    "Neutral/Wire": "#64748b",
    "Pro-Government": "#16a34a",
}


def compute_kpis(raw_df: pd.DataFrame, fact_df: pd.DataFrame) -> dict:
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


def update_historical_archive(current_fact_df: pd.DataFrame) -> pd.DataFrame:
    hist_path = Path("data") / "history_stories.parquet"
    archive_df = current_fact_df.copy()
    archive_df["archived_at"] = datetime.now(timezone.utc).isoformat()

    if hist_path.exists():
        existing_df = pd.read_parquet(hist_path)
        combined = pd.concat([existing_df, archive_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["market_id", "cluster_id"], keep="last")
    else:
        combined = archive_df

    combined.to_parquet(hist_path, index=False)
    return combined


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

    hist_df = update_historical_archive(df)
    con.register("hist_df_view", hist_df)
    con.execute("CREATE OR REPLACE TABLE dim_historical_stories AS SELECT * FROM hist_df_view")

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

    # 1. Horizontal Agenda Initiator Charts by Market
    domain_summary = (
        df.groupby(["market_id", "policy_domain", "agenda_initiator"], as_index=False)
        .size()
        .rename(columns={"size": "unique_stories"})
    )

    us_domain = domain_summary[domain_summary["market_id"] == "us_ct"]
    us_order = (
        us_domain.groupby("policy_domain")["unique_stories"].sum().sort_values(ascending=True).index.tolist()
    )
    fig_us_agenda = px.bar(
        us_domain,
        y="policy_domain",
        x="unique_stories",
        color="agenda_initiator",
        orientation="h",
        category_orders={"policy_domain": us_order},
        title="US National & Connecticut: Policy Volume by Agenda Initiator",
        labels={"policy_domain": "", "unique_stories": "Unique Policy Stories", "agenda_initiator": "Initiator"},
        barmode="stack",
        template="plotly_white",
    )
    fig_us_agenda.update_layout(margin=dict(l=10, r=10, t=45, b=20), height=360)

    gh_domain = domain_summary[domain_summary["market_id"] == "ghana"]
    gh_order = (
        gh_domain.groupby("policy_domain")["unique_stories"].sum().sort_values(ascending=True).index.tolist()
    )
    fig_gh_agenda = px.bar(
        gh_domain,
        y="policy_domain",
        x="unique_stories",
        color="agenda_initiator",
        orientation="h",
        category_orders={"policy_domain": gh_order},
        title="Ghana Political Media: Policy Volume by Agenda Initiator",
        labels={"policy_domain": "", "unique_stories": "Unique Policy Stories", "agenda_initiator": "Initiator"},
        barmode="stack",
        template="plotly_white",
    )
    fig_gh_agenda.update_layout(margin=dict(l=10, r=10, t=45, b=20), height=360)

    # 2. Editorial Slant / Framing Breakdown by Outlet Category
    slant_summary = (
        df.groupby(["market_id", "outlet_category", "framing_stance"], as_index=False)
        .size()
        .rename(columns={"size": "stories"})
    )

    fig_us_slant = px.bar(
        slant_summary[slant_summary["market_id"] == "us_ct"],
        y="outlet_category",
        x="stories",
        color="framing_stance",
        color_discrete_map=FRAMING_COLORS,
        orientation="h",
        title="US & CT: Editorial Framing by Outlet Type",
        labels={"outlet_category": "", "stories": "Stories", "framing_stance": "Framing"},
        barmode="stack",
        template="plotly_white",
    )
    fig_us_slant.update_layout(margin=dict(l=10, r=10, t=45, b=20), height=300)

    fig_gh_slant = px.bar(
        slant_summary[slant_summary["market_id"] == "ghana"],
        y="outlet_category",
        x="stories",
        color="framing_stance",
        color_discrete_map=FRAMING_COLORS,
        orientation="h",
        title="Ghana: Editorial Framing by Outlet Type",
        labels={"outlet_category": "", "stories": "Stories", "framing_stance": "Framing"},
        barmode="stack",
        template="plotly_white",
    )
    fig_gh_slant.update_layout(margin=dict(l=10, r=10, t=45, b=20), height=300)

    # 3. Strategic Vulnerabilities & Underreported Gaps Table
    opportunities = con.execute("""
        SELECT
            market_id AS Market,
            outlet_name AS Outlet,
            policy_domain AS Domain,
            agenda_initiator AS Initiator,
            framing_stance AS Framing,
            outlet_reach_count AS Outlets,
            title,
            url,
            key_entities,
            unanswered_questions AS Strategic_Gap
        FROM fact_media_stories
        ORDER BY outlet_reach_count DESC, published_at DESC
        LIMIT 75
    """).df()

    table_rows = []
    for _, row in opportunities.iterrows():
        market = html.escape(str(row["Market"]))
        outlet = html.escape(str(row["Outlet"]))
        domain = html.escape(str(row["Domain"]))
        initiator = html.escape(str(row["Initiator"]))
        framing = html.escape(str(row["Framing"]))
        outlets = html.escape(str(row["Outlets"]))
        safe_title = html.escape(str(row["title"]))
        safe_url = html.escape(str(row["url"]), quote=True)
        entities = html.escape(str(row.get("key_entities", "")))
        gap = html.escape(str(row["Strategic_Gap"]))

        badge_color = FRAMING_COLORS.get(str(row["Framing"]), "#475569")
        search_blob = html.escape(
            f"{row['Market']} {row['Outlet']} {row['Domain']} {row['Initiator']} {row['Framing']} {row['title']} {row.get('key_entities', '')} {row['Strategic_Gap']}".lower()
        )

        table_rows.append(
            f'<tr data-market="{market}" data-framing="{framing}" data-search="{search_blob}">'
            f"<td><strong>{market}</strong><br><span style='font-size:0.78rem;color:#64748b;'>{outlet}</span></td>"
            f"<td>{domain}</td>"
            f"<td>{initiator}</td>"
            f'<td><span style="display:inline-block;padding:0.2rem 0.5rem;border-radius:999px;font-size:0.78rem;font-weight:600;color:#fff;background:{badge_color};">{framing}</span></td>'
            f"<td style='text-align:center;'>{outlets}</td>"
            f'<td><a href="{safe_url}" target="_blank" rel="noopener noreferrer">{safe_title}</a><br><span style="font-size:0.78rem;color:#64748b;">Entities: {entities}</span></td>'
            f"<td>{gap}</td>"
            f"</tr>"
        )

    table_body_html = "\n".join(table_rows)
    updated_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    initial = kpi_data["all"]
    archive_total = len(hist_df)

    html_page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Multi-Market Political Media & Narrative Intelligence</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 2rem; background: #f8fafc; color: #0f172a; }}
    .container {{ max-width: 1240px; margin: auto; }}
    header {{ margin-bottom: 1.25rem; border-bottom: 2px solid #e2e8f0; padding-bottom: 1rem; display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-end; gap: 1rem; }}
    .tab-bar {{ display: inline-flex; background: #e2e8f0; padding: 0.25rem; border-radius: 8px; gap: 0.25rem; }}
    .tab-btn {{ border: none; background: transparent; padding: 0.55rem 1rem; border-radius: 6px; font-size: 0.9rem; font-weight: 600; color: #475569; cursor: pointer; transition: all 0.15s ease; }}
    .tab-btn:hover {{ color: #0f172a; }}
    .tab-btn.active {{ background: #ffffff; color: #1d4ed8; box-shadow: 0 1px 2px rgba(0,0,0,0.1); }}
    .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem; margin-bottom: 1.75rem; }}
    .kpi-card {{ background: #ffffff; border-radius: 8px; padding: 1.25rem; box-shadow: 0 1px 3px rgba(0,0,0,0.08); border-left: 4px solid #2563eb; }}
    .kpi-label {{ font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; color: #64748b; font-weight: 600; }}
    .kpi-value {{ font-size: 1.55rem; font-weight: 700; color: #0f172a; margin-top: 0.35rem; }}
    .market-section {{ display: grid; grid-template-columns: 1.3fr 1fr; gap: 1.25rem; margin-bottom: 1.75rem; }}
    @media (max-width: 900px) {{ .market-section {{ grid-template-columns: 1fr; }} }}
    .card {{ background: #ffffff; border-radius: 8px; padding: 1.25rem; box-shadow: 0 1px 3px rgba(0,0,0,0.08); overflow-x: auto; }}
    .table-controls {{ display: flex; flex-wrap: wrap; gap: 0.75rem; justify-content: space-between; align-items: center; margin-bottom: 1rem; }}
    .control-group {{ display: flex; flex-wrap: wrap; gap: 0.65rem; align-items: center; }}
    .search-input, .filter-select {{ padding: 0.5rem 0.75rem; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 0.9rem; background: #fff; color: #0f172a; }}
    .search-input {{ min-width: 260px; }}
    .brief-table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
    .brief-table th, .brief-table td {{ padding: 0.75rem; text-align: left; border-bottom: 1px solid #e2e8f0; vertical-align: top; }}
    .brief-table th {{ background: #f1f5f9; font-weight: 600; }}
    .brief-table a {{ color: #1d4ed8; text-decoration: none; font-weight: 600; }}
    .brief-table a:hover {{ text-decoration: underline; }}
    .hidden {{ display: none !important; }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1 style="margin: 0 0 0.4rem 0;">Multi-Market Media & Narrative Intelligence Engine</h1>
        <p style="margin: 0; color: #475569;">Automated Agenda-Setting, Syndication Clustering & Policy Gap Tracker | Updated: <strong>{updated_ts}</strong> | Historical Archive: <strong>{archive_total}</strong> stories</p>
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

    <div class="market-section" id="section-us_ct">
      <div class="card">{fig_us_agenda.to_html(full_html=False, include_plotlyjs=False)}</div>
      <div class="card">{fig_us_slant.to_html(full_html=False, include_plotlyjs=False)}</div>
    </div>

    <div class="market-section" id="section-ghana">
      <div class="card">{fig_gh_agenda.to_html(full_html=False, include_plotlyjs=False)}</div>
      <div class="card">{fig_gh_slant.to_html(full_html=False, include_plotlyjs=False)}</div>
    </div>

    <div class="card">
      <div class="table-controls">
        <h2 style="margin: 0;">Narrative Brief & Accountability Gaps (<span id="row-count">{len(table_rows)}</span> shown)</h2>
        <div class="control-group">
          <input type="text" id="table-search" class="search-input" placeholder="Search headline, entity, or gap..." oninput="filterTable()" />
          <select id="framing-filter" class="filter-select" onchange="filterTable()">
            <option value="all">All Framings</option>
            <option value="Critical/Accountability">Critical / Accountability</option>
            <option value="Opposition-Led">Opposition-Led</option>
            <option value="Neutral/Wire">Neutral / Wire</option>
            <option value="Pro-Government">Pro-Government</option>
          </select>
        </div>
      </div>
      <table class="brief-table">
        <thead>
          <tr>
            <th>Market / Outlet</th>
            <th>Domain</th>
            <th>Initiator</th>
            <th>Framing</th>
            <th>Reach</th>
            <th>Headline & Key Entities</th>
            <th>Strategic Gap / Unanswered Question</th>
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
    let activeMarket = 'all';

    function setMarket(market, btn) {{
      activeMarket = market;
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      const stats = KPI_DATA[market];
      document.getElementById('kpi-ingested').textContent = stats.ingested;
      document.getElementById('kpi-canonical').textContent = stats.canonical;
      document.getElementById('kpi-domain').textContent = stats.top_domain;
      document.getElementById('kpi-critical').textContent = stats.critical_pct;

      document.getElementById('section-us_ct').classList.toggle('hidden', market === 'ghana');
      document.getElementById('section-ghana').classList.toggle('hidden', market === 'us_ct');

      window.dispatchEvent(new Event('resize'));
      filterTable();
    }}

    function filterTable() {{
      const query = document.getElementById('table-search').value.trim().toLowerCase();
      const framing = document.getElementById('framing-filter').value;
      let visibleCount = 0;

      document.querySelectorAll('#brief-tbody tr').forEach(row => {{
        const rowMarket = row.getAttribute('data-market');
        const rowFraming = row.getAttribute('data-framing');
        const rowSearch = row.getAttribute('data-search');

        const matchMarket = (activeMarket === 'all' || rowMarket === activeMarket);
        const matchFraming = (framing === 'all' || rowFraming === framing);
        const matchQuery = (!query || rowSearch.includes(query));

        const show = matchMarket && matchFraming && matchQuery;
        row.classList.toggle('hidden', !show);
        if (show) visibleCount++;
      }});

      document.getElementById('row-count').textContent = visibleCount;
    }}
  </script>
</body>
</html>
"""
    Path("docs").mkdir(exist_ok=True)
    Path("docs/index.html").write_text(html_page, encoding="utf-8")
    print(f"Generated v2 dashboard -> docs/index.html (Historical archive: {archive_total} stories)")


if __name__ == "__main__":
    build_report()
