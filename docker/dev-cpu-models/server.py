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
# DEVICE: cpu (default, as before) | cuda (GPU or fail) | auto (GPU if the model fits, else CPU). Set to auto by
# docker-compose.gpu-models.yml, with the CUDA build of torch. On a shared GPU the memory may not be there:
# /health says which device the model actually ended up on, and why.
DEVICE = os.getenv("DEVICE", "cpu")
HALF = os.getenv("GPU_HALF", "1") == "1"       # half precision on the GPU: half the memory, as vLLM serves these models
app = FastAPI(title=f"NBE dev {ROLE}")


def load(device: str):
    if ROLE == "embed":
        from sentence_transformers import SentenceTransformer
        m = SentenceTransformer(PATH, device=device)
    else:
        from sentence_transformers import CrossEncoder
        m = CrossEncoder(PATH, device=device, max_length=8192)    # single-logit model: predict() applies a sigmoid
    if device == "cuda":
        if HALF:
            (m if ROLE == "embed" else m.model).half()
        # one real call, so a GPU too full to work is found now and not on the first question
        m.encode(["warm-up"]) if ROLE == "embed" else m.predict([("warm-up", "warm-up")])
    return m


device, note = "cpu", ""
if DEVICE in ("cuda", "auto"):
    import torch
    try:
        if not torch.cuda.is_available():
            raise RuntimeError("no CUDA device is visible in this container")
        model, device = load("cuda"), "cuda"
    except Exception as exc:                    # typically: out of memory on a GPU other users have filled
        if DEVICE == "cuda":
            raise
        note = f"GPU not used: {str(exc).splitlines()[0][:200]}"
        torch.cuda.empty_cache()
if device == "cpu":
    model = load("cpu")


@app.get("/health")
def health():
    return {"status": "ok", "role": ROLE, "model": NAME, "device": device, **({"note": note} if note else {})}


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
