#!/usr/bin/env bash
# Prove the demo is offline by construction (PLAN.md §0):
#  1. every NBE container except the gateway is attached only to the internal network nbe-core
#  2. from inside those containers, the internet is unreachable
#  3. model servers run with HF_HUB_OFFLINE=1
set -uo pipefail
fail=0
pass() { printf '  \033[32mPASS\033[0m %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=1; }

echo "Networks"
for c in $(docker ps --filter name=nbe- --format '{{.Names}}' | sort); do
  nets=$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$c" | xargs)
  if [ "$c" = "nbe-gateway" ]; then
    [ "$nets" = "nbe-core nbe-edge" ] || [ "$nets" = "nbe-edge nbe-core" ] && pass "$c on nbe-edge + nbe-core (the only published port)" || bad "$c networks: $nets"
  else
    [ "$nets" = "nbe-core" ] && pass "$c only on nbe-core" || bad "$c networks: $nets"
  fi
done
[ "$(docker network inspect -f '{{.Internal}}' nbe-core)" = "true" ] && pass "nbe-core is internal (no route out)" || bad "nbe-core is not internal"

echo "Egress attempts from inside (must all fail)"
for c in nbe-d1 nbe-llmgw nbe-llm nbe-guardrails; do
  docker inspect "$c" >/dev/null 2>&1 || continue
  if docker exec "$c" sh -c 'command -v curl >/dev/null && curl -s --max-time 5 -o /dev/null https://huggingface.co || python3 -c "import urllib.request;urllib.request.urlopen(\"https://huggingface.co\",timeout=5)"' >/dev/null 2>&1; then
    bad "$c reached the internet"
  else
    pass "$c cannot reach the internet"
  fi
done

echo "Model servers offline mode"
for c in $(docker ps --filter name=nbe- --format '{{.Names}}' | grep -E '^nbe-(llm|llm-q|embed|rerank|hero|asr|ref-.*)$'); do
  docker exec "$c" printenv HF_HUB_OFFLINE 2>/dev/null | grep -q 1 && pass "$c HF_HUB_OFFLINE=1" || bad "$c HF_HUB_OFFLINE not set"
done
[ $fail -eq 0 ] && echo "offline-check: passed" || { echo "offline-check: FAILED"; exit 1; }
