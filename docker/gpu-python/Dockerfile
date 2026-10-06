# GPU Python services (ASR, SDXL) on NVIDIA's vLLM image: it already ships PyTorch built for
# GB10 (sm_121, aarch64), which avoids the aarch64 wheel gaps flagged in PLAN.md §9.
FROM nvcr.io/nvidia/vllm:26.05-py3

ARG SERVICE
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY services/${SERVICE}/requirements.txt /srv/requirements.txt
# Constrain torch so a dependency can never replace NVIDIA's GB10 build
RUN pip freeze | grep -iE '^(torch|torchvision|torchaudio|transformers)==' > /tmp/constraints.txt; \
    pip install -c /tmp/constraints.txt -r /srv/requirements.txt

WORKDIR /srv
COPY services/${SERVICE}/app /srv/app
EXPOSE 8000
ENTRYPOINT []
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
