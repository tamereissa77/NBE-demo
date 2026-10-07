#!/usr/bin/env bash
# Between audiences: clear decisions, triage results, agent sessions and mock-bank state. Data stays loaded.
set -uo pipefail
BASE="http://localhost:${NBE_PORT:-8200}/api"
for d in d1 d4 d7; do printf '  %-3s ' "$d"; curl -fsS -X POST "$BASE/$d/admin/reset"; echo; done
