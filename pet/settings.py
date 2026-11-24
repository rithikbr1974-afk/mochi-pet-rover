"""Settings the phone app can change. config.yaml holds the defaults (part of the code, read-only on the Pi);
the app's changes go to <data>/settings.json and are merged on top at start and on every save.

Each entry: (key, kind, label, options). kind = float | int | bool | text | secret | choice.
restart=True means the change needs a restart (the app offers the button).
"""
import copy
import json
import os

from .voice import VOICES

S = []


def _add(section, key, kind, label, restart=False, **opt):
    S.append({"section": section, "key": key, "kind": kind, "label": label, "restart": restart, **opt})


_add("Pet", "name", "text", "Name")
_add("Pet", "owner", "text", "Owner's name (she calls you this)")
_add("Voice", "voice.enabled", "bool", "Girl's voice")
_add("Voice", "voice.model", "choice", "Voice", choices=list(VOICES))
_add("Voice", "voice.pitch", "float", "Cuteness (higher pitch)", min=1.0, max=1.3, step=0.01)
_add("Voice", "voice.speed", "float", "Speaking speed", min=0.7, max=1.4, step=0.05)
_add("Voice", "audio.pochi", "bool", "Pochi chirps")
_add("Voice", "audio.volume", "float", "Volume", min=0.1, max=1.0, step=0.05)
_add("Driving", "motors.max_speed", "float", "Top speed", min=0.3, max=1.0, step=0.05)
_add("Driving", "motors.min_speed", "float", "Lowest speed (where the motors start turning)", min=0.0, max=0.6, step=0.05)
_add("Driving", "motors.trim", "float", "Straight-line trim (+ slows the right wheel)", min=-0.2, max=0.2, step=0.01)
_add("Driving", "motors.turn_180_s", "float", "Seconds for a half turn (used on routes)", min=0.3, max=3.0, step=0.05)
_add("Driving", "motors.watchdog_s", "float", "Stop if no command for (s)", min=0.2, max=1.0, step=0.05)
_add("Driving", "motors.invert_left", "bool", "Flip left wheel direction")
_add("Driving", "motors.invert_right", "bool", "Flip right wheel direction")
_add("Sensors", "sensors.ultrasonic.connected", "bool", "Ultrasonic sensor wired", restart=True)
_add("Sensors", "sensors.ultrasonic.stop_cm", "int", "Stop before obstacles (cm)", min=5, max=60, step=1)
_add("Sensors", "sensors.cliff.connected", "bool", "Cliff sensors wired", restart=True)
_add("Sensors", "sensors.cliff.active_high", "bool", "Cliff sensor reads HIGH over a drop", restart=True)
_add("Sensors", "sensors.touch.connected", "bool", "Touch pad wired", restart=True)
_add("Sensors", "sensors.tray.connected", "bool", "Tray sensor wired", restart=True)
_add("Camera", "camera.url", "text", "Robot phone camera address (IP Webcam app), e.g. http://192.168.1.50:8080")
_add("Tasks", "tasks.wait_load_s", "int", "Wait for someone to load the tray (s)", min=15, max=300, step=5)
_add("Tasks", "tasks.wait_take_s", "int", "Wait for you to take the item (s)", min=10, max=300, step=5)
_add("Tasks", "tasks.obstacle_wait_s", "int", "Wait for a blocked path to clear (s)", min=3, max=60, step=1)
_add("Wi-Fi", "wifi.hotspot_name", "text", "Own hotspot name (when no Wi-Fi is found)")
_add("Wi-Fi", "wifi.hotspot_password", "secret", "Own hotspot password (8+ characters)", min_len=8)
_add("Wi-Fi", "wifi.fallback_s", "int", "Start own hotspot after no Wi-Fi for (s)", min=30, max=900, step=10)

BY_KEY = {s["key"]: s for s in S}


def get(cfg, key, default=None):
    node = cfg
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def _put(cfg, key, value):
    parts = key.split(".")
    node = cfg
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def _merge(base, over):
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v


class Settings:
    def __init__(self, cfg, data_dir):
        self.defaults = copy.deepcopy(cfg)
        self.cfg = cfg                       # the live dict every part reads
        self.path = os.path.join(data_dir, "settings.json")
        self.saved = {}
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    self.saved = json.load(f)
            except ValueError:
                self.saved = {}
        _merge(self.cfg, copy.deepcopy(self.saved))

    def describe(self):
        values = {}
        for s in S:
            v = get(self.cfg, s["key"])
            values[s["key"]] = ("set" if v else "") if s["kind"] == "secret" else v
        return {"schema": S, "values": values}

    def update(self, changes):
        """Validates and saves; returns (ok, message, needs_restart)."""
        clean = {}
        for key, value in changes.items():
            s = BY_KEY.get(key)
            if not s:
                return False, f"unknown setting {key}", False
            k = s["kind"]
            try:
                if k == "float":
                    value = min(s["max"], max(s["min"], float(value)))
                elif k == "int":
                    value = int(min(s["max"], max(s["min"], int(float(value)))))
                elif k == "bool":
                    value = value in (True, "true", "1", 1, "on")
                elif k == "choice":
                    if value not in s["choices"]:
                        return False, f"{s['label']}: not a choice", False
                else:
                    value = str(value).strip()[:200]
                    if k == "secret":
                        if not value:
                            continue                 # empty = keep the old one
                        if len(value) < s.get("min_len", 0):
                            return False, f"{s['label']}: at least {s['min_len']} characters", False
            except (TypeError, ValueError):
                return False, f"{s['label']}: bad value", False
            clean[key] = value
        restart = False
        for key, value in clean.items():
            if get(self.cfg, key) != value and BY_KEY[key]["restart"]:
                restart = True
            _put(self.cfg, key, value)
            _put(self.saved, key, value)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.saved, f, indent=1)
        os.replace(tmp, self.path)
        return True, f"saved {len(clean)}", restart
