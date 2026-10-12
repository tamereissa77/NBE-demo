# D2 extraction service (GPU). Same base as nbe-working's extraction service image by default.
# Build context: this folder (see docker-compose.yml here, and docker-compose.d2-extract.yml at the repo root).
#
# Two build arguments, for a machine where the defaults do not give a working GPU build of torch
# (nbe-working's image was only ever built for an x86 workstation with an RTX 5090):
#   BASE_IMAGE   any image with Python 3.10+ and pip, for example one that already ships CUDA torch
#   TORCH_INDEX  the wheel index torch is installed from; empty = whatever pip resolves
ARG BASE_IMAGE=nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-dev python3-pip curl libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* && ln -sf /usr/bin/python3 /usr/bin/python

WORKDIR /srv
COPY requirements.txt /srv/requirements.txt
ARG TORCH_INDEX=
RUN if [ -n "$TORCH_INDEX" ]; then pip install torch torchvision --index-url "$TORCH_INDEX"; fi \
 && pip install -r /srv/requirements.txt

COPY app /srv/app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
