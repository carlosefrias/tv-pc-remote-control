"""The channel list file, grouped by language.

    [PT]
    RTP 1 | https://www.rtp.pt/play/direto/rtp1
    [EN]
    Sky News | https://news.sky.com/watch-live

A "[XX]" line starts a group (the phone shows one tab per group). Channels
before any header belong to PT - that is how lists from older versions look;
`update` converts them, taking each channel's group from the defaults.
Standard library only. CLI:  python3 channels.py update DEFAULTS MINE SEEN
"""

import os
import re
import sys

GROUP_ORDER = ["PT", "EN", "DE"]
DEFAULT_GROUP = "PT"
HEADER_RE = re.compile(r"^\[([A-Za-z0-9_-]{1,12})\]$")

FILE_HEADER = """\
# TV Remote channel list.
#   [PT] / [EN] / [DE] start a language group (one tab per group on the phone).
#   Each channel:  Name | URL
# Lines starting with # are ignored. Order here = order on the phone.
# You can edit this file by hand or from the phone app (Edit mode).
# Note: editing from the phone rewrites this file (comments other than this
# header are not kept).
"""


def norm_url(url):
    return url.strip().rstrip("/").lower()


def clean_group(group):
    g = re.sub(r"[^A-Za-z0-9_-]", "", str(group or "")).upper()[:12]
    return g or DEFAULT_GROUP


def parse(path):
    """-> (channels [{name, url, group}], has_group_headers)"""
    items, group, has_headers = [], DEFAULT_GROUP, False
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            m = HEADER_RE.match(line)
            if m:
                group, has_headers = m.group(1).upper(), True
                continue
            if "|" in line:
                name, url = (p.strip() for p in line.split("|", 1))
                if name and url:
                    items.append({"name": name, "url": url, "group": group})
    return items, has_headers


def group_order(groups):
    """Known languages first (PT, EN, DE), then any others in order of appearance."""
    seen = []
    for g in groups:
        if g not in seen:
            seen.append(g)
    return [g for g in GROUP_ORDER if g in seen] + [g for g in seen if g not in GROUP_ORDER]


def serialize(items):
    out = [FILE_HEADER]
    for g in group_order([it["group"] for it in items]):
        out.append("\n[%s]\n" % g)
        out.extend("%s | %s\n" % (it["name"], it["url"]) for it in items if it["group"] == g)
    return "".join(out)


def write(path, items):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(serialize(items))
    os.replace(tmp, path)


def update(defaults_path, mine_path, seen_path):
    """Add default channels the user hasn't got (and wasn't offered before) to
    their list, in the right language group; convert old lists without groups.
    Returns a one-line summary."""
    defaults, _ = parse(defaults_path)
    default_urls = {norm_url(c["url"]) for c in defaults}

    def remember(urls):
        with open(seen_path, "w", encoding="utf-8") as f:
            f.write("# Default channels already offered (so deleted ones are not added back)\n")
            f.writelines(u + "\n" for u in sorted(urls))

    if not os.path.exists(mine_path):
        write(mine_path, defaults)
        remember(default_urls)
        return "Channels: created your list with %d channels." % len(defaults)

    mine, has_groups = parse(mine_path)
    seen = set()
    if os.path.exists(seen_path):
        with open(seen_path, encoding="utf-8") as f:
            seen = {norm_url(l) for l in f if l.strip() and not l.startswith("#")}

    notes = []
    if not has_groups:  # list from an older version: put each channel in its language group
        by_url = {norm_url(c["url"]): c["group"] for c in defaults}
        for c in mine:
            c["group"] = by_url.get(norm_url(c["url"]), DEFAULT_GROUP)
        notes.append("organised by language")

    have = {norm_url(c["url"]) for c in mine}
    new = [dict(c) for c in defaults if norm_url(c["url"]) not in have and norm_url(c["url"]) not in seen]
    for c in new:  # insert at the end of its group
        last = max([i for i, m in enumerate(mine) if m["group"] == c["group"]], default=len(mine) - 1)
        mine.insert(last + 1, c)
    if new:
        notes.append("added %d new channel(s): %s" % (len(new), ", ".join("%s (%s)" % (c["name"], c["group"]) for c in new)))

    if new or not has_groups:
        write(mine_path, mine)
    remember(seen | default_urls)
    return "Channels: " + ("; ".join(notes) if notes else "no new channels.")


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "update":
        print(update(*sys.argv[2:5]))
    else:
        sys.exit("usage: channels.py update DEFAULTS MINE SEEN")
