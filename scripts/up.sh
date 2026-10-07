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

echo; echo "Portal: http://localhost:${NBE_PORT:-8200}"
