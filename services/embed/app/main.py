"""Embeddings and reranking on a workstation (docker-compose.local.yml): bge-m3 and bge-reranker-v2-m3
from the local model store, behind the endpoints the GB10's vLLM pooling servers expose, so
nbe_core.retrieval and the LiteLLM `embed` alias work unchanged.

POST /v1/embeddings {model, input: str | [str], encoding_format?} -> OpenAI embeddings response
POST /v1/rerank     {model, query, documents: [str]}              -> {results: [{index, relevance_score}]}, best first

Embeddings are bge-m3's dense vectors (CLS token, L2-normalised, 1024-dim); rerank scores are the
cross-encoder logit through a sigmoid, the 0-1 scale the demos' "not found" thresholds expect.
"""
import base64
import os
import time

import numpy as np
import torch
from fastapi import FastAPI
from pydantic import BaseModel
from transformers import AutoModel, AutoModelForSequenceClassification, AutoTokenizer

EMBED_MODEL = os.getenv("EMBED_MODEL", "/models/bge-m3-source")
RERANK_MODEL = os.getenv("RERANK_MODEL", "/models/bge-reranker-v2-m3")
DEVICE = os.getenv("RETRIEVAL_DEVICE", "cpu")
if DEVICE.startswith("cuda") and not torch.cuda.is_available():
    DEVICE = "cpu"                  # GPU asked for but not visible: slower, still correct
DTYPE = torch.float16 if DEVICE.startswith("cuda") else torch.float32
MAX_LEN = 8192
BATCH = 8
# One thread per core is far slower on a shared box (measured: 2.5 s per query with 24 threads, 60 ms with 8)
torch.set_num_threads(int(os.getenv("RETRIEVAL_THREADS", "8")))

app = FastAPI(title="NBE embeddings + reranker (bge-m3, bge-reranker-v2-m3)")
embed_tok = AutoTokenizer.from_pretrained(EMBED_MODEL)
embed_model = AutoModel.from_pretrained(EMBED_MODEL, torch_dtype=DTYPE).to(DEVICE).eval()
rerank_tok = AutoTokenizer.from_pretrained(RERANK_MODEL)
rerank_model = AutoModelForSequenceClassification.from_pretrained(RERANK_MODEL, torch_dtype=DTYPE).to(DEVICE).eval()


class EmbedIn(BaseModel):
    input: str | list[str]
    model: str = "bge-m3"
    encoding_format: str = "float"      # the OpenAI SDK (and so LiteLLM) asks for base64 by default


class RerankIn(BaseModel):
    query: str
    documents: list[str]
    model: str = "bge-reranker-v2-m3"
    top_n: int | None = None


@app.get("/health")
def health():
    return {"status": "ok", "device": DEVICE, "embed": EMBED_MODEL, "rerank": RERANK_MODEL}


@app.post("/v1/embeddings")
def embeddings(body: EmbedIn):
    texts = [body.input] if isinstance(body.input, str) else body.input
    vectors, tokens = [], 0
    with torch.inference_mode():
        for i in range(0, len(texts), BATCH):
            enc = embed_tok(texts[i:i + BATCH], padding=True, truncation=True, max_length=MAX_LEN, return_tensors="pt").to(DEVICE)
            tokens += int(enc["attention_mask"].sum())
            cls = embed_model(**enc).last_hidden_state[:, 0]
            vectors.append(torch.nn.functional.normalize(cls.float(), dim=-1).cpu().numpy())
    out = np.concatenate(vectors).astype(np.float32)
    data = [{"object": "embedding", "index": i,
             "embedding": base64.b64encode(v.tobytes()).decode() if body.encoding_format == "base64" else v.tolist()}
            for i, v in enumerate(out)]
    return {"object": "list", "data": data, "model": body.model, "usage": {"prompt_tokens": tokens, "total_tokens": tokens}}


@app.post("/v1/rerank")
def rerank(body: RerankIn):
    t = time.time()
    scores: list[float] = []
    with torch.inference_mode():
        for i in range(0, len(body.documents), BATCH):
            docs = body.documents[i:i + BATCH]
            enc = rerank_tok([body.query] * len(docs), docs, padding=True, truncation=True, max_length=MAX_LEN, return_tensors="pt").to(DEVICE)
            scores += torch.sigmoid(rerank_model(**enc).logits.float().view(-1)).cpu().tolist()
    order = sorted(range(len(scores)), key=lambda i: -scores[i])[:body.top_n or len(scores)]
    return {"model": body.model, "results": [{"index": i, "relevance_score": scores[i]} for i in order],
            "latency_ms": int((time.time() - t) * 1000)}
