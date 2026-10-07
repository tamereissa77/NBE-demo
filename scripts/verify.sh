#!/usr/bin/env bash
# Smoke test through the gateway, plus proof that services cannot reach the internet.
set -uo pipefail
PORT=${NBE_PORT:-8200}
BASE="http://localhost:${PORT}"
fail=0
pass() { printf '  \033[32mPASS\033[0m %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=1; }

# Wait for the stack to settle (e.g. right after `make up` or a portal rebuild)
for _ in $(seq 30); do curl -fsS -o /dev/null "$BASE/" && curl -fsS -o /dev/null "$BASE/api/d7/health" && break; sleep 1; done

echo "Portal"
curl -fsS "$BASE/" | grep -q 'id="root"' && pass "portal / served" || bad "portal / not served"
curl -fsS "$BASE/d4" | grep -q 'id="root"' && pass "SPA deep link /d4" || bad "SPA deep link /d4"
curl -fsS -o /dev/null "$BASE/nbe-logo-web.png" && pass "NBE logo asset" || bad "NBE logo asset"

echo "Demo APIs"
for i in 1 2 3 4 5 6 7; do
  body=$(curl -fsS "$BASE/api/d$i/health" 2>/dev/null)
  echo "$body" | grep -q '"status":"ok"' && pass "d$i health ok" || bad "d$i health: ${body:-no response}"
done

echo "Offline by construction"
if docker exec nbe-d1 python -c "import urllib.request; urllib.request.urlopen('https://huggingface.co', timeout=5)" >/dev/null 2>&1; then
  bad "nbe-d1 reached the internet (nbe-core must be internal)"
else
  pass "nbe-d1 cannot reach the internet"
fi

echo "Platform (models, retrieval, guardrails, mock bank, documents)"
if docker inspect -f '{{.State.Running}}' nbe-llm 2>/dev/null | grep -q true; then
  docker run --rm --network nbe-core --env-file .env -e LLM_GATEWAY_URL=http://nbe-llmgw:4000/v1 \
    -v "$(pwd)/tests:/tests:ro" nbe-d1:${IMAGE_TAG:-latest} python /tests/platform_check.py | sed 's/^/  /' || fail=1
else
  bad "model servers not running (make up)"
fi

[ $fail -eq 0 ] && echo "verify: all checks passed" || { echo "verify: FAILED"; exit 1; }
