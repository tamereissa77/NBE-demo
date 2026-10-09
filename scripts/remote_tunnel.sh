#!/usr/bin/env bash
# Open the NBE demos from a remote macOS or Linux laptop as http://localhost:<port>.
# Run this ON THE LAPTOP, not on the demo PC. It forwards the portal's port over SSH, so the browser
# sees "localhost" and allows the microphone (D4 voice), which it refuses on a plain http://<ip> address.
#
#   NBE_DEMO_HOST=<demo-pc-address> NBE_DEMO_USER=<user> scripts/remote_tunnel.sh
#   LOCAL_PORT=8301 NBE_DEMO_HOST=<demo-pc-address> scripts/remote_tunnel.sh     if the port is busy here
#
# Leave it running while you use the demos; Ctrl+C closes the tunnel.
set -euo pipefail
SERVER=${NBE_DEMO_HOST:?set NBE_DEMO_HOST to the demo PC address}
SSH_USER=${NBE_DEMO_USER:-$USER}
PORT=${NBE_PORT:-8200}              # NBE_PORT on the demo PC
LOCAL_PORT=${LOCAL_PORT:-$PORT}
URL="http://localhost:$LOCAL_PORT"

echo "Tunnel: $URL  ->  $SERVER:$PORT  (as $SSH_USER). Ctrl+C closes it."
# Open the browser once the tunnel answers (after the password or key prompt)
( for _ in $(seq 120); do
    if (exec 3<>"/dev/tcp/127.0.0.1/$LOCAL_PORT") 2>/dev/null; then
      { command -v open >/dev/null && open "$URL"; } || { command -v xdg-open >/dev/null && xdg-open "$URL"; } || true
      break
    fi
    sleep 1
  done ) &

exec ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -L "$LOCAL_PORT:127.0.0.1:$PORT" "$SSH_USER@$SERVER"
