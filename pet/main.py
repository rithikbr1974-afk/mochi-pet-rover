"""Mochi: wires body, moves, voices, emotion, Wi-Fi, places, tasks, MQTT and the phone app together.

On the Pi:  python3 -m pet.main            (pet.service does this at boot)
On the PC:  python -m pet.main --sim       (fake pins; sounds go to data/last_sound.wav)
"""
import argparse
import logging
import os
import signal
import subprocess
import threading
import time

import yaml

from .audio import Player
from .body import Body
from .bus import Bus
from .chirps import Pochi
from .emotion import Emotion
from .moves import MOVES, Mover
from .places import Places
from .settings import Settings
from .tasks import Tasks
from .voice import Voice
from .web import serve
from .wifi import Wifi

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
log = logging.getLogger("pet")


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def pi_health():
    temp = _read("/sys/class/thermal/thermal_zone0/temp")
    h = {"temp_c": round(int(temp) / 1000, 1) if temp else None}
    try:
        out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=2).stdout
        bits = int(out.strip().split("=")[1], 16)
        h["undervoltage_now"] = bool(bits & 0x1)
        h["undervoltage_seen"] = bool(bits & 0x10000)
    except Exception:
        pass
    load = _read("/proc/loadavg")
    if load:
        h["load"] = float(load.split()[0])
    return h


