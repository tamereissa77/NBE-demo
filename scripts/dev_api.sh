#!/usr/bin/env bash
# TEMPORARY development helper for a workstation that cannot run the workhorse LLM locally.
# Starts only what D2 needs, with the chat model on an external API (docker-compose.api.yml).
# Do not use on the GB10: there `make up` starts everything locally. `make up` is not used here
# because its preflight stops every other container holding GPU memory.
#
#   scripts/dev_api.sh models   download bge-m3 and bge-reranker-v2-m3 into $MODELS_DIR (once)
#   scripts/dev_api.sh up       data services, embeddings, reranker, model gateway, guardrails, D2, portal, gateway; then load D2
#   scripts/dev_api.sh ingest   reload D2's collections (after changing seed data or chunking)
#   scripts/dev_api.sh golden   run both D2 golden sets (procedures, scanned corpus) against the running service
#   scripts/dev_api.sh down     stop and remove the containers (data volumes kept)
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "no .env: run 'make .env', then append .env.api.example and fill it in" >&2; exit 1; }
set -a; . ./.env; set +a
C="docker compose -f docker-compose.yml -f docker-compose.api.yml --profile core"
BASE="http://localhost:${NBE_PORT:-8200}/api/d2"

case "${1:-up}" in
  models)
    mkdir -p "${MODELS_DIR:?set MODELS_DIR in .env}"
    docker run --rm -v "$MODELS_DIR:/models" python:3.12-slim bash -c '
      set -e; pip install -q huggingface_hub
      hf download BAAI/bge-m3 --local-dir /models/bge-m3 --exclude "onnx/*" --exclude "*.onnx"
      hf download BAAI/bge-reranker-v2-m3 --local-dir /models/bge-reranker-v2-m3'
    ;;
  up)
    $C up -d --wait nbe-postgres nbe-qdrant
    $C up -d --wait nbe-embed
    $C up -d --wait nbe-rerank
    $C up -d --wait --build nbe-llmgw nbe-guardrails nbe-d2 nbe-portal nbe-gateway
    "$0" ingest
    echo; echo "Portal: http://localhost:${NBE_PORT:-8200}/d2"
    ;;
  ingest)
    curl -fsS -X POST --max-time 900 "$BASE/admin/ingest"; echo
    ;;
  golden)
    for t in golden_d2 golden_d2_circulars; do
      echo "== $t"
      docker run --rm --network nbe-core -v "$(pwd)/tests:/tests:ro" -v "$(pwd)/data:/data:ro" nbe-d2:latest \
        python "/tests/$t.py" http://nbe-d2:8000
    done
    ;;
  down)
    $C down
    ;;
  *)
    sed -n '2,12p' "$0"; exit 1
    ;;
esac
