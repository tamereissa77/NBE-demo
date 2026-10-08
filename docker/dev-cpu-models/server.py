"""TEMPORARY development stand-in for the two vLLM pooling servers (nbe-embed, nbe-rerank).

For a workstation whose GPU has no free memory: serves the same weights (bge-m3, bge-reranker-v2-m3)
on CPU behind the same two endpoints the demo calls, so nothing else changes:

    POST /v1/embeddings  {input}                    -> OpenAI shape, L2-normalised 1024-dim vectors
    POST /v1/rerank      {query, documents}         -> {results: [{index, relevance_score}]}, best first, scores 0 to 1

Used only through docker-compose.api.yml. The GB10 runs the vLLM servers of docker-compose.yml.
"""
import base64
import os

import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel

ROLE, PATH, NAME = os.environ["MODEL_ROLE"], os.environ["MODEL_PATH"], os.environ["MODEL_NAME"]
BATCH = int(os.getenv("BATCH", "8"))
app = FastAPI(title=f"NBE dev CPU {ROLE}")

if ROLE == "embed":
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(PATH, device="cpu")
else:
    from sentence_transformers import CrossEncoder
    model = CrossEncoder(PATH, device="cpu", max_length=8192)     # single-logit model: predict() applies a sigmoid


@app.get("/health")
def health():
    return {"status": "ok", "role": ROLE, "model": NAME, "device": "cpu"}


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": NAME, "object": "model"}]}


class Embeddings(BaseModel):
    input: list[str] | str
    encoding_format: str | None = None


@app.post("/v1/embeddings")
def embeddings(body: Embeddings):
    texts = [body.input] if isinstance(body.input, str) else body.input
    vecs = model.encode(texts, normalize_embeddings=True, batch_size=BATCH).astype(np.float32)
    enc = (lambda v: base64.b64encode(v.tobytes()).decode()) if body.encoding_format == "base64" else (lambda v: v.tolist())
    return {"object": "list", "model": NAME, "usage": {"prompt_tokens": 0, "total_tokens": 0},
            "data": [{"object": "embedding", "index": i, "embedding": enc(v)} for i, v in enumerate(vecs)]}


class Rerank(BaseModel):
    query: str
    documents: list[str]
    top_n: int | None = None


@app.post("/v1/rerank")
def rerank(body: Rerank):
    scores = model.predict([(body.query, d) for d in body.documents], batch_size=BATCH)
    order = sorted(range(len(scores)), key=lambda i: -float(scores[i]))[: body.top_n or len(scores)]
    return {"model": NAME, "results": [{"index": i, "document": {"text": body.documents[i]}, "relevance_score": float(scores[i])}
                                       for i in order]}
