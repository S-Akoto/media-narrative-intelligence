# Multi-Market Political Media & Narrative Intelligence Engine

An automated, serverless analytics pipeline that ingests political and policy news across **US National / Connecticut** and **Ghana**, clusters syndicated duplicates using local vector embeddings, filters non-policy wire noise via Gemini, and publishes an interactive dashboard to **GitHub Pages**.

**Live Dashboard:** [https://s-akoto.github.io/media-narrative-intelligence/](https://s-akoto.github.io/media-narrative-intelligence/)

---

## Architecture

```mermaid
flowchart LR
    A[RSS Feeds<br/>US/CT & Ghana] --> B[src/ingest.py<br/>BeautifulSoup + Parquet]
    B --> C[src/cluster.py<br/>MiniLM Cosine Deduplication]
    C --> D[src/enrich.py<br/>Gemini Relevance Gate + JSON]
    D --> E[src/report.py<br/>DuckDB Warehouse + Plotly HTML]
    E --> F[GitHub Pages<br/>docs/index.html]

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export GEMINI_API_KEY="your-api-key"

python src/ingest.py --config config/us_ct.yaml
python src/cluster.py --config config/us_ct.yaml
python src/enrich.py --config config/us_ct.yaml

python src/ingest.py --config config/ghana.yaml
python src/cluster.py --config config/ghana.yaml
python src/enrich.py --config config/ghana.yaml

python src/report.py

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export GEMINI_API_KEY=your-api-key

python src/ingest.py --config config/us_ct.yaml
python src/cluster.py --config config/us_ct.yaml
python src/enrich.py --config config/us_ct.yaml

python src/ingest.py --config config/ghana.yaml
python src/cluster.py --config config/ghana.yaml
python src/enrich.py --config config/ghana.yaml

python src/report.py
