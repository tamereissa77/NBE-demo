# Synthetic data generation (PLAN.md Phase 3). Pillow with raqm/FriBiDi shapes Arabic; Noto fonts cover
# Arabic (Naskh, Kufi, Sans) and Latin. pandas/numpy are installed so D6 can index their real docstrings.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends libfribidi0 fonts-noto-core fonts-dejavu-core fonts-hosny-amiri \
    && rm -rf /var/lib/apt/lists/*
COPY packages/nbe_core /tmp/nbe_core
RUN pip install /tmp/nbe_core pillow numpy pandas pyyaml && rm -rf /tmp/nbe_core
WORKDIR /repo
CMD ["python", "-m", "data.generators.run"]
