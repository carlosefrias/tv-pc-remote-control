#!/usr/bin/env python3
"""TV Remote server - runs on the Linux Mint laptop connected to the TV.

Serves the phone web app (../web) and a small JSON API that switches the
channel by (re)launching Firefox in kiosk mode, controls volume and shuts the
laptop down. Standard library only - no pip install needed.
"""

import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import display
import fullscreen
import relay

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
CONFIG_DIR = Path(os.environ.get("TVREMOTE_CONFIG_DIR", Path.home() / ".config" / "tv-remote"))
CONFIG_FILE = CONFIG_DIR / "config.json"
CHANNELS_FILE = CONFIG_DIR / "channels.txt"
DEFAULT_CHANNELS_FILE = ROOT / "server" / "channels.default.txt"
PROFILE_DIR = CONFIG_DIR / "firefox-profile"

DEFAULT_CONFIG = {
    "port": 8080,
    "token": "",  # generated on first run
    "firefox_cmd": "firefox",
    "kiosk": True,
    # Dedicated profile: no "restore session?" prompt after we kill Firefox,
    # autoplay allowed, no first-run pages. Set false to use your normal profile.
    "dedicated_profile": True,
    # Put the channel's video player itself in fullscreen (not the whole page),
    # start it if it waits for a click, and unmute it. Needs dedicated_profile.
    "fullscreen_player": True,
    "marionette_port": 2828,
    # Which screen shows the channel: "auto" = the TV (external HDMI/DP screen),
    # an xrandr output name such as "HDMI-1", or "none" to leave Firefox where it opens.
    "tv_display": "auto",
    "shutdown_cmd": ["systemctl", "poweroff"],
    "volume_step": "5%",
    # Control through the internet (for Wi-Fi with "AP isolation" / 4G routers):
    # the phone app is hosted at app_url and talks to the laptop via relay_server.
    "relay": True,
    "relay_server": "https://ntfy.sh",
    "relay_secret": "",  # generated on first run; travels only inside the QR code
    "app_url": "https://carlosefrias.github.io/tv-pc-remote-control/",
}

CHANNELS_HEADER = """\
# TV Remote channel list - one channel per line:
#   Name | URL
# Lines starting with # are ignored. Order here = order on the phone grid.
# You can edit this file by hand or from the phone app (Edit mode).
# Note: editing from the phone rewrites this file (comments other than this
# header are not kept).
"""

FIREFOX_PREFS = {
    "browser.sessionstore.resume_from_crash": False,
    "browser.sessionstore.max_resumed_crashes": 0,
    "browser.startup.page": 0,
    "browser.shell.checkDefaultBrowser": False,
    "browser.aboutwelcome.enabled": False,
    "browser.startup.homepage_override.mstone": "ignore",
    "startup.homepage_welcome_url": "",
    "startup.homepage_welcome_url.additional": "",
    "trailhead.firstrun.didSeeAboutWelcome": True,
    "browser.translations.automaticallyPopup": False,  # no "translate page?" over the video
    "signon.rememberSignons": False,
    "datareporting.policy.dataSubmissionPolicyBypassNotification": True,
    "toolkit.telemetry.reportingPolicy.firstRun": False,
    "media.autoplay.default": 0,          # allow audio+video autoplay
    "media.autoplay.blocking_policy": 0,
    "full-screen-api.warning.timeout": 0,
    "full-screen-api.transition-duration.enter": "0 0",
    "full-screen-api.transition-duration.leave": "0 0",
    "browser.tabs.warnOnClose": False,
    "browser.warnOnQuit": False,
    "app.update.auto": False,
}

lock = threading.Lock()
# gen increases on every play/stop so the previous channel's fullscreen helper stops.
state = {"current": None, "gen": 0}


# --------------------------------------------------------------------------- config

def load_config():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}
    cfg = dict(DEFAULT_CONFIG, **saved)
    changed = any(k not in saved for k in DEFAULT_CONFIG)  # also adds new settings to old files
    if not cfg.get("token"):
        cfg["token"] = secrets.token_urlsafe(12)
        changed = True
    if not cfg.get("relay_secret"):
        cfg["relay_secret"] = secrets.token_urlsafe(24)
        changed = True
    if changed:
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return cfg


# --------------------------------------------------------------------------- channels

