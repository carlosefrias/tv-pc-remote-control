#!/usr/bin/env bash
# Add the channels from server/channels.default.txt that you don't have yet to
# your channel list (~/.config/tv-remote/channels.txt). Runs automatically from
# ./install.sh. Your own channels, names and order are kept; new ones go at the
# end. A default channel you deleted is not added back: the default channels
# already offered are remembered in channels.seen. No restart needed.
# Usage: ./update-channels.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
CONF="${TVREMOTE_CONFIG_DIR:-$HOME/.config/tv-remote}"
mkdir -p "$CONF"

python3 - "$REPO/server/channels.default.txt" "$CONF/channels.txt" "$CONF/channels.seen" <<'EOF'
import os, shutil, sys

defaults_file, mine_file, seen_file = sys.argv[1:4]
norm = lambda u: u.strip().rstrip("/").lower()

def channels(path):
    out = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "|" in line:
            name, url = (p.strip() for p in line.split("|", 1))
            out.append((name, url))
    return out

defaults = channels(defaults_file)

def remember(urls):
    with open(seen_file, "w", encoding="utf-8") as f:
        f.write("# Default channels already offered (so deleted ones are not added back)\n")
        f.writelines(u + "\n" for u in sorted(urls))

if not os.path.exists(mine_file):
    shutil.copyfile(defaults_file, mine_file)
    remember({norm(u) for _, u in defaults})
    print("Channels: created your list with %d channels." % len(defaults))
    sys.exit(0)

seen = set()
if os.path.exists(seen_file):
    seen = {norm(l) for l in open(seen_file, encoding="utf-8") if l.strip() and not l.startswith("#")}
have = {norm(u) for _, u in channels(mine_file)}
new = [(n, u) for n, u in defaults if norm(u) not in have and norm(u) not in seen]

if new:
    ends_with_newline = open(mine_file, encoding="utf-8").read().endswith("\n")
    with open(mine_file, "a", encoding="utf-8") as f:
        if not ends_with_newline:
            f.write("\n")
        for n, u in new:
            f.write("%s | %s\n" % (n, u))
    print("Channels: added %d new channel(s): %s" % (len(new), ", ".join(n for n, _ in new)))
else:
    print("Channels: no new channels.")
remember(seen | {norm(u) for _, u in defaults})
EOF
