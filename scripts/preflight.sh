#!/usr/bin/env bash
# Free the shared GB10 for the NBE demos (PLAN.md §6).
# vLLM sizes itself from memory that is free when it starts, and stopping one hog lets the
# next one grow, so every non-NBE GPU consumer is stopped in a single `docker stop`.
set -euo pipefail

declare -A victims=()

# 1. Known neighbours on this box
for c in gemma4-gb10-vllm; do
  [ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null)" = "true" ] && victims[$c]=1
done
while read -r c; do [ -n "$c" ] && victims[$c]=1; done < <(
  docker ps --filter label=com.docker.compose.project.working_dir=/etc/galene --format '{{.Names}}')

# 2. Anything else holding GPU memory that is not part of this project
while IFS=, read -r pid _; do
  pid=${pid// /}; [ -z "$pid" ] && continue
  cid=$(grep -oE '[0-9a-f]{64}' "/proc/$pid/cgroup" 2>/dev/null | head -1 || true)
  [ -z "$cid" ] && continue
  name=$(docker inspect -f '{{.Name}}' "$cid" 2>/dev/null | sed 's#^/##' || true)
  [ -n "$name" ] && [[ "$name" != nbe-* ]] && victims[$name]=1
done < <(nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader 2>/dev/null || true)

if [ ${#victims[@]} -gt 0 ]; then
  echo "preflight: stopping non-NBE GPU consumers together: ${!victims[*]}"
  docker stop "${!victims[@]}" >/dev/null
else
  echo "preflight: no competing GPU consumers running"
fi

if docker inspect -f '{{.State.Running}}' nbe-llm 2>/dev/null | grep -q true; then
  echo "preflight: NBE model servers already running (see 'make gpu')"
  exit 0
fi

avail=$(free -g | awk '/^Mem:/ {print $7}')
need=${NBE_MIN_FREE_GB:-95}
echo "preflight: ${avail} GB unified memory available (budget needs ~${need} GB)"
if [ "$avail" -lt "$need" ]; then
  echo "preflight: WARNING - below budget; check 'make gpu' and 'free -g' before starting models" >&2
  [ "${STRICT:-0}" = "1" ] && exit 1
fi
exit 0
