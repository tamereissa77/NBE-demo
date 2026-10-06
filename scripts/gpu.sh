#!/usr/bin/env bash
# GPU memory per container (nvidia-smi PID -> cgroup -> container). On GB10 unified memory,
# cgroup memory stats do not include GPU allocations, so this is the reliable view.
set -uo pipefail
printf '%-36s %10s  %s\n' CONTAINER USED_MIB PID
nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits 2>/dev/null |
while IFS=, read -r pid mem; do
  pid=${pid// /}; mem=${mem// /}
  cid=$(grep -oE '[0-9a-f]{64}' "/proc/$pid/cgroup" 2>/dev/null | head -1)
  name=$( [ -n "$cid" ] && docker inspect -f '{{.Name}}' "$cid" 2>/dev/null | sed 's#^/##' || echo "(host) $(ps -o comm= -p "$pid")")
  printf '%-36s %10s  %s\n' "$name" "$mem" "$pid"
done
echo; free -g | awk 'NR==1 || /^Mem:/'
