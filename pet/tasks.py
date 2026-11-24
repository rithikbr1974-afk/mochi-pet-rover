"""Tasks Mochi can be asked to do, one at a time, each step said out loud.

"bring my remote from the bedroom":
  1. find the way: taught routes from where she is to the bedroom
  2. drive there; pause and say "excuse me" if the path is blocked
  3. ask whoever is there: "Hi! <owner> needs the remote. Could you please put it on my tray?"
  4. wait for the tray sensor, a head pat, or the app's "Loaded" button (asks again halfway, gives up kindly)
  5. drive back to you (where you said you are, else where she started)
  6. "Here's your remote!" and wait until it's taken
Other tasks: "go to the kitchen", "come here / come back", "stop".
Requests are parsed with simple rules; a home assistant can send them in the same words when she's online.
"""
import logging
import re
import threading
import time

from .places import drive_steps

log = logging.getLogger("tasks")

FETCH = re.compile(r"\b(?:bring|fetch|get|grab)\s+(?:me\s+)?(?:my|the|a|an|our)?\s*(?P<item>.+?)\s+from\s+(?:the\s+|my\s+)?(?P<place>.+?)[.!?]*$", re.I)
GOTO = re.compile(r"\b(?:go|drive|move)\s+(?:to|into)\s+(?:the\s+|my\s+)?(?P<place>.+?)[.!?]*$", re.I)
COME = re.compile(r"\b(?:come\s+(?:here|back|to\s+me)|return)\b", re.I)
STOP = re.compile(r"^\s*(?:stop|cancel|halt|freeze)\b", re.I)


class Cancelled(Exception):
    pass


