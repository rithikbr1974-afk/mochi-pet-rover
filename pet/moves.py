"""Emotion moves: the car shows feelings with its wheels. Each step is (left, right, seconds), speeds -1..1.

A move plays in its own thread, keeps feeding the body's watchdog, and stops at once when something else
drives (stop(), a new move, or manual driving).
"""
import threading
import time


def _rep(steps, n):
    return steps * n


MOVES = {
    "happy":   _rep([(1, -1, 0.06), (-1, 1, 0.06)], 12),                     # fast continuous wiggle
    "excited": _rep([(1, -1, 0.06), (-1, 1, 0.06)], 5) + [(1, -1, 0.9)]
               + _rep([(1, -1, 0.06), (-1, 1, 0.06)], 5),
    "angry":   _rep([(1, 1, 0.1), (-1, -1, 0.1)], 4) + [(0, 0, 0.15), (1, -1, 0.35)],   # shakes, turns away
    "sad":     [(-0.3, -0.3, 1.0), (-0.3, 0.1, 0.4), (0, 0, 0.3)],
    "curious": [(0.3, 0.3, 0.4), (0, 0, 0.4), (0.3, 0.3, 0.3), (0, 0, 0.2),
                (0.5, -0.5, 0.12), (0, 0, 0.25), (-0.5, 0.5, 0.24), (0, 0, 0.25), (0.5, -0.5, 0.12)],
    "sleepy":  _rep([(0.2, -0.2, 0.5), (0, 0, 0.3), (-0.2, 0.2, 0.5), (0, 0, 0.3)], 2),
    "love":    [(0.3, 0.3, 0.6)] + _rep([(0.5, -0.5, 0.05), (-0.5, 0.5, 0.05)], 6)
               + [(0.6, 0.6, 0.15), (0, 0, 0.2), (-0.3, -0.3, 0.15)],    # approach, wiggle, nudge
    "no":      _rep([(0.7, -0.7, 0.12), (-0.7, 0.7, 0.12)], 3),          # head shake
    "yes":     _rep([(0.7, 0.7, 0.1), (-0.7, -0.7, 0.1)], 3),            # nods
    "spin":    [(1, -1, 1.2)],
}


class Mover:
    def __init__(self, body, pochi=None):
        self.body = body
        self.pochi = pochi
        self.current = ""
        self._cancel = threading.Event()
        self._thread = None

    def play(self, name):
        if name not in MOVES:
            raise KeyError(name)
        self.cancel()
        self._cancel = threading.Event()
        self.current = name
        if self.pochi and name != "spin":
            self.pochi.say(name)
        self._thread = threading.Thread(target=self._run, args=(MOVES[name], self._cancel), daemon=True)
        self._thread.start()

    def cancel(self):
        self._cancel.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=0.5)
        self.current = ""

    def _run(self, steps, cancel):
        for left, right, secs in steps:
            end = time.monotonic() + secs
            while time.monotonic() < end:
                if cancel.is_set():
                    return
                self.body.drive(left, right)
                time.sleep(0.03)
        if not cancel.is_set():
            self.body.stop()
            self.current = ""
