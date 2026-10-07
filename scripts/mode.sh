#!/usr/bin/env bash
# Switch on-demand model profiles at runtime (PLAN.md §5 operating points).
#   mode.sh hero | hero-off | quality-on | quality-off | voice-on | voice-off | image-on | image-off | show
set -euo pipefail
cd "$(dirname "$0")/.."
C="docker compose --profile core --profile quality --profile voice --profile image --profile hero --profile eval"
avail() { free -g | awk '/^Mem:/ {print $7}'; }
need() {  # need <GB> <what>
  if [ "$(avail)" -lt "$1" ]; then
    echo "mode: only $(avail) GB free, $2 needs ~$1 GB. Switch something off first (e.g. make quality-off)." >&2
    exit 1
  fi
}

case "${1:-show}" in
  hero)
    echo "mode: hero - stopping quality, voice and image, starting gpt-oss-120b (~71 GB)"
    $C stop nbe-llm-q nbe-asr nbe-tts nbe-sdxl >/dev/null 2>&1 || true
    need 72 "gpt-oss-120b"
    $C up -d --wait nbe-hero ;;
  hero-off)
    $C stop nbe-hero
    "$0" voice-on && "$0" image-on ;;
  quality-on)  need 40 "Gemma 4 31B"; $C up -d --wait nbe-llm-q ;;
  quality-off) $C stop nbe-llm-q ;;
  voice-on)    need 6 "whisper + Piper"; $C up -d --wait nbe-asr nbe-tts ;;
  voice-off)   $C stop nbe-asr nbe-tts ;;
  image-on)    need 18 "SDXL"; $C up -d --wait nbe-sdxl ;;
  image-off)   $C stop nbe-sdxl ;;
  *) echo "usage: $0 hero|hero-off|quality-on|quality-off|voice-on|voice-off|image-on|image-off" >&2; exit 2 ;;
esac
scripts/gpu.sh
