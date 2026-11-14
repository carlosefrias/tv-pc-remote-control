"""Find the TV among the laptop's screens and put Firefox on it.

The laptop and the TV usually form one extended desktop, and Firefox opens on
the laptop's own screen. We ask X11 (xrandr) where each monitor is and pick
the TV: the external output (HDMI/DP...) rather than the built-in panel
(eDP/LVDS/DSI), the physically biggest one if there are several.
Standard library only; uses the xrandr and (optional) wmctrl commands.
"""

import os
import re
import shutil
import subprocess
import sys
import time

INTERNAL = re.compile(r"^(eDP|LVDS|DSI|DPI)", re.I)
# " 1: +HDMI-1 1920/1600x1080/900+1920+0  HDMI-1"
MONITOR = re.compile(r"^\s*\d+:\s+[+*]*(\S+)\s+(\d+)/(\d+)x(\d+)/(\d+)([+-]\d+)([+-]\d+)")

_last_choice = [None]


def log(msg):
    sys.stderr.write("[%s] display: %s\n" % (time.strftime("%H:%M:%S"), msg))
    sys.stderr.flush()


def x_env():
    env = dict(os.environ)
    env.setdefault("DISPLAY", ":0")
    return env


def parse_monitors(text):
    mons = []
    for line in text.splitlines():
        m = MONITOR.match(line)
        if m:
            name, w, mmw, h, mmh, x, y = m.groups()
            mons.append({"name": name, "x": int(x), "y": int(y), "w": int(w), "h": int(h),
                         "mm": int(mmw) * int(mmh), "primary": "*" in line.split(name)[0]})
    return mons


def choose_tv(mons, wanted="auto"):
    """Pick the TV monitor, or None when there is nothing to do (one screen,
    mirrored screens, or feature disabled)."""
    if not wanted or wanted == "none" or len(mons) < 2:
        return None
    if wanted != "auto":
        return next((m for m in mons if m["name"] == wanted), None)
    if len({(m["x"], m["y"]) for m in mons}) == 1:
        return None  # mirrored: the TV already shows the same as the laptop
    external = [m for m in mons if not INTERNAL.match(m["name"])] or [m for m in mons if not m["primary"]]
    return max(external, key=lambda m: (m["mm"], m["w"] * m["h"])) if external else None


def find_tv(wanted="auto"):
    """The TV's {name, x, y, w, h} in desktop coordinates, or None."""
    if not wanted or wanted == "none":
        return None
    try:
        out = subprocess.run(["xrandr", "--listmonitors"], capture_output=True, text=True,
                             env=x_env(), timeout=5).stdout
    except (OSError, subprocess.SubprocessError) as e:
        log("can't list screens (xrandr: %s)" % e)
        return None
    mons = parse_monitors(out)
    tv = choose_tv(mons, wanted)
    desc = ", ".join("%s %dx%d+%d+%d" % (m["name"], m["w"], m["h"], m["x"], m["y"]) for m in mons)
    choice = (desc, tv and tv["name"])
    if choice != _last_choice[0]:  # log only when the setup changes
        _last_choice[0] = choice
        if tv:
            log("screens: %s -> TV is %s" % (desc, tv["name"]))
        elif wanted not in ("auto",) and mons:
            log("screens: %s -> output %r not found" % (desc, wanted))
        else:
            log("screens: %s -> nothing to move (single or mirrored screen)" % (desc or "none found"))
        if os.environ.get("XDG_SESSION_TYPE") == "wayland":
            log("warning: Wayland session - moving windows may not work; use the X11 (Cinnamon) session")
    return tv


def contains(tv, rect):
    """Is the centre of window `rect` ({x, y, width, height}) on the TV?"""
    cx, cy = rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2
    return tv["x"] <= cx < tv["x"] + tv["w"] and tv["y"] <= cy < tv["y"] + tv["h"]


def firefox_windows():
    """[(window id, x, y, w, h)] of Firefox windows, via wmctrl."""
    try:
        out = subprocess.run(["wmctrl", "-lxG"], capture_output=True, text=True, env=x_env(), timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    wins = []
    for line in out.splitlines():
        p = line.split(None, 7)  # id desktop x y w h class host title
        if len(p) >= 7 and "firefox" in p[6].lower():
            wins.append((p[0], int(p[2]), int(p[3]), int(p[4]), int(p[5])))
    return wins


def move_with_wm(tv, timeout=10.0):
    """Plan B: ask the window manager (wmctrl) to move Firefox to the TV and
    make it fullscreen there. Returns True if a window was moved."""
    if not shutil.which("wmctrl"):
        log("wmctrl not installed - can't move the window (sudo apt install wmctrl)")
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        wins = firefox_windows()
        if wins:
            for wid, *_ in wins:
                for args in (["-b", "remove,fullscreen"],
                             ["-e", "0,%d,%d,%d,%d" % (tv["x"], tv["y"], tv["w"], tv["h"])],
                             ["-b", "add,fullscreen"]):
                    subprocess.run(["wmctrl", "-i", "-r", wid] + args, env=x_env(), timeout=5,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        time.sleep(0.3)
    return False
