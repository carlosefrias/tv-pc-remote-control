#!/usr/bin/env bash
# Add the channels from server/channels.default.txt that you don't have yet to
# your channel list (~/.config/tv-remote/channels.txt), each in its language
# group ([PT] / [EN] / [DE]). Runs automatically from ./install.sh.
# Your own channels, names and order are kept. A default channel you deleted is
# not added back: the default channels already offered are remembered in
# channels.seen. Lists from older versions (no groups) are organised by language.
# No restart needed.  Usage: ./update-channels.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
CONF="${TVREMOTE_CONFIG_DIR:-$HOME/.config/tv-remote}"
mkdir -p "$CONF"

python3 "$REPO/server/channels.py" update \
  "$REPO/server/channels.default.txt" "$CONF/channels.txt" "$CONF/channels.seen"
