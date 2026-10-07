#!/usr/bin/env bash
# Start the NBE stack in a memory-safe order (PLAN.md §6). vLLM sizes its KV cache from memory
# that is free when it starts, so model servers start one at a time, each waiting for healthy.
#   MODE=show (default): core + voice + image (live D3 banners)
#   MODE=full:           show + Gemma 4 31B quality model (optional for D5; the Arabic gate provisionally drops it)
#   MODE=core:           core models only
set -euo pipefail
cd "$(dirname "$0")/.."
MODE=${MODE:-show}
C="docker compose --profile core --profile quality --profile voice --profile image --profile hero --profile eval"

step() { printf '\n== %s\n' "$*"; }

# Bind-mounted data folders must exist (and be writable) before any container starts; otherwise Docker
# creates them as root on a fresh checkout and the data generators cannot write into them.
mkdir -p data/generated/d3/banners && chmod 777 data/generated/d3/banners 2>/dev/null || true

step "data services"
$C up -d --wait nbe-postgres nbe-qdrant

step "core models: workhorse -> embeddings -> reranker (sequential)"
$C up -d --wait nbe-llm
$C up -d --wait nbe-embed
$C up -d --wait nbe-rerank

if [ "$MODE" = "full" ]; then
  step "quality model (Gemma 4 31B NVFP4)"
  $C up -d --wait nbe-llm-q
fi
if [ "$MODE" = "show" ] || [ "$MODE" = "full" ]; then
  step "voice (whisper-large-v3 + Piper) and image (SDXL)"
  $C up -d --wait nbe-asr nbe-tts nbe-sdxl
fi

step "platform and demo services"
docker compose up -d --wait

# First start on a fresh box: generate synthetic data and load every demo
if [ ! -f data/generated/d1/manifest.json ] || [ ! -f data/generated/d3/customers.csv ]; then
  step "generating synthetic data (first run)"
  make -s data
fi
if ! curl -fsS "http://localhost:${NBE_PORT:-8200}/api/d2/documents" | grep -q procedure || \
   [ "$(docker exec nbe-qdrant bash -c 'exec 3<>/dev/tcp/127.0.0.1/6333; printf "GET /collections/d2_procedures HTTP/1.0\r\n\r\n" >&3; head -1 <&3' 2>/dev/null | grep -c 200)" = "0" ]; then
  step "loading demo data (first run)"
  scripts/ingest.sh
fi

echo; echo "Portal: http://localhost:${NBE_PORT:-8200}"
