# Multi-Market Political Media & Narrative Intelligence Engine

An automated, serverless analytics pipeline that ingests political and policy news across **US National / Connecticut** and **Ghana**, clusters syndicated duplicates using local vector embeddings, extracts structured agenda-setting metadata via Gemini, and publishes a static interactive dashboard to **GitHub Pages**.

**Live Dashboard:** [https://s-akoto.github.io/media-narrative-intelligence/](https://s-akoto.github.io/media-narrative-intelligence/)

---

## Architecture

```mermaid
flowchart LR
    A[RSS Feeds<br/>US/CT & Ghana] --> B[src/ingest.py<br/>BeautifulSoup + Parquet]
    B --> C[src/cluster.py<br/>MiniLM Cosine Deduplication]
    C --> D[src/enrich.py<br/>Gemini Structured JSON + Fallback]
    D --> E[src/report.py<br/>DuckDB Warehouse + Plotly HTML]
    E --> F[GitHub Pages<br/>docs/index.html]

