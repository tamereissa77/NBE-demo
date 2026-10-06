#!/usr/bin/env bash
# Download NBE demo model weights into /opt/models (the only online step; see PLAN.md §5).
# Runs inside a container so nothing is installed on the host. Usage: HF_TOKEN=... scripts/download_models.sh
set -euo pipefail
MODELS_DIR="${MODELS_DIR:-/opt/models}"
docker run --rm -e HF_TOKEN="${HF_TOKEN:?HF_TOKEN required}" -e HF_HUB_ENABLE_HF_TRANSFER=1 \
  -v "${MODELS_DIR}:/models" python:3.12-slim bash -c '
set -e
pip install -q "huggingface_hub[hf_transfer]"
dl() { echo "=== $1 -> /models/$2"; hf download "$1" --local-dir "/models/$2" "${@:3}"; }
dl nvidia/Gemma-4-31B-IT-NVFP4               Gemma-4-31B-IT-NVFP4
dl BAAI/bge-m3                               bge-m3 --exclude "onnx/*" "*.onnx"
dl BAAI/bge-reranker-v2-m3                   bge-reranker-v2-m3
dl stabilityai/stable-diffusion-xl-base-1.0  sdxl-base-1.0 --include "*.json" "*.txt" "*fp16.safetensors"
dl rhasspy/piper-voices                      piper-voices --include "ar/ar_JO/kareem/medium/*" "en/en_US/lessac/medium/*" "voices.json"
echo "=== all downloads complete"; du -sh /models/Gemma-4-31B-IT-NVFP4 /models/bge-m3 /models/bge-reranker-v2-m3 /models/sdxl-base-1.0 /models/piper-voices
'