class Tasks:
    def __init__(self, pet):
        self.pet = pet
        self.current = None           # {"kind", "text", "step", "started"}
        self.history = []
        self._cancel = threading.Event()
        self._confirm = threading.Event()
        self._thread = None

    # ---- entry points ---------------------------------------------------------------------------
    def request(self, text):
        """Returns (ok, reply). Starts the task in the background."""
        text = " ".join(str(text).split())[:200]
        if STOP.search(text):
            self.cancel()
            return True, "Stopped."
        if self.busy():
            return False, f"I'm busy: {self.current['text']}. Say stop first."
        if m := FETCH.search(text):
            return self._start("fetch", text, self._fetch, m["item"].strip(), m["place"].strip())
        if m := GOTO.search(text):
            return self._start("go", text, self._go, m["place"].strip())
        if COME.search(text):
            return self._start("come", text, self._come)
        return False, "I can fetch things, go to a place, or come back. Try: bring my remote from the bedroom."

    def busy(self):
        return self._thread is not None and self._thread.is_alive()

    def confirm(self):
        self._confirm.set()

    def cancel(self):
        self._cancel.set()
        self._confirm.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        self.pet.body.stop()

    def status(self):
        return {"current": self.current, "history": self.history[-6:]}

    # ---- plumbing -------------------------------------------------------------------------------
    def _start(self, kind, text, fn, *args):
        self._cancel = threading.Event()
        self._confirm = threading.Event()
        self.current = {"kind": kind, "text": text, "step": "starting", "started": int(time.time()), "waiting": False}

        def run():
            result = "done"
            try:
                fn(*args)
            except Cancelled:
                result = "stopped"
                self.pet.say("Okay, I stopped.")
            except TaskFailed as e:
                result = f"failed: {e}"
                self.pet.feel("sad")
                self.pet.say(str(e))
            except Exception as e:
                log.exception("task crashed")
                result = f"error: {e}"
            finally:
                self.pet.body.stop()
                self.history.append({"text": text, "result": result, "at": int(time.time())})
                self.current = None
        self._thread = threading.Thread(target=run, name="task", daemon=True)
        self._thread.start()
        return True, "On it!"

    def _step(self, text, waiting=False):
        log.info("task step: %s", text)
        if self.current:
            self.current["step"] = text
            self.current["waiting"] = waiting

    def _check(self):
        if self._cancel.is_set():
            raise Cancelled()

    def _conf(self, key, default):
        return float(self.pet.cfg.get("tasks", {}).get(key, default))

    def _place(self, spoken):
        p = self.pet.places.find(spoken)
        if not p:
            raise TaskFailed(f"I don't know a place called {spoken} yet. Add it in the app and teach me the way.")
        return p

    def _travel(self, dest):
        places = self.pet.places
        here = places.here
        if not here:
            raise TaskFailed("I don't know where I am. Please tell me in the app.")
        path = places.path(here, dest)
        if path is None:
            raise TaskFailed(f"I don't know the way from the {here} to the {dest} yet. Please teach me once.")
        turn = float(self.pet.cfg.get("motors", {}).get("turn_180_s", 1.2))
        for route, rev in path:
            a, b = (route["to"], route["from"]) if rev else (route["from"], route["to"])
            self._step(f"driving from the {a} to the {b}")
            self.pet.feel("focused", hold=600)
            for left, right, dt in drive_steps(route, rev, turn):
                self._drive(left, right, dt)
            self.pet.body.stop()
            places.set("here", b)

    def _drive(self, left, right, dt):
        """One step. Time spent waiting for a blocked path doesn't count toward the step."""
        body = self.pet.body
        left_s = dt
        blocked_since = None
        asked = False
        while left_s > 0:
            self._check()
            if body.reflex and (left + right) > 0.05:
                body.stop()
                blocked_since = blocked_since or time.monotonic()
                if not asked:
                    self.pet.say("Excuse me, can I get through?")
                    self.pet.feel("confused")
                    asked = True
                if time.monotonic() - blocked_since > self._conf("obstacle_wait_s", 15):
                    raise TaskFailed("Something is blocking my way, so I stopped.")
                body.drive(0, 0)
                time.sleep(0.1)
                continue
            blocked_since = None
            body.drive(left, right)
            time.sleep(0.03)
            left_s -= 0.03

    def _wait(self, what, seconds, done, nudge=None):
        """Waits for done() or the app button; says `nudge` halfway. Returns True if it happened."""
        self._confirm.clear()
        self._step(what, waiting=True)
        end = time.monotonic() + seconds
        half = time.monotonic() + seconds / 2
        while time.monotonic() < end:
            self._check()
            if self._confirm.is_set() or done():
                self._step(what + ": done")
                return True
            if nudge and time.monotonic() > half:
                self.pet.say(nudge)
                nudge = None
            time.sleep(0.2)
        return False

    # ---- the tasks ------------------------------------------------------------------------------
    def _fetch(self, item, spoken):
        dest = self._place(spoken)
        places = self.pet.places
        home = places.d.get("owner") or places.here
        owner = self.pet.owner()
        self.pet.feel("excited")
        self.pet.say(f"Okay! I'll bring your {item} from the {dest}.")
        self._travel(dest)
        body = self.pet.body
        self.pet.feel("curious")
        self.pet.say(f"Hi there! {owner} needs the {item}. Could you please put it on my tray?")
        loaded = self._wait(f"waiting for someone to put the {item} on the tray", self._conf("wait_load_s", 60),
                            lambda: body.tray_loaded() is True or body.take_touch(),
                            nudge=f"Excuse me, could someone put the {item} on my tray, please?")
        if loaded:
            self.pet.feel("happy")
            self.pet.say("Thank you so much!")
            time.sleep(2.5)                  # let them take their hand away
        else:
            self.pet.feel("sad")
            self.pet.say(f"Nobody gave me the {item}. I'll go back to {owner}.")
        if home and home != places.here:
            self._travel(home)
        if not loaded:
            raise TaskFailed(f"Sorry {owner}, I couldn't get the {item}.")
        self.pet.feel("excited")
        self.pet.say(f"{owner}! Here's your {item}!")
        taken = self._wait(f"waiting for {owner} to take the {item}", self._conf("wait_take_s", 60),
                           lambda: body.tray_loaded() is False or body.take_touch())
        self.pet.feel("love" if taken else "happy")
        self.pet.move("happy")

    def _go(self, spoken):
        dest = self._place(spoken)
        self.pet.say(f"Going to the {dest}!")
        self._travel(dest)
        self.pet.say(f"I'm in the {dest}.")
        self.pet.feel("happy")

    def _come(self):
        home = self.pet.places.d.get("owner")
        if not home:
            raise TaskFailed("Where are you? Tell me in the app which room you're in.")
        if home == self.pet.places.here:
            self.pet.say("I'm already here with you!")
            self.pet.move("love")
            return
        self.pet.say("Coming!")
        self._travel(home)
        self.pet.move("love")


class TaskFailed(Exception):
    pass
