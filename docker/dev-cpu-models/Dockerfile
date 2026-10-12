# TEMPORARY development image: bge-m3 and bge-reranker-v2-m3 on CPU (see server.py).
# Built and used only through docker-compose.api.yml; the GB10 serves both models with vLLM.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
# CPU wheels by default. docker-compose.gpu-models.yml builds a second image from this file with the CUDA wheels.
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
RUN pip install torch --index-url ${TORCH_INDEX} \
 && pip install "sentence-transformers>=3.3" "fastapi>=0.115" "uvicorn>=0.30"

WORKDIR /srv
COPY server.py /srv/server.py
EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
