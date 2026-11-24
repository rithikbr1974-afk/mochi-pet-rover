"""Body: motors, sensors and reflexes. The only code that touches the GPIO.

Reflexes run in their own 50 Hz thread and win over every command:
  - watchdog: no drive command for `watchdog_s` -> stop
  - obstacle: ultrasonic closer than stop_cm -> no forward motion (turning and reversing still allowed)
  - cliff: a cliff sensor sees no floor -> back off for 0.3 s, then stop
Without gpiozero (on the PC) or with sim=True everything runs on fake pins.
"""
import logging
import threading
import time

log = logging.getLogger("body")


class _SimMotor:
    def __init__(self):
        self.value = 0.0


class Body:
    def __init__(self, cfg, sim=False, on_event=None):
        self.cfg = cfg
        m = cfg["motors"]
        self.sim = sim
        self.on_event = on_event or (lambda name, **kw: None)
        self._refresh()
        self.lock = threading.Lock()
        self.cmd = (0.0, 0.0)          # last requested (left, right), -1..1
        self.out = (0.0, 0.0)          # what the motors actually got after reflexes
        self.last = 0.0
        self.reflex = ""               # why a reflex is acting, shown on the status page
        self.backoff_until = 0.0
        self.distance_cm = None
        self.cliff = False
        self._touched = False
        self._touch_flag = False
        self._setup_pins(m, cfg.get("sensors", {}))
        self._stop = threading.Event()
        threading.Thread(target=self._loop, name="reflex", daemon=True).start()

    def _refresh(self):
        """Speed settings are re-read all the time, so the app's changes apply at once."""
        m = self.cfg["motors"]
        self.max = float(m.get("max_speed", 0.7))
        self.min = float(m.get("min_speed", 0.0))
        self.trim = float(m.get("trim", 0.0))
        self.inv = (-1 if m.get("invert_left") else 1, -1 if m.get("invert_right") else 1)
        self.timeout = float(m.get("watchdog_s", 0.3))

    # ---- pins -------------------------------------------------------------------------------
    def _setup_pins(self, m, s):
        self.us = None
        self.cliffs = []
        self.touch = None
        self.tray = None
        if not self.sim:
            try:
                import gpiozero  # noqa: F401
            except ImportError:
                log.warning("gpiozero not installed: simulated body")
                self.sim = True
        if self.sim:
            self.left, self.right, self.stby = _SimMotor(), _SimMotor(), None
            return
        from gpiozero import DigitalInputDevice, DistanceSensor, Motor, OutputDevice
        self.left = Motor(forward=m["left"][1], backward=m["left"][2], enable=m["left"][0], pwm=True)
        self.right = Motor(forward=m["right"][1], backward=m["right"][2], enable=m["right"][0], pwm=True)
        self.stby = OutputDevice(m["standby"], initial_value=True) if m.get("standby") is not None else None
        u = s.get("ultrasonic", {})
        if u.get("connected"):
            self.us = DistanceSensor(echo=u["echo"], trigger=u["trigger"], max_distance=2.0, queue_len=3)
        c = s.get("cliff", {})
        if c.get("connected"):
            self.cliffs = [DigitalInputDevice(p, pull_up=None, active_state=bool(c.get("active_high", True)))
                           for p in c["pins"]]
        t = s.get("touch", {})
        if t.get("connected"):
            self.touch = DigitalInputDevice(t["pin"], pull_up=None, active_state=True)
        tr = s.get("tray", {})
        if tr.get("connected"):   # microswitch to GND (pull-up) or an IR module; active = something on the tray
            self.tray = DigitalInputDevice(tr["pin"], pull_up=bool(tr.get("pull_up", True)),
                                           active_state=None if tr.get("pull_up", True) else bool(tr.get("active_high", True)))

    def tray_loaded(self):
        """True/False from the tray sensor, None if no tray sensor is wired."""
        return None if self.tray is None else bool(self.tray.is_active)

    def take_touch(self):
        """True once per head pat since the last call (used as 'done' in tasks)."""
        flag, self._touch_flag = self._touch_flag, False
        return flag

    # ---- commands ---------------------------------------------------------------------------
    def drive(self, left, right):
        """left/right in -1..1. Must be repeated faster than the watchdog, or the wheels stop."""
        left = max(-1.0, min(1.0, float(left)))
        right = max(-1.0, min(1.0, float(right)))
        with self.lock:
            self.cmd = (left, right)
            self.last = time.monotonic()

    def stop(self):
        with self.lock:
            self.cmd = (0.0, 0.0)
            self.last = 0.0
        self._apply(0.0, 0.0)

    def close(self):
        self._stop.set()
        self.stop()

    def _scale(self, v):
        if abs(v) < 0.02:
            return 0.0
        mag = self.min + (self.max - self.min) * abs(v)
        return mag if v > 0 else -mag

    def _apply(self, left, right):
        l_out = self._scale(left) * (1 - max(0.0, -self.trim))
        r_out = self._scale(right) * (1 - max(0.0, self.trim))
        self.out = (round(l_out, 3), round(r_out, 3))
        self.left.value = l_out * self.inv[0]
        self.right.value = r_out * self.inv[1]

    # ---- reflex loop ------------------------------------------------------------------------
    def _loop(self):
        stop_cm = self.cfg.get("sensors", {}).get("ultrasonic", {}).get("stop_cm", 15)
        while not self._stop.is_set():
            self._refresh()
            now = time.monotonic()
            with self.lock:
                left, right = self.cmd
                fresh = now - self.last < self.timeout
            reflex = ""
            if self.us is not None:
                self.distance_cm = round(self.us.distance * 100, 1)
            if self.cliffs:
                cliff = any(c.is_active for c in self.cliffs)
                if cliff and not self.cliff:
                    self.backoff_until = now + 0.3
                    self.on_event("cliff")
                self.cliff = cliff
            if self.touch is not None:
                touched = self.touch.is_active
                if touched and not self._touched:
                    self._touch_flag = True
                    self.on_event("touch")
                self._touched = touched

            if now < self.backoff_until:
                left, right, reflex = -0.5, -0.5, "cliff: backing off"
            elif not fresh:
                left, right = 0.0, 0.0
            else:
                forward = left + right > 0.05
                if self.cliff and forward:
                    left, right, reflex = 0.0, 0.0, "cliff: no forward"
                elif forward and self.distance_cm is not None and self.distance_cm < stop_cm:
                    left, right, reflex = 0.0, 0.0, f"obstacle at {self.distance_cm} cm"
            self.reflex = reflex
            self._apply(left, right)
            time.sleep(0.02)

    def status(self):
        return {"sim": self.sim, "cmd": self.cmd, "out": self.out, "reflex": self.reflex,
                "distance_cm": self.distance_cm, "cliff": self.cliff, "tray": self.tray_loaded()}
