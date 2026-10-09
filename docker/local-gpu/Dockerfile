# GPU services on a workstation (docker-compose.local.yml): embeddings + reranker, VoiceTut-TTS and QwenCleo-ASR.
# One recipe for all three, like docker/gpu-python on the GB10: they share PyTorch and the CUDA libraries,
# so the heavy layers are built and stored once and SERVICE only selects the app. Models are read from the
# local model store at run time; nothing is downloaded.
#
# BASE: an image that already holds these dependencies (an earlier build of this recipe), to add only what
# changed instead of reinstalling about 11 GB.
ARG BASE=python:3.12-slim
FROM ${BASE}
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
USER root
RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1 ffmpeg sox build-essential && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY services/tts_voicetut/requirements.txt /srv/requirements/tts_voicetut.txt
COPY services/embed/requirements.txt /srv/requirements/embed.txt
RUN pip install -r /srv/requirements/tts_voicetut.txt -r /srv/requirements/embed.txt
# Speech-to-text needs transformers 4.57 while VoiceTut needs 5.x, so it gets its own environment.
# --system-site-packages lets it use the PyTorch installed above instead of a second copy; the service
# runs with /opt/asr/bin/python (see the nbe-qwencleo command in docker-compose.local.yml).
COPY services/asr_qwencleo/requirements.txt /srv/requirements/asr_qwencleo.txt
RUN python -m venv --system-site-packages /opt/asr && /opt/asr/bin/pip install -r /srv/requirements/asr_qwencleo.txt

# Everything above is identical for the three services
ARG SERVICE
COPY services/${SERVICE}/app /srv/app
RUN id nbe >/dev/null 2>&1 || useradd --system --create-home --uid 10001 nbe
USER nbe
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
