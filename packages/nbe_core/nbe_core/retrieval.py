"""Retrieval: bge-m3 embeddings (via the gateway) + Qdrant + bge-reranker-v2-m3.
Shared by D2 (chat with document) and D5 (legal), and used by D3/D4/D6/D7 for similarity search.
"""
import uuid

import httpx

from nbe_core.settings import settings

EMBED_DIM = 1024
_TIMEOUT = httpx.Timeout(120, connect=5)


async def embed(texts: list[str]) -> list[list[float]]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(f"{settings.llm_gateway_url}/embeddings", json={"model": "embed", "input": texts},
                              headers={"Authorization": f"Bearer {settings.llm_gateway_key}"})
        r.raise_for_status()
        return [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]


async def ensure_collection(name: str, recreate: bool = False) -> None:
    async with httpx.AsyncClient(timeout=_TIMEOUT, base_url=settings.qdrant_url) as client:
        if recreate:
            await client.delete(f"/collections/{name}")
        elif (await client.get(f"/collections/{name}")).status_code == 200:
            return
        r = await client.put(f"/collections/{name}", json={"vectors": {"size": EMBED_DIM, "distance": "Cosine"}})
        r.raise_for_status()


async def upsert(collection: str, texts: list[str], payloads: list[dict], batch: int = 32) -> int:
    """Embed and store texts. Each payload is stored with the text under `text`."""
    n = 0
    async with httpx.AsyncClient(timeout=_TIMEOUT, base_url=settings.qdrant_url) as client:
        for i in range(0, len(texts), batch):
            chunk, meta = texts[i:i + batch], payloads[i:i + batch]
            vectors = await embed(chunk)
            points = [{"id": str(uuid.uuid4()), "vector": v, "payload": {**m, "text": t}}
                      for t, m, v in zip(chunk, meta, vectors)]
            r = await client.put(f"/collections/{collection}/points?wait=true", json={"points": points})
            r.raise_for_status()
            n += len(points)
    return n


async def rerank(query: str, documents: list[str]) -> list[tuple[int, float]]:
    """Returns (index, score) pairs, best first."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(f"{settings.rerank_url}/v1/rerank",
                              json={"model": "bge-reranker-v2-m3", "query": query, "documents": documents})
        r.raise_for_status()
        return [(x["index"], x["relevance_score"]) for x in r.json()["results"]]


async def search(collection: str, query: str, k: int = 5, candidates: int = 20,
                 filters: dict | None = None) -> list[dict]:
    """Dense search for `candidates`, then rerank to the top `k`. Each hit: payload + scores."""
    [qv] = await embed([query])
    body: dict = {"vector": qv, "limit": candidates, "with_payload": True}
    if filters:
        body["filter"] = {"must": [{"key": key, "match": {"value": val}} for key, val in filters.items()]}
    async with httpx.AsyncClient(timeout=_TIMEOUT, base_url=settings.qdrant_url) as client:
        r = await client.post(f"/collections/{collection}/points/search", json=body)
        r.raise_for_status()
        hits = r.json()["result"]
    if not hits:
        return []
    order = await rerank(query, [h["payload"]["text"] for h in hits])
    return [{**hits[i]["payload"], "dense_score": round(hits[i]["score"], 4), "rerank_score": round(s, 4)}
            for i, s in order[:k]]