class Pet:
    def __init__(self, cfg, sim=False):
        self.data = os.environ.get("PET_DATA") or os.path.join(ROOT, "data")
        self.settings = Settings(cfg, self.data)
        self.cfg = cfg                          # live: settings changes land in this dict
        self.started = time.time()
        self.restart_wanted = False
        self.player = Player(cfg, self.data)
        self.pochi = Pochi(cfg, self.player)
        self.voice = Voice(cfg, self.data, self.player)
        self.emotion = Emotion()
        self.body = Body(cfg, sim=sim, on_event=self.event)
        self.mover = Mover(self.body, self.pochi)
        self.places = Places(self.data)
        self.tasks = Tasks(self)
        self.wifi = Wifi(cfg, on_event=self.event)
        self.bus = Bus(cfg, lambda name, payload: self.command(name, payload))
        self._stop = threading.Event()

    # ---- small helpers used by tasks --------------------------------------------------------
    def name(self):
        return self.cfg.get("name", "Mochi")

    def owner(self):
        return self.cfg.get("owner", "Friend")

    def say(self, text):
        self.voice.say(text)

    def feel(self, label, hold=8.0):
        self.emotion.set(label, hold)

    def move(self, name):
        self.emotion.set(name)
        self.mover.play(name)

    def event(self, name, **kw):
        log.info("event %s %s", name, kw)
        if name == "touch":
            self.feel("love")
            self.pochi.say("love")
        elif name == "cliff":
            self.mover.cancel()
            self.feel("sad")
            self.pochi.say("sad")
        elif name == "hotspot":
            self.say(f"I can't find a Wi-Fi I know. Connect your phone to my hotspot, {kw.get('name')}.")

    # ---- commands from the app and MQTT -----------------------------------------------------
    def command(self, name, p):
        """Returns (ok, message or data)."""
        h = self.HANDLERS.get(name)
        if not h:
            return False, "unknown command"
        try:
            return h(self, p or {})
        except (ValueError, KeyError, RuntimeError) as e:
            return False, str(e)

    def _drive(self, p):
        if self.mover.current:
            self.mover.cancel()
        if self.tasks.busy():
            return False, "busy with a task (stop it first)"
        l, r = float(p.get("l", 0)), float(p.get("r", 0))
        self.places.record(l, r)
        self.body.drive(l, r)
        return True, "ok"

    def _stop_all(self, p):
        self.mover.cancel()
        if self.tasks.busy():
            self.tasks.cancel()
        self.body.stop()
        self.places.record(0, 0)
        return True, "stopped"

    def _move(self, p):
        name = str(p.get("name"))
        if name not in MOVES:
            return False, f"unknown move; known: {', '.join(MOVES)}"
        self.move(name)
        return True, name

    def _settings_save(self, p):
        ok, msg, restart = self.settings.update(p)
        return ok, {"msg": msg, "restart": restart} if ok else msg

    def _restart(self, p):
        self.restart_wanted = True
        self._stop.set()                        # systemd starts the service again
        return True, "restarting"

    HANDLERS = {
        "drive": _drive,
        "stop": _stop_all,
        "move": _move,
        "chirp": lambda s, p: (s.pochi.say(str(p.get("emotion", "hello"))), (True, "chirp"))[1],
        "say": lambda s, p: (s.say(p.get("text", "")), (True, "ok"))[1],
        "settings": _settings_save,
        "restart": _restart,
        "wifi/add": lambda s, p: (True, s.wifi.add(p.get("ssid", ""), p.get("password", ""), int(p.get("priority", 0)))),
        "wifi/remove": lambda s, p: (s.wifi.remove(p.get("name", "")), (True, "removed"))[1],
        "wifi/connect": lambda s, p: (s.wifi.connect(p.get("name", "")), (True, "connecting"))[1],
        "wifi/scan": lambda s, p: (True, s.wifi.scan()),
        "wifi/hotspot": lambda s, p: (s.wifi.hotspot(bool(p.get("on"))), (True, "ok"))[1],
        "places/add": lambda s, p: (True, s.places.add(p.get("name", ""))),
        "places/remove": lambda s, p: (s.places.remove(p.get("name", "")), (True, "removed"))[1],
        "places/here": lambda s, p: (s.places.set("here", p.get("name") or None), (True, "ok"))[1],
        "places/owner": lambda s, p: (s.places.set("owner", p.get("name") or None), (True, "ok"))[1],
        "route/start": lambda s, p: (True, s.places.start(p.get("to", ""))),
        "route/finish": lambda s, p: (s.body.stop(), (True, s.places.finish(float(s.cfg["motors"].get("watchdog_s", 0.3)))))[1],
        "route/cancel": lambda s, p: (s.places.cancel(), (True, "cancelled"))[1],
        "route/delete": lambda s, p: (s.places.delete_route(p.get("from"), p.get("to")), (True, "deleted"))[1],
        "task": lambda s, p: s.tasks.request(p.get("text", "")),
        "task/confirm": lambda s, p: (s.tasks.confirm(), (True, "ok"))[1],
        "task/cancel": lambda s, p: (s.tasks.cancel(), (True, "stopped"))[1],
    }

    # ---- reading ----------------------------------------------------------------------------
    def status(self):
        return {"name": self.name(), "owner": self.owner(), "uptime_s": int(time.time() - self.started),
                "move": self.mover.current, "moves": list(MOVES), "emotion": self.emotion.now(self.tasks.busy()),
                "body": self.body.status(), "pi": pi_health(), "task": self.tasks.status(),
                "voice": {"state": self.voice.state, "last": self.voice.last, "talking": self.player.busy},
                "places": self.places.summary(), "camera": bool(self.cfg.get("camera", {}).get("url"))}

    def run(self):
        httpd = serve(self, int(self.cfg.get("web", {}).get("port", 8080)))
        threading.Thread(target=httpd.serve_forever, name="web", daemon=True).start()
        self.voice.preload()
        self.pochi.say("hello")
        self.say(f"Hi {self.owner()}! I'm awake.")
        signal.signal(signal.SIGTERM, lambda *a: self._stop.set())
        signal.signal(signal.SIGINT, lambda *a: self._stop.set())
        log.info("%s is awake", self.name())
        while not self._stop.wait(1.0):
            self.bus.publish("pet/status", self.status())
        if self.tasks.busy():
            self.tasks.cancel()
        self.mover.cancel()
        self.body.close()
        httpd.shutdown()
        log.info("%s is asleep", self.name())
        if self.restart_wanted:
            os._exit(3)                         # non-zero: systemd's Restart= brings her back


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true", help="fake pins (testing on a PC)")
    ap.add_argument("--config", default=os.path.join(ROOT, "config.yaml"))
    ap.add_argument("--port", type=int, help="phone app port (default from config)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    with open(a.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if a.port:
        cfg.setdefault("web", {})["port"] = a.port
    Pet(cfg, sim=a.sim).run()


if __name__ == "__main__":
    main()
