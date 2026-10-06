#!/usr/bin/env bash
# Download NBE demo model weights into /opt/models (the only online step; see PLAN.md §5).
# Pass one pattern per --include/--exclude flag (the hf CLI reads extra words as file names).
# Runs inside a container so nothing is installed on the host. Usage: HF_TOKEN=... scripts/download_models.sh
set -euo pipefail
MODELS_DIR="${MODELS_DIR:-/opt/models}"
docker run --rm -e HF_TOKEN="${HF_TOKEN:?HF_TOKEN required}" -e HF_XET_HIGH_PERFORMANCE=1 \
  -v "${MODELS_DIR}:/models" python:3.12-slim bash -c '
set -e
pip install -q huggingface_hub
dl() { echo "=== $1 -> /models/$2"; hf download "$1" --local-dir "/models/$2" "${@:3}"; }
dl nvidia/Gemma-4-31B-IT-NVFP4               Gemma-4-31B-IT-NVFP4
dl BAAI/bge-m3                               bge-m3 --exclude "onnx/*" --exclude "*.onnx"
dl BAAI/bge-reranker-v2-m3                   bge-reranker-v2-m3
dl stabilityai/stable-diffusion-xl-base-1.0  sdxl-base-1.0 --include "*.json" --include "*.txt" --include "*fp16.safetensors"
dl openai/gpt-oss-120b                      gpt-oss-120b --include "model-*.safetensors" --include "*.json" --include "chat_template.jinja"
# Arabic-gate reference from the NBE model list (PLAN.md §5); Llama-3 is gated for this account. No apostrophes in this block: it is single-quoted.
dl mistralai/Mistral-7B-Instruct-v0.3         Mistral-7B-Instruct-v0.3 --include "model-*.safetensors" --include "*.json" --include "tokenizer*"
dl rhasspy/piper-voices                      piper-voices --include "ar/ar_JO/kareem/medium/*" --include "en/en_US/lessac/medium/*" --include "voices.json"
echo "=== all downloads complete"; du -sh /models/Gemma-4-31B-IT-NVFP4 /models/bge-m3 /models/bge-reranker-v2-m3 /models/sdxl-base-1.0 /models/piper-voices /models/gpt-oss-120b /models/Mistral-7B-Instruct-v0.3
'
