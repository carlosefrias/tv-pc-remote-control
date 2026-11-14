#!/usr/bin/env bash
# Show the QR code (and link) that opens the TV Remote app on a phone.
# Scan it with the phone's camera. By default the link uses the internet
# (works on any network, even 4G or Wi-Fi with "AP isolation");
# ./show-qr.sh --local shows the home-network link instead.
set -euo pipefail

CONF="${TVREMOTE_CONFIG_DIR:-$HOME/.config/tv-remote}"
if [ ! -f "$CONF/config.json" ]; then
  echo "TV Remote is not set up yet - run ./install.sh first."
  exit 1
fi

# The address the laptop uses on the home network (the one with the default
# route), falling back to the first address the machine has.
IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") { print $(i + 1); exit }}')"
[ -n "$IP" ] || IP="$(hostname -I | awk '{print $1}')"

# Prints: local-link internet-link (internet-link is "-" if the relay is off).
read -r LOCAL_URL NET_URL < <(python3 - "$CONF/config.json" "$IP" <<'EOF'
import json, sys, urllib.parse
c = json.load(open(sys.argv[1]))
local = "http://%s:%s/?t=%s" % (sys.argv[2], c.get("port", 8080), c["token"])
net = "-"
if c.get("relay", True) and c.get("relay_secret") and c.get("app_url"):
    net = c["app_url"] + "#k=" + c["relay_secret"]
    server = c.get("relay_server", "https://ntfy.sh").rstrip("/")
    if server != "https://ntfy.sh":
        net += "&s=" + urllib.parse.quote(server, safe="")
print(local, net)
EOF
)

URL="$NET_URL"
WHERE="works on any network, through the internet"
if [ "${1:-}" = "--local" ] || [ "$NET_URL" = "-" ]; then
  URL="$LOCAL_URL"
  WHERE="only works with the phone on the same Wi-Fi as this laptop"
fi

echo
if ! python3 -c 'import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=2)' "http://127.0.0.1:$(python3 -c "import json;print(json.load(open('$CONF/config.json')).get('port', 8080))")/" 2>/dev/null; then
  echo "  WARNING: the TV Remote server is NOT running, so the phone can't connect."
  echo "  Start it with ./install.sh and look at $CONF/server.log for errors."
  echo
fi
if command -v qrencode >/dev/null; then
  echo "  Scan this with the phone's camera ($WHERE):"
  echo
  qrencode -t ANSIUTF8 -m 2 "$URL"
  echo
  echo "  Then in the phone's browser menu choose 'Add to Home screen'."
  echo "  Keep this code private: whoever scans it can control the TV."
else
  echo "  (No QR code: install it with  sudo apt install qrencode  and run ./show-qr.sh again)"
fi
echo
echo "  Link: $URL"
echo
