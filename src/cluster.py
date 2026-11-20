import argparse
from pathlib import Path

import pandas as pd
import yaml
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity


def load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_clustering(config_path: str) -> Path:
    cfg = load_config(config_path)
    market_id = cfg["market_id"]
    threshold = cfg.get("similarity_threshold", 0.84)

    raw_path = Path("data") / f"raw_{market_id}.parquet"
    df = pd.read_parquet(raw_path)
    if df.empty:
        return raw_path

    print(f"[{market_id}] Embedding {len(df)} articles locally...")
    model = SentenceTransformer("all-MiniLM-L6-v2")
    texts = (df["title"] + ". " + df["body_text"].str[:500]).tolist()
    embeddings = model.encode(texts, normalize_embeddings=True)

    sim_matrix = cosine_similarity(embeddings)
    visited = set()
    cluster_ids = [-1] * len(df)
    is_canonical = [False] * len(df)
    cluster_counter = 0

    sorted_indices = df["word_count"].argsort()[::-1].tolist()

    for idx in sorted_indices:
        if idx in visited:
            continue
        cluster_label = f"{market_id}_c{cluster_counter:04d}"
        cluster_counter += 1
        visited.add(idx)
        cluster_ids[idx] = cluster_label
        is_canonical[idx] = True

        for peer_idx in sorted_indices:
            if peer_idx not in visited and sim_matrix[idx, peer_idx] >= threshold:
                visited.add(peer_idx)
                cluster_ids[peer_idx] = cluster_label

    df["cluster_id"] = cluster_ids
    df["is_canonical"] = is_canonical
    reach_map = df.groupby("cluster_id")["outlet_id"].nunique().to_dict()
    df["outlet_reach_count"] = df["cluster_id"].map(reach_map)

    out_path = Path("data") / f"clustered_{market_id}.parquet"
    df.to_parquet(out_path, index=False)
    print(f"[{market_id}] Grouped into {cluster_counter} unique stories -> {out_path}")
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    run_clustering(args.config)
