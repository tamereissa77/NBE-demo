# Docling on CPU: PyTorch CPU wheels for aarch64, layout/table models baked in at build (offline at runtime).
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/opt/hf DOCLING_ARTIFACTS_PATH=/opt/docling-models
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
RUN pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
COPY services/docling/requirements.txt /srv/requirements.txt
RUN pip install -r /srv/requirements.txt
RUN docling-tools models download -o /opt/docling-models layout tableformer && chmod -R a+rX /opt/docling-models
COPY services/docling/app /srv/app
RUN useradd --system --uid 10001 nbe
USER nbe
ENV HF_HUB_OFFLINE=1
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
