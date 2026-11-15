"""Make the channel's video player fill the TV.

Firefox only lets a page go fullscreen after a real user gesture, so after
launching a channel we drive the page through Marionette (Firefox's built-in
remote protocol, enabled with --marionette, listening on localhost only) and
run player_assist.js in it until the player is fullscreen, playing and unmuted.
Standard library only.
"""

import json
import socket
import sys
import time
from pathlib import Path

import display

ASSIST_JS = (Path(__file__).resolve().parent / "player_assist.js").read_text(encoding="utf-8")
CONSENT_JS = (Path(__file__).resolve().parent / "consent_reject.js").read_text(encoding="utf-8")
CONSENT_FRAMES_JS = r"""
return [...document.querySelectorAll('iframe')].filter(function (f) {
  var r = f.getBoundingClientRect();
  return r.width > 50 && r.height > 50 && /consent|cmp|privacy|sourcepoint|sp_message|didomi|onetrust|usercentrics|cookie|trustarc|quantcast/i
    .test((f.src || '') + ' ' + (f.id || '') + ' ' + (f.name || '') + ' ' + (f.title || ''));
});
"""

# Prefs written to the dedicated profile so the assist can work.
PREFS = {
    # Allow the page script to request fullscreen without a click.
    "full-screen-api.allow-trusted-requests-only": False,
    # Don't let Marionette switch on its "automation" prefs (they'd change the
    # profile's behaviour, e.g. safe browsing / startup page).
    "remote.prefs.recommended": False,
    "marionette.prefs.recommended": False,
}


def log(msg):
    sys.stderr.write("[%s] fullscreen: %s\n" % (time.strftime("%H:%M:%S"), msg))
    sys.stderr.flush()


class MarionetteError(Exception):
    pass


class Marionette:
    """Minimal Marionette protocol 3 client: "<len>:<json>" messages over TCP."""

    def __init__(self, port, timeout=30.0):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        self.buf = b""
        self.msg_id = 0
        self._read()  # server hello: {"applicationType": "gecko", ...}

    def _read(self):
        while True:
            sep = self.buf.find(b":")
            if sep != -1:
                n = int(self.buf[:sep])
                end = sep + 1 + n
                if len(self.buf) >= end:
                    data = self.buf[sep + 1:end]
                    self.buf = self.buf[end:]
                    return json.loads(data.decode("utf-8"))
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("Marionette connection closed")
            self.buf += chunk

    def send(self, name, params=None):
        self.msg_id += 1
        payload = json.dumps([0, self.msg_id, name, params or {}]).encode("utf-8")
        self.sock.sendall(str(len(payload)).encode("ascii") + b":" + payload)
        while True:
            msg = self._read()
            if isinstance(msg, list) and len(msg) == 4 and msg[0] == 1 and msg[1] == self.msg_id:
                if msg[2]:
                    raise MarionetteError("%s: %s" % (msg[2].get("error"), msg[2].get("message")))
                return msg[3]

    def start_session(self):
        # Marionette takes the capabilities object directly. pageLoadStrategy
        # "none" = don't wait for the (slow, ad-heavy) page to finish loading
        # before running our script.
        self.send("WebDriver:NewSession", {"pageLoadStrategy": "none"})
        self.send("WebDriver:SetTimeouts", {"script": 10000})

    def execute(self, script, args=None):
        return self.send("WebDriver:ExecuteScript", {"script": script, "args": args or []}).get("value")

    def click(self, x, y):
        self.send("WebDriver:PerformActions", {"actions": [{
            "type": "pointer", "id": "mouse", "parameters": {"pointerType": "mouse"},
            "actions": [
                {"type": "pointerMove", "x": int(x), "y": int(y), "origin": "viewport"},
                {"type": "pointerDown", "button": 0},
                {"type": "pointerUp", "button": 0},
            ],
        }]})
        self.send("WebDriver:ReleaseActions")

    def screenshot_png(self):
        import base64
        return base64.b64decode(self.send("WebDriver:TakeScreenshot", {"full": False})["value"])

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def place_window(m, tv):
    """Move the Firefox window to the TV screen and make it fullscreen there."""
    try:
        if display.contains(tv, m.send("WebDriver:GetWindowRect")):
            return
        # Restores the window from fullscreen, moves it, then fullscreen again
        # (now on the TV). Works in kiosk mode too.
        m.send("WebDriver:SetWindowRect", {"x": tv["x"], "y": tv["y"], "width": tv["w"], "height": tv["h"]})
        m.send("WebDriver:FullscreenWindow")
        time.sleep(0.3)
        r = m.send("WebDriver:GetWindowRect")
        if display.contains(tv, r):
            log("moved Firefox to the TV (%s)" % tv["name"])
            return
        log("Firefox stayed at %d,%d - asking the window manager to move it" % (r["x"], r["y"]))
    except MarionetteError as e:
        log("could not move the window via Firefox: %s" % e)
    if display.move_with_wm(tv, timeout=3):
        time.sleep(0.5)
        try:
            r = m.send("WebDriver:GetWindowRect")
            log("window manager move: %s" % ("OK, Firefox is on the TV" if display.contains(tv, r)
                                             else "failed, window still at %d,%d" % (r["x"], r["y"])))
        except MarionetteError:
            pass


ELEMENT_KEY = "element-6066-11e4-a52e-4f735466cecf"  # WebDriver element reference


def switch_to_frame(m, ref):
    try:
        m.send("WebDriver:SwitchToFrame", {"id": ref})
    except MarionetteError:  # older protocol form
        m.send("WebDriver:SwitchToFrame", {"element": ref.get(ELEMENT_KEY)})


