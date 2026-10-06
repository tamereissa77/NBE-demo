#!/usr/bin/env bash
# Week-1 Arabic gate, end to end (PLAN.md §5, Phase 2). Swaps models in and out so each candidate
# runs on the same GB10, then has gpt-oss-120b pre-score every answer. ~30-40 min.
# Results: portal /eval (blind human scoring) and /eval/results.
# Re-running is safe: answers are upserted per (prompt, model).
set -euo pipefail
cd "$(dirname "$0")/.."
C="docker compose --profile core --profile quality --profile voice --profile image --profile hero --profile eval"
gate() { docker exec nbe-eval python -m app.gate "$@"; }
step() { printf '\n==== %s  (%s)\n' "$*" "$(date +%H:%M:%S)"; }

step "candidates in the show configuration: Gemma 4 26B (workhorse), Gemma 4 31B (quality)"
$C up -d --wait nbe-llm-q
gate run --models workhorse,quality

step "references: free memory, then Qwen2.5-14B and Mistral-7B one at a time"
$C stop nbe-llm-q nbe-asr nbe-tts nbe-sdxl >/dev/null 2>&1 || true
# References are context, not candidates: a failure is reported and skipped, never fatal
for ref in qwen:ref-qwen14b mistral:ref-mistral7b; do
  svc="nbe-ref-${ref%%:*}"; alias="${ref##*:}"
  if $C up -d --wait "$svc"; then gate run --models "$alias"; else echo "WARNING: $svc failed to start; skipping $alias" >&2; fi
  $C stop "$svc" >/dev/null 2>&1 || true
done

step "hero: gpt-oss-120b answers, then judges every answer"
scripts/mode.sh hero >/dev/null
gate run --models hero
gate judge --judge hero

step "back to the show configuration"
scripts/mode.sh hero-off >/dev/null
gate summary
echo "Score blind at http://localhost:${NBE_PORT:-8200}/eval"
