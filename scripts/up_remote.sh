#!/usr/bin/env bash
# Start the apps and the data on a workstation, with every model on the GB10 (docker-compose.remote.yml).
# The GB10 must be serving them: HUB=1 scripts/up_gb10.sh there. In .env here: NBE_HUB_URL and NBE_HUB_KEY.
#   DEMOS="d1 d4" scripts/up_remote.sh   start only some demos (default: all seven)
#   BUILD=1 scripts/up_remote.sh         rebuild images first (missing images are always built)
set -euo pipefail
cd "$(dirname "$0")/.."
C="docker compose -f docker-compose.yml -f docker-compose.d2-extract.yml -f docker-compose.remote.yml"
BUILD_FLAG=""
[ "${BUILD:-0}" = "1" ] && BUILD_FLAG="--build"
DEMOS=${DEMOS:-d1 d2 d3 d4 d5 d6 d7}
env_value() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- || true; }
NBE_PORT=${NBE_PORT:-$(env_value NBE_PORT)}
HUB=${NBE_HUB_URL:-$(env_value NBE_HUB_URL)}

step() { printf '\n== %s\n' "$*"; }

[ -n "$HUB" ] || { echo "Set NBE_HUB_URL and NBE_HUB_KEY in .env (see .env.example)" >&2; exit 1; }
curl -fsS --max-time 8 "$HUB/health" >/dev/null || {
  echo "The model hub at $HUB does not answer. On the GB10: HUB=1 scripts/up_gb10.sh" >&2; exit 1; }

# Docker's disk only grows; on WSL it sits on the system drive. Refuse to build when that drive is short.
MIN_FREE_GB=${NBE_MIN_FREE_GB:-20}
GUARD_PATH=${NBE_DISK_GUARD_PATH:-$([ -d /mnt/c ] && echo /mnt/c || echo /var/lib/docker)}
free_gb=$(df -BG --output=avail "$GUARD_PATH" 2>/dev/null | tail -1 | tr -dc '0-9')
if [ -n "$free_gb" ] && [ "$free_gb" -lt "$MIN_FREE_GB" ]; then
  [ -z "$BUILD_FLAG" ] || { echo "Only ${free_gb} GB free on $GUARD_PATH (need ${MIN_FREE_GB}): not building." >&2; exit 1; }
  echo "Warning: only ${free_gb} GB free on $GUARD_PATH; a missing image may not fit if it has to be built." >&2
fi

# The demo services run as their own user: the folders they write to must be open to it
mkdir -p data/uploads/d1 data/generated/d3/banners && chmod 777 data/uploads/d1 data/generated/d3/banners 2>/dev/null || true

step "data services, and the link to the models on the GB10"
$C up -d $BUILD_FLAG --wait nbe-postgres nbe-qdrant nbe-llmgw

step "platform and demo services: $DEMOS"
$C up -d $BUILD_FLAG --wait nbe-mockbank nbe-guardrails nbe-docling nbe-eval $(printf 'nbe-%s ' $DEMOS) nbe-portal nbe-gateway

# First start on a fresh machine: generate synthetic data and load every demo (embeddings come from the GB10)
if [ ! -f data/generated/d1/manifest.json ] || [ ! -f data/generated/d3/customers.csv ]; then
  step "generating synthetic data (first run)"
  make -s data
fi
if ! curl -fsS "http://localhost:${NBE_PORT:-8200}/api/d2/documents" | grep -q procedure || \
   [ "$(docker exec nbe-qdrant bash -c 'exec 3<>/dev/tcp/127.0.0.1/6333; printf "GET /collections/d2_procedures HTTP/1.0\r\n\r\n" >&3; head -1 <&3' 2>/dev/null | grep -c 200)" = "0" ]; then
  step "loading demo data (first run)"
  NBE_PORT=${NBE_PORT:-8200} scripts/ingest.sh
fi

echo; echo "Portal: http://localhost:${NBE_PORT:-8200}   (models: $HUB)"
