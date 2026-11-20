import argparse
import hashlib
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import pandas as pd
import requests
import yaml
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )
}


def load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def fetch_article_body(url: str, fallback_summary: str) -> str:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=12)
        if resp.status_code != 200:
            return BeautifulSoup(fallback_summary, "html.parser").get_text(" ", strip=True)
        soup = BeautifulSoup(resp.text, "html.parser")
        paragraphs = [
            p.get_text(" ", strip=True)
            for p in soup.find_all("p")
            if len(p.get_text(strip=True)) > 45
        ]
        full_text = " ".join(paragraphs[:15])
        return full_text if len(full_text) > 150 else BeautifulSoup(fallback_summary, "html.parser").get_text(" ", strip=True)
    except Exception:
        return BeautifulSoup(fallback_summary, "html.parser").get_text(" ", strip=True)


def run_ingestion(config_path: str) -> Path:
    cfg = load_config(config_path)
    market_id = cfg["market_id"]
    cutoff = datetime.now(timezone.utc) - timedelta(days=cfg.get("lookback_days", 7))
    records = []

    for feed_cfg in cfg.get("rss_feeds", []):
        print(f"[{market_id}] Fetching feed: {feed_cfg['outlet_name']}...")
        parsed = feedparser.parse(feed_cfg["url"])
        for entry in parsed.entries[:30]:
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            else:
                published_dt = datetime.now(timezone.utc)

            if published_dt < cutoff:
                continue

            url = entry.get("link", "")
            title = entry.get("title", "").strip()
            summary = entry.get("summary", "")
            body_text = fetch_article_body(url, summary)
            article_id = hashlib.sha256(f"{market_id}:{url}".encode()).hexdigest()[:16]

            records.append(
                {
                    "article_id": article_id,
                    "market_id": market_id,
                    "outlet_id": feed_cfg["outlet_id"],
                    "outlet_name": feed_cfg["outlet_name"],
                    "outlet_category": feed_cfg["category"],
                    "published_at": published_dt.isoformat(),
                    "title": title,
                    "url": url,
                    "body_text": body_text[:4000],
                    "word_count": len(body_text.split()),
                }
            )
            time.sleep(0.4)

    df = pd.DataFrame(records).drop_duplicates(subset=["article_id"])
    Path("data").mkdir(exist_ok=True)
    out_file = Path("data") / f"raw_{market_id}.parquet"
    df.to_parquet(out_file, index=False)
    print(f"[{market_id}] Saved {len(df)} unique articles -> {out_file}")
    return out_file


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    run_ingestion(args.config)
