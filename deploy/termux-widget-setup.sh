#!/data/data/com.termux/files/usr/bin/bash
# Create home-screen shortcuts, so the GUI is one tap instead of typed commands.
#
# Needs the Termux:Widget app from F-Droid. After running this, long-press your
# home screen -> Widgets -> Termux:Widget -> drop it anywhere.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SHORTCUTS="$HOME/.shortcuts"
mkdir -p "$SHORTCUTS"

cat > "$SHORTCUTS/FreeAgent Dashboard" <<RUNNER
#!/data/data/com.termux/files/usr/bin/bash
cd "$REPO"
termux-wake-lock
echo "Dashboard: http://127.0.0.1:8765"
echo "Open that in Chrome, then Add to Home screen."
python tools/serve.py --port 8765
RUNNER

cat > "$SHORTCUTS/FreeAgent Poll" <<RUNNER
#!/data/data/com.termux/files/usr/bin/bash
cd "$REPO"
termux-wake-lock
python tools/poll_espn.py
python tools/weekly_brief.py
termux-wake-unlock
echo
read -n1 -p "Done. Press any key to close."
RUNNER

chmod +x "$SHORTCUTS"/FreeAgent*

echo "Created:"
ls -1 "$SHORTCUTS" | sed 's/^/  /'
echo
echo "Next: install Termux:Widget from F-Droid, then long-press your home"
echo "screen -> Widgets -> Termux:Widget."