def read_channels():
    if not CHANNELS_FILE.exists():
        shutil.copyfile(DEFAULT_CHANNELS_FILE, CHANNELS_FILE)
    channels = []
    for raw in CHANNELS_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "|" not in line:
            continue
        name, url = (p.strip() for p in line.split("|", 1))
        if name and url:
            channels.append({"id": len(channels), "name": name, "url": url})
    return channels


def write_channels(items):
    clean = []
    for it in items:
        name = str(it.get("name", "")).replace("|", "/").replace("\n", " ").strip()
        url = str(it.get("url", "")).replace("\n", "").strip()
        if not name or not url:
            raise ValueError("Every channel needs a name and a URL")
        if not url.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://: %s" % url)
        clean.append((name, url))
    body = CHANNELS_HEADER + "\n" + "".join("%s | %s\n" % c for c in clean)
    tmp = CHANNELS_FILE.with_suffix(".tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(CHANNELS_FILE)


# --------------------------------------------------------------------------- actions

def use_fullscreen_helper(cfg):
    return cfg.get("fullscreen_player", True) and cfg.get("dedicated_profile", True)


def prepare_profile(cfg):
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    prefs = dict(FIREFOX_PREFS)
    if use_fullscreen_helper(cfg):
        prefs.update(fullscreen.PREFS)
        prefs["marionette.port"] = int(cfg.get("marionette_port", 2828))
    lines = ['user_pref("%s", %s);' % (k, json.dumps(v)) for k, v in prefs.items()]
    (PROFILE_DIR / "user.js").write_text("\n".join(lines) + "\n", encoding="utf-8")


def firefox_command(cfg, url, helper=False):
    """helper=True: start with Marionette on about:blank; the fullscreen helper
    then opens `url` itself (much faster than waiting for the page to load)."""
    cmd = [cfg["firefox_cmd"]]
    if cfg.get("dedicated_profile", True):
        prepare_profile(cfg)
        cmd += ["--profile", str(PROFILE_DIR), "--no-remote"]
        if helper:
            cmd += ["--marionette"]
            url = "about:blank"
    if cfg.get("kiosk", True):
        cmd += ["--kiosk"]
    return cmd + [url]


def kill_firefox():
    """Close every Firefox process (all profiles) and wait until gone."""
    names = ["firefox", "firefox-bin", "firefox-esr"]
    for n in names:
        subprocess.run(["pkill", "-TERM", "-x", n], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 3.0
    while time.time() < deadline:
        alive = any(
            subprocess.run(["pgrep", "-x", n], stdout=subprocess.DEVNULL).returncode == 0
            for n in names
        )
        if not alive:
            return
        time.sleep(0.1)
    for n in names:
        subprocess.run(["pkill", "-KILL", "-x", n], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.3)


def launch_firefox(cfg, url, helper=False):
    env = dict(os.environ)
    env.setdefault("DISPLAY", ":0")
    subprocess.Popen(
        firefox_command(cfg, url, helper), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, start_new_session=True,
    )


def start_fullscreen_helper(cfg, gen, url, tv):
    def keep_going():
        return state["gen"] == gen

    def run():
        port = int(cfg.get("marionette_port", 2828))
        if fullscreen.assist(port, keep_going, url, tv=tv):
            return
        # Couldn't control Firefox: at least show the page (whole page, kiosk).
        with lock:
            if keep_going():
                fullscreen.log("falling back to opening the page without the helper")
                kill_firefox()
                launch_firefox(cfg, url, helper=False)
        if tv and keep_going():
            display.move_with_wm(tv)

    threading.Thread(target=run, daemon=True).start()


def play(cfg, channel):
    with lock:
        state["gen"] += 1
        kill_firefox()
        helper = use_fullscreen_helper(cfg)
        tv = display.find_tv(cfg.get("tv_display", "auto"))
        launch_firefox(cfg, channel["url"], helper)
        state["current"] = channel["id"]
        if helper:
            start_fullscreen_helper(cfg, state["gen"], channel["url"], tv)
        elif tv:
            threading.Thread(target=display.move_with_wm, args=(tv,), daemon=True).start()


def stop():
    with lock:
        state["gen"] += 1
        kill_firefox()
        state["current"] = None


def volume(cfg, action):
    step = cfg.get("volume_step", "5%")
    if shutil.which("pactl"):
        cmds = {
            "up": ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+" + step],
            "down": ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-" + step],
            "mute": ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"],
        }
    else:
        cmds = {
            "up": ["amixer", "-q", "set", "Master", step + "+"],
            "down": ["amixer", "-q", "set", "Master", step + "-"],
            "mute": ["amixer", "-q", "set", "Master", "toggle"],
        }
    if action not in cmds:
        raise ValueError("unknown volume action")
    subprocess.run(cmds[action], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def shutdown(cfg):
    def later():
        time.sleep(2.0)  # let the reply reach the phone first
        subprocess.Popen(cfg["shutdown_cmd"])
    threading.Thread(target=later, daemon=True).start()


class NotFound(ValueError):
    pass


def api_call(cfg, cmd, args):
    """All phone commands, shared by the local HTTP API and the internet relay.
    Raises ValueError (bad input) / NotFound."""
    if cmd == "channels":
        return {"channels": read_channels(), "current": state["current"]}
    if cmd == "save":
        write_channels(args.get("channels", []))
        state["current"] = None
        return {"channels": read_channels(), "current": None}
    if cmd == "play":
        channels = read_channels()
        cid = int(args.get("id", -1))
        if not 0 <= cid < len(channels):
            raise NotFound("no such channel")
        play(cfg, channels[cid])
    elif cmd == "stop":
        stop()
    elif cmd == "volume":
        volume(cfg, args.get("action"))
    elif cmd == "shutdown":
        shutdown(cfg)
    else:
        raise NotFound("unknown command")
    return {"ok": True, "current": state["current"]}


def relay_handler(cfg):
    def handle(cmd, args):
        try:
            return api_call(cfg, cmd, args)
        except FileNotFoundError as e:
            raise ValueError("command not found on the laptop: %s" % e.filename)
    return handle


# --------------------------------------------------------------------------- http

class Handler(SimpleHTTPRequestHandler):
    cfg = None

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(WEB_DIR), **kw)

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def send_json(self, obj, status=HTTPStatus.OK):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        token = self.headers.get("X-Token", "")
        if secrets.compare_digest(token, self.cfg["token"]):
            return True
        self.send_json({"error": "bad token"}, HTTPStatus.UNAUTHORIZED)
        return False

    def read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    # (method, path) -> api_call command
    ROUTES = {
        ("GET", "/api/channels"): "channels",
        ("PUT", "/api/channels"): "save",
        ("POST", "/api/play"): "play",
        ("POST", "/api/stop"): "stop",
        ("POST", "/api/volume"): "volume",
        ("POST", "/api/shutdown"): "shutdown",
    }

    def handle_api(self, method):
        cmd = self.ROUTES.get((method, self.path))
        if cmd is None:
            return self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        if not self.authorized():
            return
        try:
            body = self.read_body() if method != "GET" else {}
            self.send_json(api_call(self.cfg, cmd, body if isinstance(body, dict) else {}))
        except NotFound as e:
            self.send_json({"error": str(e)}, HTTPStatus.NOT_FOUND)
        except (ValueError, TypeError, AttributeError) as e:
            self.send_json({"error": str(e)}, HTTPStatus.BAD_REQUEST)
        except FileNotFoundError as e:
            self.send_json({"error": "command not found: %s" % e.filename}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self.handle_api("GET")
        return super().do_GET()

    def do_PUT(self):
        self.handle_api("PUT")

    def do_POST(self):
        self.handle_api("POST")


def local_ips():
    try:
        out = subprocess.run(["hostname", "-I"], capture_output=True, text=True).stdout
        return out.split()
    except FileNotFoundError:
        return []


def main():
    cfg = load_config()
    read_channels()  # create channels.txt from defaults if missing
    Handler.cfg = cfg
    server = ThreadingHTTPServer(("0.0.0.0", int(cfg["port"])), Handler)
    print("TV Remote running. For the phone link/QR code run ./show-qr.sh")
    for ip in local_ips() or ["<laptop-ip>"]:
        print("  home network: http://%s:%s/?t=%s" % (ip, cfg["port"], cfg["token"]))
    if cfg.get("relay", True):
        relay.Relay(cfg["relay_server"], cfg["relay_secret"], relay_handler(cfg)).start()
        print("  internet: via %s (app: %s)" % (cfg["relay_server"], cfg.get("app_url") or "not set"))
    print("Channels file: %s" % CHANNELS_FILE)
    sys.stdout.flush()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        server.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
