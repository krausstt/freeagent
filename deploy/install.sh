#!/usr/bin/env bash
# Install the ESPN poll as a systemd timer. Run on your Linux server.
#
#   ./deploy/install.sh
#
# Idempotent: safe to re-run after editing the unit files.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
UNIT_DIR="/etc/systemd/system"

echo "repo:  $REPO_DIR"
echo "user:  $USER_NAME"

if [[ ! -f "$HOME/.ffdraft.json" ]]; then
  echo "ERROR: $HOME/.ffdraft.json not found." >&2
  echo "Run this first:  python3 tools/find_league.py --guide" >&2
  exit 1
fi

# Refuse to proceed if the credential file is readable by anyone else.
perms="$(stat -c '%a' "$HOME/.ffdraft.json")"
if [[ "$perms" != "600" ]]; then
  echo "Tightening $HOME/.ffdraft.json from $perms to 600"
  chmod 600 "$HOME/.ffdraft.json"
fi

echo "Verifying the connection before installing a timer that would just fail..."
if ! python3 -m ffdraft.cli verify; then
  echo "ERROR: verify failed. Fix credentials before scheduling." >&2
  exit 1
fi

tmp="$(mktemp -d)"
sed -e "s|^User=.*|User=$USER_NAME|" \
    -e "s|^WorkingDirectory=.*|WorkingDirectory=$REPO_DIR|" \
    -e "s|^ReadWritePaths=.*|ReadWritePaths=$(dirname "$REPO_DIR")|" \
    "$REPO_DIR/deploy/ffdraft-poll.service" > "$tmp/ffdraft-poll.service"
cp "$REPO_DIR/deploy/ffdraft-poll.timer" "$tmp/"

sudo cp "$tmp/ffdraft-poll.service" "$tmp/ffdraft-poll.timer" "$UNIT_DIR/"
sudo systemctl daemon-reload
sudo systemctl enable --now ffdraft-poll.timer
rm -rf "$tmp"

echo
echo "Installed. Useful commands:"
echo "  systemctl list-timers ffdraft-poll.timer     # when does it next run"
echo "  sudo systemctl start ffdraft-poll.service    # run it now"
echo "  journalctl -u ffdraft-poll.service -n 50     # read the log"
