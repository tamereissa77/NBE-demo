# NeMo Guardrails check service. annoy builds from source on aarch64, hence build-essential.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 FASTEMBED_CACHE_PATH=/opt/fastembed
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY services/guardrails/requirements.txt /srv/requirements.txt
RUN pip install -r /srv/requirements.txt
# Bake NeMo's default embedding model into the image so nothing is fetched at runtime (offline)
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('sentence-transformers/all-MiniLM-L6-v2')" \
    && chmod -R a+rX /opt/fastembed
COPY services/guardrails/app /srv/app
RUN useradd --system --uid 10001 nbe
USER nbe
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
