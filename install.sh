#!/usr/bin/env bash
# Install TV Remote on the Linux Mint laptop.
# Run from the repo folder as your normal user (NOT with sudo):  ./install.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
CONF="$HOME/.config/tv-remote"
AUTOSTART="$HOME/.config/autostart/tv-remote.desktop"

command -v python3 >/dev/null || { echo "python3 is required"; exit 1; }
command -v firefox >/dev/null || echo "WARNING: firefox not found in PATH (set firefox_cmd in $CONF/config.json)"

mkdir -p "$CONF" "$(dirname "$AUTOSTART")"
chmod +x "$REPO/server/tvremote.py"

# Start automatically with the desktop session (so it has access to the display).
cat > "$AUTOSTART" <<EOF
[Desktop Entry]
Type=Application
Name=TV Remote server
Comment=Phone remote control for the TV
Exec=sh -c 'python3 "$REPO/server/tvremote.py" >> "$CONF/server.log" 2>&1'
X-GNOME-Autostart-enabled=true
NoDisplay=false
EOF

# Allow the server port through ufw if the firewall is active.
if command -v ufw >/dev/null && sudo -n true 2>/dev/null; then
  sudo ufw allow 8080/tcp >/dev/null 2>&1 || true
elif command -v ufw >/dev/null; then
  echo "If the firewall (ufw) is enabled, run:  sudo ufw allow 8080/tcp"
fi

# (Re)start it now.
pkill -f "$REPO/server/tvremote.py" 2>/dev/null || true
nohup python3 "$REPO/server/tvremote.py" >> "$CONF/server.log" 2>&1 &
sleep 1

TOKEN="$(python3 -c "import json;print(json.load(open('$CONF/config.json'))['token'])")"
PORT="$(python3 -c "import json;print(json.load(open('$CONF/config.json'))['port'])")"
IP="$(hostname -I | awk '{print $1}')"
URL="http://$IP:$PORT/?t=$TOKEN"

echo
echo "Installed. The server starts automatically when you log in."
echo "Open this on your phone, then use the browser menu > 'Add to Home screen':"
echo
echo "   $URL"
echo
if command -v qrencode >/dev/null; then
  qrencode -t ANSIUTF8 "$URL"
else
  echo "(Tip: 'sudo apt install qrencode' and re-run to get a QR code to scan.)"
fi
echo "Channels: $CONF/channels.txt    Log: $CONF/server.log"
