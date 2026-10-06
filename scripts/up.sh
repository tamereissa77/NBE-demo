#!/usr/bin/env bash
# Start the NBE stack in a memory-safe order (PLAN.md §6). vLLM sizes its KV cache from memory
# that is free when it starts, so model servers start one at a time, each waiting for healthy.
#   MODE=show (default): core + quality + voice     (image is switched on separately: make image-on)
#   MODE=core:           core models only
set -euo pipefail
cd "$(dirname "$0")/.."
MODE=${MODE:-show}
C="docker compose --profile core --profile quality --profile voice --profile image --profile hero"

step() { printf '\n== %s\n' "$*"; }

step "data services"
$C up -d --wait nbe-postgres nbe-qdrant

step "core models: workhorse -> embeddings -> reranker (sequential)"
$C up -d --wait nbe-llm
$C up -d --wait nbe-embed
$C up -d --wait nbe-rerank

if [ "$MODE" = "show" ]; then
  step "quality model (Gemma 4 31B NVFP4)"
  $C up -d --wait nbe-llm-q
  step "voice (whisper-large-v3 + Piper)"
  $C up -d --wait nbe-asr nbe-tts
fi

step "platform and demo services"
docker compose up -d --wait

echo; echo "Portal: http://localhost:${NBE_PORT:-8200}"
