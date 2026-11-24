"""Places and taught routes ("teach and repeat" navigation).

You name places ("living room", "bedroom") and teach a route once by driving it from the app. The route is
stored as wheel commands with their timing, and Mochi can then drive it again, and back (turn around, the steps
in reverse order with left/right swapped, turn around again). Routes join up: living room -> hall -> bedroom.

How accurate this is depends on what's wired:
  now:              timing only. Fine for short, simple routes; drift grows with distance and battery level.
  + wheel encoders: distances instead of time (phase 1).
  + camera:         it checks the view against keyframes saved while teaching and corrects itself (phase 2).
Stored in <data>/places.json.
"""
import json
import os
import threading
import time
from collections import deque


class Places:
    def __init__(self, data_dir):
        self.file = os.path.join(data_dir, "places.json")
        self.lock = threading.Lock()
        self.d = {"places": [], "routes": [], "here": None, "owner": None}
        if os.path.exists(self.file):
            try:
                with open(self.file, encoding="utf-8") as f:
                    self.d.update(json.load(f))
            except ValueError:
                pass
        self.rec = None              # {"to": name, "samples": [(t, l, r)]}

    def _save(self):
        os.makedirs(os.path.dirname(self.file), exist_ok=True)
        with open(self.file + ".tmp", "w", encoding="utf-8") as f:
            json.dump(self.d, f, indent=1)
        os.replace(self.file + ".tmp", self.file)

    @staticmethod
    def norm(name):
        return " ".join(str(name).lower().replace("the ", " ").split())[:40]

    def find(self, name):
        """Best match for a spoken place name, or None."""
        n = self.norm(name)
        for p in self.d["places"]:
            if p == n:
                return p
        for p in self.d["places"]:
            if n and (n in p or p in n):
                return p
        return None

    # ---- places ---------------------------------------------------------------------------------
    def add(self, name):
        n = self.norm(name)
        if not n:
            raise ValueError("empty name")
        with self.lock:
            if n not in self.d["places"]:
                self.d["places"].append(n)
                self._save()
        return n

    def remove(self, name):
        with self.lock:
            self.d["places"] = [p for p in self.d["places"] if p != name]
            self.d["routes"] = [r for r in self.d["routes"] if name not in (r["from"], r["to"])]
            for k in ("here", "owner"):
                if self.d[k] == name:
                    self.d[k] = None
            self._save()

    def set(self, key, name):
        if name is not None and name not in self.d["places"]:
            raise ValueError("unknown place")
        with self.lock:
            self.d[key] = name
            self._save()

    @property
    def here(self):
        return self.d["here"]

    # ---- teaching -------------------------------------------------------------------------------
    def start(self, to):
        if not self.d["here"]:
            raise ValueError("first tell Mochi where she is now")
        to = self.add(to)
        if to == self.d["here"]:
            raise ValueError("she is already there")
        self.rec = {"to": to, "samples": [], "started": time.time()}
        return to

    def record(self, left, right):
        if self.rec is not None:
            self.rec["samples"].append((time.monotonic(), round(float(left), 2), round(float(right), 2)))

    def finish(self, watchdog_s=0.3):
        if self.rec is None:
            raise ValueError("not teaching a route")
        s = self.rec["samples"]
        steps = []
        for i, (t, left, right) in enumerate(s):
            nxt = s[i + 1][0] if i + 1 < len(s) else t + 0.1
            dt = min(nxt - t, watchdog_s)        # after the watchdog time the wheels had stopped anyway
            if steps and steps[-1][0] == left and steps[-1][1] == right:
                steps[-1][2] = round(steps[-1][2] + dt, 3)
            else:
                steps.append([left, right, round(dt, 3)])
        steps = [st for st in steps if st[0] or st[1]]
        if not steps:
            self.rec = None
            raise ValueError("nothing was driven")
        route = {"from": self.d["here"], "to": self.rec["to"], "steps": steps, "made": int(time.time()),
                 "seconds": round(sum(st[2] for st in steps), 1)}
        with self.lock:
            self.d["routes"] = [r for r in self.d["routes"] if not (r["from"] == route["from"] and r["to"] == route["to"])]
            self.d["routes"].append(route)
            self.d["here"] = route["to"]
            self._save()
        self.rec = None
        return route

    def cancel(self):
        self.rec = None

    def delete_route(self, a, b):
        with self.lock:
            self.d["routes"] = [r for r in self.d["routes"] if not (r["from"] == a and r["to"] == b)]
            self._save()

    # ---- planning -------------------------------------------------------------------------------
    def path(self, a, b):
        """Shortest chain of (route, reversed) from a to b over taught routes, or None."""
        if a == b:
            return []
        edges = {}
        for r in self.d["routes"]:
            edges.setdefault(r["from"], []).append((r["to"], r, False))
            edges.setdefault(r["to"], []).append((r["from"], r, True))
        prev = {a: None}
        q = deque([a])
        while q:
            cur = q.popleft()
            if cur == b:
                break
            for nxt, r, rev in edges.get(cur, []):
                if nxt not in prev:
                    prev[nxt] = (cur, r, rev)
                    q.append(nxt)
        if b not in prev:
            return None
        out, cur = [], b
        while prev[cur]:
            p, r, rev = prev[cur]
            out.append((r, rev))
            cur = p
        return out[::-1]

    def summary(self):
        return {"places": self.d["places"], "here": self.d["here"], "owner": self.d["owner"],
                "routes": [{"from": r["from"], "to": r["to"], "seconds": r["seconds"]} for r in self.d["routes"]],
                "teaching": ({"to": self.rec["to"], "seconds": round(time.time() - self.rec["started"])}
                             if self.rec else None)}


def drive_steps(route, reverse, turn_s):
    """The wheel steps for one route, forward or back (turn around, mirror, turn around)."""
    if not reverse:
        return [tuple(st) for st in route["steps"]]
    spin = [(1.0, -1.0, turn_s), (0.0, 0.0, 0.3)]
    back = [(r, l, dt) for l, r, dt in reversed(route["steps"])]
    return spin + back + [(0.0, 0.0, 0.3)] + spin
