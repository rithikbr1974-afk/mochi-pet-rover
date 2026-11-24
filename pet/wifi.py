"""Wi-Fi through NetworkManager (nmcli). The pet user may only manage the network (a polkit rule from
install.sh), nothing else.

- Saved networks connect by themselves when in range (priority decides between several), so pre-added places
  just work.
- No known Wi-Fi for `fallback_s` -> Mochi starts her own hotspot (default "Mochi-setup"). Your phone joins it,
  the app reaches her at 10.42.0.1, and you add the new place's Wi-Fi.
- While her hotspot is on and nobody is connected to it, every 5 min she drops it for 45 s to look for known
  networks again.
- Passwords go into NetworkManager's root-only files and are never sent back to the app.
On a PC (no nmcli) a small fake keeps the app testable.
"""
import logging
import shutil
import subprocess
import threading
import time

log = logging.getLogger("wifi")
HOTSPOT = "pet-hotspot"


def _split(line):
    """nmcli -t output: ':' separated, '\\:' is a literal colon."""
    out, cur, esc = [], "", False
    for ch in line:
        if esc:
            cur += ch
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


class Wifi:
    def __init__(self, cfg, on_event=None):
        self.cfg = cfg
        self.on_event = on_event or (lambda *a, **k: None)
        self.nmcli = shutil.which("nmcli")
        self.fake = None if self.nmcli else {"saved": [{"name": "Home", "priority": 10}], "current": "Home"}
        self.lock = threading.Lock()
        self.last_ok = time.monotonic()
        self.hotspot_since = 0.0
        self.note = ""
        if self.nmcli:
            threading.Thread(target=self._watch, name="wifi", daemon=True).start()

    def _w(self):
        return self.cfg.get("wifi", {})

    def _run(self, *args, timeout=30):
        p = subprocess.run([self.nmcli, *args], capture_output=True, text=True, timeout=timeout)
        if p.returncode != 0:
            raise RuntimeError((p.stderr or p.stdout).strip()[:200] or "nmcli failed")
        return p.stdout

    # ---- reading ----------------------------------------------------------------------------
    def status(self):
        if self.fake is not None:
            return {"current": self.fake["current"], "ip": "127.0.0.1", "signal": 70, "hotspot": False,
                    "hotspot_name": self._w().get("hotspot_name", "Mochi-setup"), "saved": self.fake["saved"],
                    "note": "simulated (no NetworkManager here)"}
        cur, sig, hotspot = None, None, False
        try:
            for line in self._run("-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active").splitlines():
                name, typ, dev = (_split(line) + ["", "", ""])[:3]
                if dev == "wlan0":
                    hotspot = name == HOTSPOT
                    cur = name
            for line in self._run("-t", "-f", "ACTIVE,SIGNAL", "device", "wifi", "list", "--rescan", "no").splitlines():
                act, s = (_split(line) + ["", ""])[:2]
                if act == "yes":
                    sig = int(s or 0)
            ip = self._run("-g", "IP4.ADDRESS", "device", "show", "wlan0").strip().split("/")[0]
        except Exception as e:
            return {"current": None, "error": str(e), "saved": self.saved()}
        return {"current": cur, "ip": ip, "signal": sig, "hotspot": hotspot,
                "hotspot_name": self._w().get("hotspot_name", "Mochi-setup"), "saved": self.saved(), "note": self.note}

    def saved(self):
        if self.fake is not None:
            return self.fake["saved"]
        out = []
        for line in self._run("-t", "-f", "NAME,TYPE,AUTOCONNECT-PRIORITY", "connection", "show").splitlines():
            name, typ, prio = (_split(line) + ["", "", "0"])[:3]
            if typ == "802-11-wireless" and name != HOTSPOT:
                out.append({"name": name, "priority": int(prio or 0)})
        return sorted(out, key=lambda n: -n["priority"])

    def scan(self):
        if self.fake is not None:
            return [{"ssid": "Home", "signal": 70, "security": "WPA2"}, {"ssid": "Neighbour", "signal": 30, "security": "WPA2"}]
        seen = {}
        for line in self._run("-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "yes",
                              timeout=40).splitlines():
            ssid, sig, sec = (_split(line) + ["", "0", ""])[:3]
            if ssid and int(sig or 0) > seen.get(ssid, {}).get("signal", -1):
                seen[ssid] = {"ssid": ssid, "signal": int(sig or 0), "security": sec}
        return sorted(seen.values(), key=lambda n: -n["signal"])

    # ---- changing ---------------------------------------------------------------------------
    def add(self, ssid, password, priority=0):
        ssid = str(ssid).strip()
        if not ssid or len(ssid) > 32:
            raise ValueError("network name must be 1-32 characters")
        if password and not 8 <= len(password) <= 63:
            raise ValueError("Wi-Fi passwords are 8-63 characters")
        name = "pet-" + ssid
        if self.fake is not None:
            self.fake["saved"] = [n for n in self.fake["saved"] if n["name"] != name] + [{"name": name, "priority": int(priority)}]
            return name
        with self.lock:
            try:
                self._run("connection", "delete", "id", name)
            except RuntimeError:
                pass
            args = ["connection", "add", "type", "wifi", "ifname", "wlan0", "con-name", name, "ssid", ssid,
                    "connection.autoconnect", "yes", "connection.autoconnect-priority", str(int(priority))]
            if password:
                args += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password]
            self._run(*args)
        return name

    def remove(self, name):
        if self.fake is not None:
            self.fake["saved"] = [n for n in self.fake["saved"] if n["name"] != name]
            return
        if name == HOTSPOT or name not in [n["name"] for n in self.saved()]:
            raise ValueError("no such saved network")
        self._run("connection", "delete", "id", name)

    def connect(self, name):
        if self.fake is not None:
            self.fake["current"] = name
            return
        with self.lock:
            self._run("connection", "up", "id", name, timeout=45)

    def hotspot(self, on):
        if self.fake is not None:
            return
        with self.lock:
            if on:
                w = self._w()
                self._run("device", "wifi", "hotspot", "ifname", "wlan0", "con-name", HOTSPOT,
                          "ssid", w.get("hotspot_name", "Mochi-setup"), "password", w.get("hotspot_password", "mochipet"))
                self.hotspot_since = time.monotonic()
                self.on_event("hotspot", name=w.get("hotspot_name", "Mochi-setup"))
            else:
                try:
                    self._run("connection", "down", "id", HOTSPOT)
                except RuntimeError:
                    pass
                self.hotspot_since = 0.0

    # ---- watcher: own hotspot when lost ------------------------------------------------------
    def _clients(self):
        try:
            out = subprocess.run(["ip", "neigh", "show", "dev", "wlan0"], capture_output=True, text=True, timeout=5).stdout
            return [ln for ln in out.splitlines() if "REACHABLE" in ln or "STALE" in ln or "DELAY" in ln]
        except Exception:
            return []

    def _watch(self):
        time.sleep(20)
        while True:
            try:
                st = self.status()
                now = time.monotonic()
                if st.get("current") and not st.get("hotspot"):
                    self.last_ok = now
                    self.note = ""
                elif st.get("hotspot"):
                    if now - self.hotspot_since > 300 and not self._clients() and self.saved():
                        self.note = "looking for known Wi-Fi"
                        self.hotspot(False)
                        time.sleep(45)
                        if not self.status().get("current"):
                            self.hotspot(True)
                        self.last_ok = time.monotonic()
                elif now - self.last_ok > float(self._w().get("fallback_s", 90)):
                    self.note = "no known Wi-Fi: own hotspot on"
                    self.hotspot(True)
            except Exception as e:
                log.warning("wifi watch: %s", e)
            time.sleep(10)
