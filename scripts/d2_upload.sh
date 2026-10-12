#!/usr/bin/env bash
# Back office: add one scanned PDF to D2 without re-ingesting anything else, then wait for it.
#
#   scripts/d2_upload.sh <file.pdf> "<Arabic title>" "<English title>" [doc_type] [roles]
#       doc_type   legal_circular (default) or sop
#       roles      who may read it, comma separated (default legal_counsel,manager)
#   scripts/d2_upload.sh --list            documents added this way
#   scripts/d2_upload.sh --remove <doc_id> take one out again
#
# Needs D2 started with docker-compose.d2-extract.yml and the extraction service running
# (see that file). The document id is the file name without .pdf; uploading a file with the
# same name again replaces that document.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && { set -a; . ./.env; set +a; }
BASE="http://localhost:${NBE_PORT:-8200}/api/d2"

case "${1:-}" in
  --list)   curl -fsS "$BASE/upload/documents?role=manager"; echo; exit ;;
  --remove) curl -fsS -X DELETE "$BASE/upload/${2:?doc_id}?role=manager"; echo; exit ;;
  ""|-h|--help) sed -n '2,13p' "$0"; exit 1 ;;
esac

FILE=$1; AR=${2:?Arabic title}; EN=${3:?English title}
JOB=$(curl -fsS -X POST "$BASE/upload" -F "file=@$FILE;type=application/pdf" -F role=manager \
        -F "title_ar=$AR" -F "title_en=$EN" -F "doc_type=${4:-legal_circular}" -F "roles=${5:-legal_counsel,manager}")
ID=$(printf '%s' "$JOB" | sed -n 's/.*"job_id":"\([^"]*\)".*/\1/p')
echo "job $ID"
while :; do
  S=$(curl -fsS "$BASE/upload/jobs/$ID?role=manager")
  case "$S" in
    *'"status":"complete"'*) echo "$S"; exit 0 ;;
    *'"status":"failed"'*)   echo "$S" >&2; exit 1 ;;
  esac
  sleep 5
done
