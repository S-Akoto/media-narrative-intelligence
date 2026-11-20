import argparse
import os
import time
from pathlib import Path
from typing import List, Literal

import pandas as pd
import yaml
from google import genai
from google.genai import types
from pydantic import BaseModel, Field


class NarrativeExtraction(BaseModel):
    policy_domain: str = Field(description="Closest matching policy domain from the provided list.")
    agenda_initiator: Literal[
        "Government/Executive",
        "Opposition/Challenger",
        "Civil Society/Media",
        "Grassroots/Local",
    ] = Field(description="Who initiated or drove the primary event in this story.")
    framing_stance: Literal[
        "Pro-Government",
        "Critical/Accountability",
        "Neutral/Wire",
        "Opposition-Led",
    ] = Field(description="Overall editorial framing toward incumbent authorities.")
    key_entities: List[str] = Field(description="Up to 5 key agencies, legislators, or figures.")
    geographic_focus: str = Field(description="Specific state, region, city, or 'National'.")
    unanswered_questions: str = Field(
        description="One concise sentence noting any policy gap, contradiction, or accountability angle."
    )


def load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def extract_with_retry(client: genai.Client, prompt: str) -> NarrativeExtraction:
    models_to_try = ["gemini-3.8-flash", "gemini-3.1-flash-lite"]
    last_err = None
    for model_name in models_to_try:
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=NarrativeExtraction,
                        temperature=0.1,
                    ),
                )
                return response.parsed
            except Exception as exc:
                last_err = exc
                time.sleep(2 ** (attempt + 1))
    raise last_err


def run_enrichment(config_path: str) -> Path:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY environment variable is missing.")

    cfg = load_config(config_path)
    market_id = cfg["market_id"]
    domains = ", ".join(cfg["policy_domains"])

    df = pd.read_parquet(Path("data") / f"clustered_{market_id}.parquet")
    canonical_df = df[df["is_canonical"]].copy()

    client = genai.Client(api_key=api_key)
    enriched_rows = []

    print(f"[{market_id}] Enriching {len(canonical_df)} canonical stories...")
    for _, row in canonical_df.iterrows():
        prompt = (
            f"Analyze this news story for a political media intelligence brief.\n"
            f"Allowed policy_domain values: [{domains}].\n\n"
            f"Outlet: {row['outlet_name']} ({row['outlet_category']})\n"
            f"Headline: {row['title']}\n"
            f"Text: {row['body_text'][:2500]}"
        )
        try:
            parsed = extract_with_retry(client, prompt)
            enriched_rows.append(
                {
                    "cluster_id": row["cluster_id"],
                    "policy_domain": parsed.policy_domain,
                    "agenda_initiator": parsed.agenda_initiator,
                    "framing_stance": parsed.framing_stance,
                    "key_entities": ", ".join(parsed.key_entities),
                    "geographic_focus": parsed.geographic_focus,
                    "unanswered_questions": parsed.unanswered_questions,
                }
            )
        except Exception as exc:
            print(f"Skipping {row['cluster_id']}: {exc}")

        time.sleep(1.5)

    if not enriched_rows:
        raise RuntimeError(f"[{market_id}] No stories were enriched.")

    enrich_df = pd.DataFrame(enriched_rows)
    merged_df = df.merge(enrich_df, on="cluster_id", how="left")
    out_path = Path("data") / f"enriched_{market_id}.parquet"
    merged_df.to_parquet(out_path, index=False)
    print(f"[{market_id}] Saved {len(enriched_rows)}/{len(canonical_df)} enriched stories -> {out_path}")
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    run_enrichment(args.config)
