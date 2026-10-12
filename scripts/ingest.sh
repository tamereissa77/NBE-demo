#!/usr/bin/env bash
# Load every demo's data into Postgres/Qdrant through its own /admin/ingest endpoint (idempotent).
# DEMOS="d3 d6" limits it to some demos.
set -uo pipefail
BASE="http://localhost:${NBE_PORT:-8200}/api"
fail=0
for d in ${DEMOS:-d2 d3 d4 d5 d6 d7}; do
  printf '  %-3s ' "$d"
  out=$(curl -fsS -X POST --max-time 900 "$BASE/$d/admin/ingest" 2>&1) && echo "$out" || { echo "FAILED: $out"; fail=1; }
done
exit $fail