def run_in_frame(m, ref, elapsed, clicks, depth=0):
    """Enter the player iframe (Marionette can, even cross-origin) and run the
    assist there: play, unmute, and if needed one click. Nested up to 3 deep."""
    if not isinstance(ref, dict) or ELEMENT_KEY not in ref:
        return {}
    try:
        switch_to_frame(m, ref)
    except MarionetteError as e:
        return {"error": "frame: %s" % str(e)[:100]}
    try:
        res = m.execute(ASSIST_JS, [{"elapsed": elapsed, "clicks": clicks[0], "inFrame": True}]) or {}
        if res.get("frame") and not res.get("video") and depth < 2:
            res = run_in_frame(m, res["frame"], elapsed, clicks, depth + 1)
        elif res.get("click") and clicks[0] < 1:
            clicks[0] += 1
            m.click(*res["click"])  # coordinates are inside this frame
        res.pop("frame", None)
        return res
    except MarionetteError as e:
        return {"error": "frame: %s" % str(e)[:100]}
    finally:
        try:
            m.send("WebDriver:SwitchToParentFrame")
        except MarionetteError:
            pass


def click_element(m, ref):
    """A real (trusted) click through Marionette; falls back to a JS click."""
    try:
        m.send("WebDriver:ElementClick", {"id": ref.get(ELEMENT_KEY)})
    except MarionetteError:
        m.execute("arguments[0].click()", [ref])


def reject_cookies(m):
    """Answer a cookie notice with its REFUSING option (consent_reject.js never
    picks an accepting one). Looks in the page and in consent iframes.
    Returns the label of the clicked button, or None."""
    try:
        found = m.execute(CONSENT_JS)
        if found and found.get("el"):
            click_element(m, found["el"])
            return found.get("label")
        for frame in m.execute(CONSENT_FRAMES_JS) or []:
            try:
                switch_to_frame(m, frame)
                found = m.execute(CONSENT_JS)
                if found and found.get("el"):
                    click_element(m, found["el"])
                    return "%s (in frame)" % found.get("label")
            finally:
                try:
                    m.send("WebDriver:SwitchToParentFrame")
                except MarionetteError:
                    pass
    except MarionetteError:
        pass
    return None


def connect(port, keep_going, timeout=15.0):
    """Wait for Firefox to open the Marionette port."""
    deadline = time.time() + timeout
    while time.time() < deadline and keep_going():
        try:
            return Marionette(port)
        except OSError:
            time.sleep(0.25)
    return None


def assist(port, keep_going, url, tv=None, fast_secs=60, on_status=None, refuse_cookies=True):
    """Open `url` in the Firefox listening on `port` (started on about:blank) and
    keep its player fullscreen/playing until keep_going() turns False or Firefox exits.
    If `tv` (a monitor from display.find_tv) is given, the window is moved there first.

    Checks every second for the first `fast_secs` seconds, then every 5 s (so the
    player goes back to fullscreen if something knocks it out).
    Returns False if Firefox could not be controlled (the caller should then open
    the page without the helper), True otherwise.
    """
    m = connect(port, keep_going)
    if m is None:
        if keep_going():
            log("could not connect to Firefox on port %s" % port)
        return False
    try:
        try:
            m.start_session()
            if tv:
                place_window(m, tv)
            # pageLoadStrategy "none": returns at once, doesn't wait for the ads.
            m.send("WebDriver:Navigate", {"url": url})
        except (OSError, MarionetteError) as e:
            log("could not take control of Firefox: %s" % e)
            return False
        start, last = time.time(), None
        clicks = [0]  # shared with run_in_frame
        consent_clicks = 0
        while keep_going():
            elapsed = time.time() - start
            # Cookie notices block many players until answered: refuse them
            # (up to 3 clicks, for notices with a second step) in the first 45 s.
            if refuse_cookies and consent_clicks < 3 and elapsed < 45:
                clicked = reject_cookies(m)
                if clicked:
                    consent_clicks += 1
                    log("cookie notice: clicked %r (refuse)" % clicked)
            try:
                res = m.execute(ASSIST_JS, [{"elapsed": elapsed, "clicks": clicks[0]}]) or {}
            except MarionetteError as e:  # page navigating/reloading: try again
                res = {"error": str(e)[:120]}
            if res.get("frame") and not res.get("video"):
                # The player is inside an iframe: run the assist in there too.
                inner = run_in_frame(m, res["frame"], elapsed, clicks)
                res.update({k: inner.get(k) for k in ("video", "playing", "muted", "ad", "player", "error")
                            if k in inner})
                res["action"] = "frame:%s" % (inner.get("action") or "-") if not res.get("action") \
                    else "%s+frame:%s" % (res["action"], inner.get("action") or "-")
                res["player"] = "iframe %s %s" % (res.get("frameSrc", "")[:40], inner.get("player") or "")
            elif res.get("click") and clicks[0] < 1:
                clicks[0] += 1
                try:
                    m.click(*res["click"])
                except MarionetteError as e:
                    res["clickError"] = str(e)[:120]
            summary = {k: res.get(k) for k in ("video", "fullscreen", "filled", "playing", "muted", "ad", "player", "error")}
            if summary != last:
                log(json.dumps(dict(summary, action=res.get("action"), click=res.get("click"), t=round(elapsed, 1))))
                last = summary
            if on_status:
                on_status(res, m)
            time.sleep(1.0 if elapsed < fast_secs else 5.0)
    except socket.timeout:
        log("Firefox stopped answering (timeout)")
    except (OSError, ConnectionError):
        pass  # Firefox was closed (channel change / stop)
    except MarionetteError as e:
        log("session error: %s" % e)
    finally:
        m.close()
    return True
