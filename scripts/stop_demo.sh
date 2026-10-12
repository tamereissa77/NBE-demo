#!/usr/bin/env bash
# Stop every running demo stack (any bank), from any checkout:   scripts/stop_demo.sh [project-to-keep]
# `make down` uses it, so it works no matter which bank's folder you are in. Containers are removed;
# data volumes and images are kept. scripts/switch_brand.sh passes the bank it is about to start.
set -euo pipefail
keep="${1:-}"
PROFILES="--profile core --profile quality --profile voice --profile image --profile hero --profile eval --profile tools"
stopped=0
for proj in $(docker ps --format '{{.Label "com.docker.compose.project"}}' | sort -u); do
  { [ -z "$proj" ] || [ "$proj" = "$keep" ]; } && continue
  wd=$(docker ps --filter "label=com.docker.compose.project=$proj" --format '{{.Label "com.docker.compose.project.working_dir"}}' | head -1)
  if [ -f "$wd/docker-compose.yml" ] && grep -q 'container_name: nbe-gateway' "$wd/docker-compose.yml"; then
    echo "== stopping the $proj stack ($wd)"
    (cd "$wd" && docker compose -p "$proj" $PROFILES down)
    stopped=$((stopped + 1))
  fi
done
[ "$stopped" -gt 0 ] || [ -n "$keep" ] || echo "== no demo stack is running"
