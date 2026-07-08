"""
RAG retriever - query a platform's ChromaDB collection for relevant chunks.
"""
from __future__ import annotations

import os
import sys
import time
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_SCORE_FLOOR = 0.30

# ChromaDB builds/compacts HNSW indexes in the background after a large ingest.
# A query landing in that window can raise "Error loading hnsw index". These
# retries ride out that transient state instead of failing the whole turn.
_QUERY_RETRIES = 3
_QUERY_BACKOFF_S = 0.75


@lru_cache(maxsize=1)
def _get_embed_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2"), device="cpu")


@lru_cache(maxsize=1)
def _get_chroma_client():
    import chromadb
    chroma_dir = os.getenv("CHROMA_PERSIST_DIR", "./rag/chroma_db")
    return chromadb.PersistentClient(path=str(Path(chroma_dir)))


def retrieve(platform: str, query: str, top_k: int | None = None) -> list[dict]:
    """
    Returns: [{"content": str, "source": str, "score": float}, ...]
    Filtered: score >= 0.30
    Sorted: descending by score
    top_k: defaults to int(os.getenv("RAG_TOP_K", 5))
    """
    if top_k is None:
        top_k = int(os.getenv("RAG_TOP_K", "5"))

    try:
        client = _get_chroma_client()
        collection = client.get_collection(f"cloud_agents_{platform}")
    except Exception:
        return []

    model = _get_embed_model()
    emb = model.encode([query], normalize_embeddings=True)[0].tolist()

    # Retry the vector query to survive transient HNSW/compactor errors. If it
    # still fails, degrade gracefully: return no RAG context so the agent can
    # still answer using the model + tools, rather than crashing the turn.
    res = None
    for attempt in range(_QUERY_RETRIES):
        try:
            res = collection.query(
                query_embeddings=[emb], n_results=max(top_k * 2, top_k)
            )
            break
        except Exception as exc:
            if attempt < _QUERY_RETRIES - 1:
                time.sleep(_QUERY_BACKOFF_S * (attempt + 1))
                continue
            print(
                f"[rag] retrieval unavailable for '{platform}' "
                f"({type(exc).__name__}: {str(exc)[:120]}). "
                "Answering without doc context.",
                file=sys.stderr,
            )
            return []

    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]

    results: list[dict] = []
    for doc, meta, dist in zip(docs, metas, dists):
        # Cosine distance -> similarity. Chroma returns distance in [0, 2] for cosine.
        score = max(0.0, 1.0 - float(dist))
        if score < _SCORE_FLOOR:
            continue
        results.append({
            "content": doc,
            "source": (meta or {}).get("source", "unknown"),
            "score": score,
        })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_k]
