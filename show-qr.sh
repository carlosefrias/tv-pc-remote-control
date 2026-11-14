#!/usr/bin/env bash
# Show the QR code (and link) that opens the TV Remote app on a phone.
# Scan it with the phone's camera; the phone must be on the same Wi-Fi.
# Usage: ./show-qr.sh
set -euo pipefail

CONF="${TVREMOTE_CONFIG_DIR:-$HOME/.config/tv-remote}"
if [ ! -f "$CONF/config.json" ]; then
  echo "TV Remote is not set up yet - run ./install.sh first."
  exit 1
fi

read -r TOKEN PORT < <(python3 -c '
import json, sys
c = json.load(open(sys.argv[1]))
print(c["token"], c.get("port", 8080))' "$CONF/config.json")

# The address the laptop uses on the home network (the one with the default
# route), falling back to the first address the machine has.
IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") { print $(i + 1); exit }}')"
[ -n "$IP" ] || IP="$(hostname -I | awk '{print $1}')"

URL="http://$IP:$PORT/?t=$TOKEN"

echo
if command -v qrencode >/dev/null; then
  echo "  Scan this with the phone's camera (phone on the same Wi-Fi as this laptop):"
  echo
  qrencode -t ANSIUTF8 -m 2 "$URL"
  echo
  echo "  Then in the phone's browser menu choose 'Add to Home screen'."
else
  echo "  (No QR code: install it with  sudo apt install qrencode  and run ./show-qr.sh again)"
fi
echo
echo "  Link: $URL"
echo
