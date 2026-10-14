#!/usr/bin/env bash
# Start the Efada build on the GB10 (docker-compose.gb10.yml): every model on the box, nothing hosted.
# Models start one at a time, vLLM first: it sizes itself from the memory that is free when it starts.
#   MODE=show (default)   workhorse, embeddings, reranker, hero (gpt-oss-20b), Egyptian voice, document reader, SDXL
#   MODE=core             the same without SDXL
#   VOICE=0 / DOCVLM=0 / HERO=0   leave the voice services / the document reader / the hero model off
#   HUB=1                 also serve the models to the team's workstations (docker-compose.hub.yml): development only
#   EXTRACT=1             also start D2's document extraction (Chandra OCR, about 10 GB); it is stopped by hand
#   BUILD=1               rebuild images first (missing images are always built)
# Unlike `make up`, this never stops another team's containers: it reports them and the free memory.
set -euo pipefail
cd "$(dirname "$0")/.."
MODE=${MODE:-show}
C="docker compose -f docker-compose.yml -f docker-compose.d2-extract.yml -f docker-compose.gb10.yml"
[ "${HUB:-0}" = "1" ] && C="$C -f docker-compose.hub.yml"
C="$C --profile core --profile image --profile extract --profile hero"
BUILD_FLAG=""
[ "${BUILD:-0}" = "1" ] && BUILD_FLAG="--build"
env_value() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- || true; }
NBE_PORT=${NBE_PORT:-$(env_value NBE_PORT)}
PROJECT=${COMPOSE_PROJECT_NAME:-$(env_value COMPOSE_PROJECT_NAME)}
PROJECT=${PROJECT:-nbe}

step() { printf '\n== %s\n' "$*"; }

# Container names are the same in every checkout of this project (nbe-llm, nbe-d1, ...), so two builds
# cannot run together. Another team's build is theirs to stop.
others=$(docker ps --filter name=nbe- --format '{{.Names}} {{.Label "com.docker.compose.project"}}' | awk -v p="$PROJECT" '$2 != p {print $1}' | xargs)
if [ -n "$others" ]; then
  echo "Another build of this project is running (not project '$PROJECT'): $others" >&2
  echo "Stop it from its own folder (make down) and start again." >&2
  exit 1
fi

if ! docker inspect -f '{{.State.Running}}' nbe-llm 2>/dev/null | grep -q true; then
  gpu_users=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | while read -r pid; do
    cid=$(grep -oE '[0-9a-f]{64}' "/proc/$pid/cgroup" 2>/dev/null | head -1 || true)
    [ -n "$cid" ] && docker inspect -f '{{.Name}}' "$cid" 2>/dev/null | sed 's#^/##' || true
  done | { grep -v '^nbe-' || true; } | sort -u | xargs)
  [ -n "$gpu_users" ] && echo "Other containers are using the GPU: $gpu_users"
  avail=$(free -g | awk '/^Mem:/ {print $7}')
  need=${NBE_MIN_FREE_GB:-110}
  echo "${avail} GB of memory available (this build needs about ${need} GB)"
  if [ "$avail" -lt "$need" ]; then
    echo "Not enough free memory to start the models. Ask the owner of the containers above, or set NBE_MIN_FREE_GB." >&2
    exit 1
  fi
fi

# The demo services run as their own user: the two folders they write to must be open to it
mkdir -p data/uploads/d1 data/generated/d3/banners && chmod 777 data/uploads/d1 data/generated/d3/banners

# The active customer (make customer NAME=...): a fresh checkout starts with NBE. Its corpus, rendered with the
# bank's name, is what the services mount as /data/seed.
[ -f data/customer.json ] || python3 scripts/apply_customer.py "${CUSTOMER:-nbe}"
[ -d data/seed-active ] || python3 scripts/apply_customer.py --seed-only
# The brand is baked into the portal image: rebuild it (cached, seconds) so it always shows the active customer
$C build nbe-portal >/dev/null

step "data services"
$C up -d $BUILD_FLAG --wait nbe-postgres nbe-qdrant

step "core models: workhorse -> embeddings -> reranker (one at a time)"
$C up -d --wait nbe-llm
$C up -d --wait nbe-embed
$C up -d --wait nbe-rerank

if [ "${HERO:-1}" = "1" ]; then
  step "hero model (gpt-oss-20b)"
  $C up -d --wait nbe-hero
fi

if [ "${DOCVLM:-1}" = "1" ]; then
  LIBS=$(env_value NBE_DOCVLM_LIBS)
  [ -d "${LIBS:-ops/docvlm-libs}/transformers" ] || {
    echo "The document reader's packages are missing: run scripts/docvlm_libs.sh once (needs internet), or DOCVLM=0." >&2; exit 1; }
  step "document reader (Qwen3-VL + adapter)"
  $C up -d $BUILD_FLAG --wait nbe-docvlm
fi
if [ "${VOICE:-1}" = "1" ]; then
  step "voice (QwenCleo-ASR + VoiceTut-TTS)"
  $C up -d $BUILD_FLAG --wait nbe-qwencleo nbe-voicetut
fi
if [ "$MODE" = "show" ]; then
  step "image (SDXL)"
  $C up -d $BUILD_FLAG --wait nbe-sdxl
fi

if [ "${EXTRACT:-0}" = "1" ]; then
  step "D2 document extraction (Chandra OCR)"
  $C up -d $BUILD_FLAG --wait nbe-d2-extract
fi

step "platform and demo services"
$C up -d $BUILD_FLAG --wait nbe-llmgw nbe-mockbank nbe-guardrails nbe-docling nbe-eval \
  nbe-d1 nbe-d2 nbe-d3 nbe-d4 nbe-d5 nbe-d6 nbe-d7 nbe-portal nbe-gateway

# First start on a fresh box, or the customer changed since the data was last loaded (make customer)
fresh() { ! cmp -s data/customer.json data/generated/.loaded-customer.json; }
if [ ! -f data/generated/d1/manifest.json ] || [ ! -f data/generated/d3/customers.csv ] || fresh; then
  step "generating synthetic data (first run, or a new customer)"
  make -s data
  python3 scripts/apply_customer.py --seed-only
fi
if ! curl -fsS "http://localhost:${NBE_PORT:-8200}/api/d2/documents" | grep -q procedure || \
   [ "$(docker exec nbe-qdrant bash -c 'exec 3<>/dev/tcp/127.0.0.1/6333; printf "GET /collections/d2_procedures HTTP/1.0\r\n\r\n" >&3; head -1 <&3' 2>/dev/null | grep -c 200)" = "0" ] || fresh; then
  step "loading demo data (first run, or a new customer)"
  NBE_PORT=${NBE_PORT:-8200} scripts/ingest.sh && cp data/customer.json data/generated/.loaded-customer.json
fi

if [ "${HUB:-0}" = "1" ]; then
  step "model hub for the workstations"
  $C up -d --wait nbe-hub
  HUB_PORT=$(env_value NBE_HUB_PORT)
  echo "Model hub: http://$(hostname -I | tr ' ' '
' | grep -m1 '^100\.' || hostname):${HUB_PORT:-8035}  (key: NBE_HUB_KEY in .env)"
fi

echo; echo "Portal: http://localhost:${NBE_PORT:-8200}"
