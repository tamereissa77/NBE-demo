#!/usr/bin/env bash
# Present the demos for another customer:   scripts/switch_customer.sh <name>   (make customer NAME=<name>)
#
# <name> is a folder in customers/ (customer.json + logo.png; see customers/README.md). This
#   1. applies the profile (scripts/apply_customer.py): brand/, .env (bank names, COUNTRY, TZ), data/customer.json,
#      and the country's corpus rendered with the bank's name into data/seed-active
#   2. rebuilds the images (cached: only the portal changes, as the brand is baked into it)
#   3. if the stack is running: recreates the demo services with the new settings, regenerates the synthetic data
#      (D1 loan packs, D3 commerce, D6 documents, D5 clauses), reloads every demo and resets the demo state.
#      If it is not running, `make up` does that part the next time (it notices the customer changed).
# A country with no corpus yet (data/seed/<CC> missing) needs `make author` once, with the stack running.
set -euo pipefail
cd "$(dirname "$0")/.."
name=${1:-}
if [ -z "$name" ]; then
  echo "usage: make customer NAME=<name>   customers:" >&2
  for f in customers/*/customer.json; do d=$(basename "$(dirname "$f")"); [ "$d" = "_template" ] || echo "  $d" >&2; done
  exit 2
fi

step() { printf '\n== %s\n' "$*"; }

step "applying customers/$name"
rc=0
python3 scripts/apply_customer.py "$name" || rc=$?
[ "$rc" = 0 ] || [ "$rc" = 3 ] || exit "$rc"
no_corpus=$([ "$rc" = 3 ] && echo 1 || echo 0)

# Banner mock-ups are cached per offer: they show the previous bank's logo and colours
rm -rf data/generated/d3/banners && mkdir -p data/generated/d3/banners && chmod 777 data/generated/d3/banners 2>/dev/null || true

step "building images (cached)"
make -s build >/dev/null

if ! docker ps --format '{{.Names}}' | grep -qx nbe-gateway; then
  echo; echo "The stack is not running: \`make up\` starts it and loads the data for this customer."
  [ "$no_corpus" = 1 ] && echo "Then run \`make author\` once: this country has no corpus yet."
  exit 0
fi
project=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' nbe-gateway)
mine=$(grep -E '^COMPOSE_PROJECT_NAME=' .env | cut -d= -f2)
if [ "$project" != "${mine:-nbe}" ]; then
  echo; echo "Another checkout's stack is running (project $project). Stop it there (make down), then \`make up\` here."
  exit 0
fi

step "recreating the demo services with the new customer's settings"
running=$(docker ps --format '{{.Names}}' | grep -xE 'nbe-(d[1-7]|mockbank|eval|portal|gateway)' | xargs)
docker compose up -d --wait $running

if [ "$no_corpus" = 1 ]; then
  echo; echo "This country has no corpus yet: run \`make author\` (about 25 min), then \`make customer NAME=$name\` again."
  exit 0
fi

step "generating the synthetic data for this customer"
make -s data
python3 scripts/apply_customer.py --seed-only

step "loading every demo"
scripts/ingest.sh && cp data/customer.json data/generated/.loaded-customer.json
scripts/demo_reset.sh
echo; echo "Portal: http://localhost:$(grep -E '^NBE_PORT=' .env | cut -d= -f2)  ($(python3 -c 'import json;c=json.load(open("data/customer.json"));print(c["name"]["en"], "-", c["country"])'))"
