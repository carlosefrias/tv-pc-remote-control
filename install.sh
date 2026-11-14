#!/usr/bin/env bash
# Install TV Remote on the Linux Mint laptop.
# Run from the repo folder as your normal user:  ./install.sh
# (it asks for your password once, to install the QR-code tool and open the firewall port)
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
CONF="$HOME/.config/tv-remote"
AUTOSTART="$HOME/.config/autostart/tv-remote.desktop"

if [ "$(id -u)" = "0" ]; then
  echo "Run ./install.sh as your normal user, not with sudo."
  exit 1
fi
command -v python3 >/dev/null || { echo "python3 is required"; exit 1; }
command -v firefox >/dev/null || echo "WARNING: firefox not found in PATH (set firefox_cmd in $CONF/config.json)"

# QR code tool, so the phone can just scan the link.
if ! command -v qrencode >/dev/null; then
  echo "Installing qrencode (shows the QR code for the phone)..."
  sudo apt-get install -y qrencode >/dev/null || echo "Could not install qrencode - the link will be shown as text."
fi

mkdir -p "$CONF" "$(dirname "$AUTOSTART")"
chmod +x "$REPO/server/tvremote.py" "$REPO/show-qr.sh"

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

# (Re)start it now. On first run it creates config.json with a new token.
pkill -f "$REPO/server/tvremote.py" 2>/dev/null || true
nohup python3 "$REPO/server/tvremote.py" >> "$CONF/server.log" 2>&1 &
for _ in $(seq 50); do [ -f "$CONF/config.json" ] && break; sleep 0.1; done
sleep 0.5

# Let the phone reach the server if the firewall (ufw) is on.
PORT="$(python3 -c "import json;print(json.load(open('$CONF/config.json')).get('port', 8080))")"
if command -v ufw >/dev/null && sudo ufw status 2>/dev/null | grep -q "Status: active"; then
  sudo ufw allow "$PORT/tcp" >/dev/null && echo "Firewall: allowed port $PORT."
fi

echo
echo "Installed. The server starts automatically when you log in."
echo "Channels: $CONF/channels.txt    Log: $CONF/server.log"
"$REPO/show-qr.sh"
