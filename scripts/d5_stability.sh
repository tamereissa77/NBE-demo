#!/usr/bin/env bash
# D5 stability on the GB10: run the golden check RUNS times with the reduce step on each alias
# (workhorse, then quality = Gemma 4 31B) against the on-box models through the gateway, then
# report how often each document's result matched. Run from the repo root on the box:
#     make quality-on && scripts/d5_stability.sh        # RUNS=3 by default
set -uo pipefail
RUNS=${RUNS:-3}
BASE="http://localhost:${NBE_PORT:-8200}/api/d5"
OUT=${OUT:-/tmp/d5_stability}
mkdir -p "$OUT"

for alias in workhorse quality; do
  echo "== D5_REDUCE_ALIAS=$alias"
  D5_REDUCE_ALIAS=$alias docker compose up -d --no-deps --force-recreate nbe-d5 >/dev/null
  for _ in $(seq 60); do curl -fsS -o /dev/null "$BASE/health" && break; sleep 2; done
  for i in $(seq "$RUNS"); do
    python3 tests/golden_d5.py "$BASE" data/seed-active/d5 --json "$OUT/$alias-$i.json" > "$OUT/$alias-$i.log" 2>&1
    echo "  run $i: exit $? ($(python3 -c "import json;d=json.load(open('$OUT/$alias-$i.json'));print(d['planted_caught'],'caught,',d['severity_match'],'severity,',len(d['failures']),'failures')"))"
  done
done
D5_REDUCE_ALIAS=workhorse docker compose up -d --no-deps --force-recreate nbe-d5 >/dev/null

python3 - "$OUT" "$RUNS" <<'EOF'
import json, sys
out, runs = sys.argv[1], int(sys.argv[2])
for alias in ("workhorse", "quality"):
    res = [json.load(open(f"{out}/{alias}-{i}.json")) for i in range(1, runs + 1)]
    print(f"\n{alias}: all-pass runs {sum(not r['failures'] for r in res)}/{runs}")
    for doc in res[0]["docs"]:
        keys = ("flagged", "severity") if doc[0] in "CE" else ("amounts",)
        seen = [json.dumps([r["docs"][doc].get(k) for k in keys], ensure_ascii=False) for r in res]
        print(f"  {doc}: {'stable' if len(set(seen)) == 1 else 'VARIES'}" + ("" if len(set(seen)) == 1 else f" -> {seen}"))
    fails = sorted({f for r in res for f in r["failures"]})
    for f in fails:
        print("  failure:", f)
EOF
