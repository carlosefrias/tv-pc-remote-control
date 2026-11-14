#!/usr/bin/env bash
# Publish the phone app (the web/ folder) to the public GitHub Pages repository,
# so the phone can open it from anywhere. Run it after changing anything in web/.
# Usage: ./publish-app.sh [git URL of the Pages repo]
# Only web/ is published: no server code, no secrets (the key is only in the QR code).
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
TARGET="${1:-https://github.com/carlosefrias/tv-remote.git}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "Publishing $SRC/web to $TARGET ..."
git clone -q "$TARGET" "$WORK/site"
cd "$WORK/site"
git checkout -q -B main
find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -r "$SRC/web/." .
touch .nojekyll   # serve files as-is
cat > README.md <<'EOF'
# TV Remote - phone app

Phone remote control for a TV laptop. This repository only hosts the web page
(GitHub Pages); it is published automatically from the private project.
EOF

git add -A
if git diff --cached --quiet; then
  echo "Nothing changed - already published."
  exit 0
fi
git commit -q -m "Publish phone app ($(git -C "$SRC" rev-parse --short HEAD 2>/dev/null || date +%F))"
git push -q origin main
echo "Done. It is live within a minute or two at the GitHub Pages address of the repo."
