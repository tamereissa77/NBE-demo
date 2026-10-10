#!/usr/bin/env bash
# Start the stack on a workstation (docker-compose.local.yml): hosted LLM, local embeddings, reranker and voice.
#   DEMOS="d4" scripts/up_local.sh     start only some demos (default: all seven)
#   VOICE=0 scripts/up_local.sh        leave the voice services (VoiceTut-TTS, QwenCleo-ASR) off
#   DEV=1 scripts/up_local.sh          mount service code from the checkout (docker-compose.dev.yml): no rebuilds
#   BUILD=1 scripts/up_local.sh        rebuild images first (missing images are always built)
set -euo pipefail
cd "$(dirname "$0")/.."
C="docker compose -f docker-compose.yml -f docker-compose.local.yml"
if [ "${DEV:-0}" = "1" ]; then
  C="$C -f docker-compose.dev.yml"
  # The dev file serves the portal from the checkout; an unbuilt one would be an empty site
  [ -f services/portal/dist/index.html ] || { echo "DEV=1 needs a built portal: (cd services/portal && npm ci && npm run build)" >&2; exit 1; }
fi
BUILD_FLAG=""
[ "${BUILD:-0}" = "1" ] && BUILD_FLAG="--build"
DEMOS=${DEMOS:-d1 d2 d3 d4 d5 d6 d7}
NBE_PORT=${NBE_PORT:-$(grep -E '^NBE_PORT=' .env 2>/dev/null | cut -d= -f2)}

step() { printf '\n== %s\n' "$*"; }

# Docker's disk only grows, and a build costs several times the image size (layers, build cache and, on
# WSL, the Windows pagefile). Refuse to build when the drive that holds it is short: a full system drive
# takes Docker and everything else on the machine down with it.
MIN_FREE_GB=${NBE_MIN_FREE_GB:-20}
GUARD_PATH=${NBE_DISK_GUARD_PATH:-$([ -d /mnt/c ] && echo /mnt/c || echo /var/lib/docker)}
free_gb=$(df -BG --output=avail "$GUARD_PATH" 2>/dev/null | tail -1 | tr -dc '0-9')
if [ -n "$free_gb" ] && [ "$free_gb" -lt "$MIN_FREE_GB" ]; then
  if [ -n "$BUILD_FLAG" ]; then
    echo "Only ${free_gb} GB free on $GUARD_PATH (need ${MIN_FREE_GB}): not building. Free space, or lower NBE_MIN_FREE_GB." >&2
    exit 1
  fi
  echo "Warning: only ${free_gb} GB free on $GUARD_PATH; a missing image may not fit if it has to be built." >&2
fi

step "data services, model gateway, embeddings + reranker"
$C up -d $BUILD_FLAG --wait nbe-postgres nbe-qdrant nbe-llmgw nbe-retrieval

PLATFORM="nbe-mockbank nbe-guardrails"
[ "${VOICE:-1}" = "1" ] && PLATFORM="$PLATFORM nbe-voicetut nbe-qwencleo"
case " $DEMOS " in *" d2 "*|*" d5 "*|*" d6 "*) PLATFORM="$PLATFORM nbe-docling" ;; esac   # only these read uploads
# D1 reads real documents with the fine-tuned Qwen3-VL (about 17.5 GB of GPU memory); DOCVLM=0 leaves it off
case " $DEMOS " in *" d1 "*) [ "${DOCVLM:-1}" = "1" ] && PLATFORM="$PLATFORM nbe-docvlm" ;; esac

step "platform and demo services: $DEMOS"
$C up -d $BUILD_FLAG --wait $PLATFORM $(printf 'nbe-%s ' $DEMOS) nbe-portal nbe-gateway

echo; echo "Portal: http://localhost:${NBE_PORT:-8200}"
