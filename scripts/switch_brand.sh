#!/usr/bin/env bash
# Start the demo platform for one bank:   scripts/switch_brand.sh NBE | RYD   (make start-NBE / make start-RYD)
#
# Each bank lives on its own git branch, checked out in its own worktree:
#   NBE  -> branch main          -> the main checkout (e.g. ~/NBE-demo)
#   RYD  -> branch Riyadh-Bank   -> <main checkout>-Riyadh-Bank (created on first use)
# Each worktree has its own .env (COMPOSE_PROJECT_NAME, IMAGE_TAG, bank names), so each bank keeps its own
# containers' data and images. Only one bank fits on the GB10 at a time, so the other bank's stack is stopped
# (containers removed, data volumes kept) before this one starts.
set -euo pipefail

target=$(echo "${1:-}" | tr '[:lower:]' '[:upper:]')
case "$target" in
  NBE) branch=main ;;
  RYD) branch=Riyadh-Bank ;;
  *) echo "usage: $0 NBE|RYD" >&2; exit 2 ;;
esac

here=$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)
main_root=$(git -C "$here" worktree list --porcelain | awk '/^worktree /{print $2; exit}')

# 1. The worktree for this bank's branch (create it if needed)
dir=$(git -C "$here" worktree list --porcelain | awk -v b="branch refs/heads/$branch" '/^worktree /{w=$2} $0==b {print w}')
if [ -z "$dir" ]; then
  dir="${main_root}-${branch}"
  echo "== creating worktree $dir for branch $branch"
  if git -C "$here" show-ref -q --verify "refs/heads/$branch"; then
    git -C "$here" worktree add "$dir" "$branch"
  else
    git -C "$here" worktree add -b "$branch" "$dir" "origin/$branch"
  fi
fi

# 2. Its .env (secrets generated fresh; the Hugging Face token copied over if this checkout has one)
if [ ! -f "$dir/.env" ]; then
  make -s -C "$dir" .env
  tok=$(grep -E '^HF_TOKEN=.+' "$here/.env" 2>/dev/null | head -1 || true)
  [ -n "$tok" ] && sed -i "s|^HF_TOKEN=.*|$tok|" "$dir/.env"
fi
project=$(grep -E '^COMPOSE_PROJECT_NAME=' "$dir/.env" | cut -d= -f2)
echo "== $target: branch $branch, folder $dir, Docker project ${project:-nbe}"

# 3. Stop the other bank's stack (any running demo stack except this one)
"$(dirname "$0")/stop_demo.sh" "${project:-nbe}"

# 4. Build this bank's images from its branch (cached: quick when nothing changed), then start it
#    (generates and loads its data on first run)
make -s -C "$dir" build >/dev/null
make -C "$dir" up
echo "== $target is running from $dir"
