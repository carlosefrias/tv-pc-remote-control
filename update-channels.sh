#!/usr/bin/env bash
# Add the channels from server/channels.default.txt that are missing from your
# channel list (~/.config/tv-remote/channels.txt). Your own channels, names and
# order are kept; new ones are added at the end. No restart needed.
# Usage: ./update-channels.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
CONF="${TVREMOTE_CONFIG_DIR:-$HOME/.config/tv-remote}"
MINE="$CONF/channels.txt"

if [ ! -f "$MINE" ]; then
  mkdir -p "$CONF"
  cp "$REPO/server/channels.default.txt" "$MINE"
  echo "Created $MINE with the default channels."
  exit 0
fi

python3 - "$REPO/server/channels.default.txt" "$MINE" <<'EOF'
import sys

def channels(path):
    out = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "|" in line:
            name, url = (p.strip() for p in line.split("|", 1))
            out.append((name, url))
    return out

defaults, mine = channels(sys.argv[1]), channels(sys.argv[2])
norm = lambda u: u.rstrip("/").lower()
have = {norm(u) for _, u in mine}
new = [(n, u) for n, u in defaults if norm(u) not in have]
if not new:
    print("Your channel list already has all the default channels.")
    sys.exit(0)
ends_with_newline = open(sys.argv[2], encoding="utf-8").read().endswith("\n")
with open(sys.argv[2], "a", encoding="utf-8") as f:
    if not ends_with_newline:
        f.write("\n")
    for n, u in new:
        f.write("%s | %s\n" % (n, u))
print("Added %d channel(s):" % len(new))
for n, _ in new:
    print("  + " + n)
EOF
