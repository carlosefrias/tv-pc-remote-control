"""Remote control through the internet.

For networks where the phone can't reach the laptop directly (e.g. a router
with Wi-Fi "AP isolation", or the phone on mobile data). Messages go through a
ntfy server (https://ntfy.sh by default, free, no account):

  phone  --POST-->  ntfy topic "cmd"    --stream-->  laptop   (commands)
  laptop --POST-->  ntfy topic "state"  --SSE----->  phone    (replies)

The laptop only makes outgoing HTTPS connections, so it works behind 4G/CGNAT.
Both topic names and the signing key are derived from one random secret that
only the laptop and the phone know (it travels in the QR code, after the '#'
of the link, so it is never sent to any server). Every message is signed with
HMAC-SHA256; the laptop rejects unsigned, old (> 5 min) or repeated commands.
The same derivation/format is implemented in web/app.js (RelayTransport).
Standard library only.
"""

import hashlib
import hmac
import json
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request

CHUNK = 3000      # ntfy messages are limited to 4096 bytes; payloads are split
MAX_AGE = 300     # seconds a command stays valid (also tolerates clock drift)
USER_AGENT = "tv-remote"


def log(msg):
    sys.stderr.write("[%s] relay: %s\n" % (time.strftime("%H:%M:%S"), msg))
    sys.stderr.flush()


def derive(secret):
    """secret -> (command topic, state topic, signing key). Mirrors app.js."""
    key = secret.encode("utf-8")

    def h(label):
        return hmac.new(key, label.encode("utf-8"), hashlib.sha256).hexdigest()

    return "tvr" + h("topic:cmd")[:29], "tvr" + h("topic:state")[:29], bytes.fromhex(h("sign"))


def sign(key, text):
    return hmac.new(key, text.encode("ascii"), hashlib.sha256).hexdigest()


def to_wire(key, payload):
    """payload dict -> list of ntfy message bodies (ASCII JSON, signed, chunked)."""
    text = json.dumps(payload, separators=(",", ":"))  # ensure_ascii: 1 char = 1 byte
    sig = sign(key, text)
    gid = secrets.token_hex(6)
    parts = [text[i:i + CHUNK] for i in range(0, len(text), CHUNK)] or [""]
    return [json.dumps({"g": gid, "i": i, "n": len(parts), "d": p, "s": sig}, separators=(",", ":"))
            for i, p in enumerate(parts)]


class Reassembler:
    """Collects chunks; returns the verified payload dict once complete, else None."""

    def __init__(self, key):
        self.key = key
        self.groups = {}

    def add(self, body):
        try:
            m = json.loads(body)
            gid, i, n, data, sig = m["g"], int(m["i"]), int(m["n"]), m["d"], m["s"]
        except (ValueError, KeyError, TypeError):
            return None
        if not (0 <= i < n <= 50):
            return None
        now = time.time()
        for g in [g for g, v in self.groups.items() if now - v["t"] > 60]:
            del self.groups[g]
        grp = self.groups.setdefault(gid, {"t": now, "parts": {}})
        grp["parts"][i] = data
        if len(grp["parts"]) < n:
            return None
        del self.groups[gid]
        text = "".join(grp["parts"][k] for k in range(n))
        if not hmac.compare_digest(sign(self.key, text), str(sig)):
            log("ignored a message with a bad signature")
            return None
        try:
            return json.loads(text)
        except ValueError:
            return None


class Relay:
    """Listens for signed commands and answers them. `handler(cmd, args)` returns
    the reply data (dict), None for no reply, or raises ValueError(message)."""

    def __init__(self, server, secret, handler, quiet_cmds=("volume",)):
        self.server = server.rstrip("/")
        self.cmd_topic, self.state_topic, self.key = derive(secret)
        self.handler = handler
        self.quiet_cmds = set(quiet_cmds)   # no reply (saves ntfy's daily message quota)
        self.seen = {}

    def start(self):
        threading.Thread(target=self._listen, daemon=True).start()

    # ---------------------------------------------------------------- receive
    def _listen(self):
        since, backoff, connected_once, errors = None, 1, False, 0
        rx = Reassembler(self.key)
        while True:
            url = "%s/%s/json" % (self.server, self.cmd_topic)
            if since:
                url += "?since=" + since   # catch up on what arrived while reconnecting
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=90) as resp:
                    if not connected_once or errors:
                        log("connected to %s (listening for the phone)" % self.server)
                    connected_once, errors, backoff = True, 0, 1
                    for line in resp:
                        line = line.strip()
                        if not line:
                            continue
                        ev = json.loads(line)
                        if ev.get("event") != "message":
                            continue
                        since = ev.get("id") or since
                        payload = rx.add(ev.get("message", ""))
                        if payload is not None:
                            threading.Thread(target=self._handle, args=(payload,), daemon=True).start()
            except Exception as e:  # network down, timeout, server restart...
                errors += 1
                if errors in (1, 5) or errors % 50 == 0:
                    log("connection problem (%s), retrying..." % (getattr(e, "reason", None) or e))
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)

    def _handle(self, msg):
        rid, cmd = str(msg.get("id", ""))[:40], msg.get("cmd")
        try:
            ts = float(msg.get("ts", 0))
        except (TypeError, ValueError):
            return
        if not rid or rid in self.seen:
            return
        now = time.time()
        self.seen = {k: v for k, v in self.seen.items() if now - v < 2 * MAX_AGE}
        self.seen[rid] = now
        if abs(now - ts) > MAX_AGE:
            log("ignored a %s command with a wrong time (phone clock off by %ds?)" % (cmd, now - ts))
            # Signed, so it's really our phone: tell it its clock is off.
            return self.publish({"re": rid, "ok": False, "error": "clock", "ts": int(now)})
        try:
            data = self.handler(cmd, msg.get("args") or {})
            reply = {"re": rid, "ok": True, "data": data, "ts": int(time.time())}
        except ValueError as e:
            reply = {"re": rid, "ok": False, "error": str(e), "ts": int(time.time())}
        except Exception as e:
            log("error running %s: %r" % (cmd, e))
            reply = {"re": rid, "ok": False, "error": "error on the laptop: %s" % e, "ts": int(time.time())}
        if cmd in self.quiet_cmds and reply["ok"]:
            return
        self.publish(reply)

    # ---------------------------------------------------------------- send
    def publish(self, payload):
        for body in to_wire(self.key, payload):
            req = urllib.request.Request(
                "%s/%s" % (self.server, self.state_topic), data=body.encode("ascii"), method="POST",
                # Replies are only useful live: don't keep them on the server.
                headers={"User-Agent": USER_AGENT, "Cache": "no"})
            try:
                urllib.request.urlopen(req, timeout=15).read()
            except (urllib.error.URLError, OSError) as e:
                log("could not send reply: %s" % (getattr(e, "reason", None) or e))
                return
