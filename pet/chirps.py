"""The Pochi voice: creature chirps made in code, one melody shape per emotion.

Every call is slightly different (random pitch, length and count), so it sounds alive, not like a recording.
"""
import logging
import random

import numpy as np

log = logging.getLogger("chirps")
SR = 22050


def _tone(f0, f1, dur, vib=0.0, vib_hz=0.0, buzz=False, amp=1.0):
    n = max(1, int(SR * dur))
    t = np.arange(n) / SR
    f = f0 * (f1 / f0) ** (t / dur)                 # smooth glide from f0 to f1
    if vib:
        f = f * (1 + vib * np.sin(2 * np.pi * vib_hz * t))
    ph = 2 * np.pi * np.cumsum(f) / SR
    if buzz:                                         # grumpy: harsh, square-ish
        w = 0.55 * np.sign(np.sin(ph)) + 0.45 * np.sin(ph)
    else:                                            # cute: soft with a little brightness
        w = np.sin(ph) + 0.22 * np.sin(2 * ph) + 0.08 * np.sin(3 * ph)
    env = np.ones(n)
    a = min(n, int(SR * 0.008))
    r = min(n - a, int(n * 0.35))
    env[:a] = np.linspace(0, 1, a)
    if r > 0:
        env[-r:] = np.linspace(1, 0, r) ** 2
    return w * env * amp


def _gap(dur):
    return np.zeros(int(SR * dur))


def _sylls(count, f_lo, f_hi, rise, dur, gap, **kw):
    parts = []
    for _ in range(count):
        f0 = random.uniform(f_lo, f_hi)
        d = random.uniform(*dur)
        parts += [_tone(f0, f0 * random.uniform(*rise), d, **kw), _gap(random.uniform(*gap))]
    return parts


def make(emotion):
    """Returns float32 samples (-1..1) for an emotion."""
    r = random.randint
    if emotion == "happy":
        p = _sylls(r(3, 6), 900, 1400, (1.15, 1.5), (0.06, 0.11), (0.02, 0.05))
    elif emotion == "excited":
        p = _sylls(r(6, 9), 1100, 1700, (1.2, 1.6), (0.04, 0.08), (0.01, 0.03))
        p.append(_tone(1200, 2400, 0.22))
    elif emotion == "angry":
        p = _sylls(r(2, 4), 210, 320, (0.8, 0.95), (0.12, 0.18), (0.04, 0.07), buzz=True, amp=0.8)
    elif emotion == "sad":
        p = [_tone(random.uniform(650, 780), 380, random.uniform(0.35, 0.5), vib=0.02, vib_hz=6), _gap(0.08),
             _tone(560, 320, random.uniform(0.4, 0.55), vib=0.025, vib_hz=5)]
    elif emotion == "curious":
        p = _sylls(2, 650, 800, (0.95, 1.05), (0.07, 0.1), (0.05, 0.08))
        p.append(_tone(600, random.uniform(1050, 1250), 0.25))
    elif emotion == "sleepy":
        p = [_tone(480, 820, 0.35, amp=0.6), _tone(820, 340, 0.6, vib=0.01, vib_hz=4, amp=0.6)]
    elif emotion == "love":
        p = []
        for _ in range(3):
            f = random.uniform(760, 900)
            p += [_tone(f, f * 1.1, 0.25, vib=0.06, vib_hz=9, amp=0.8), _gap(0.06)]
    elif emotion == "no":
        p = _sylls(2, 700, 800, (0.6, 0.7), (0.08, 0.1), (0.04, 0.05))
    elif emotion == "yes":
        p = _sylls(2, 700, 800, (1.4, 1.6), (0.08, 0.1), (0.04, 0.05))
    else:  # hello
        p = [_tone(700, 1000, 0.09), _gap(0.03), _tone(1000, 800, 0.08), _gap(0.03), _tone(850, 1400, 0.16)]
    x = np.concatenate(p).astype(np.float32)
    return x / (np.max(np.abs(x)) + 1e-9) * 0.9


class Pochi:
    """The creature voice. Settings are read on every call, so the app's changes apply at once."""

    def __init__(self, cfg, player):
        self.cfg = cfg
        self.player = player

    def say(self, emotion):
        a = self.cfg.get("audio", {})
        if not a.get("pochi", True):
            return
        try:
            pcm = (make(emotion) * float(a.get("volume", 0.8)) * 32767).astype("<i2").tobytes()
            self.player.play(pcm, SR)
        except Exception as e:  # never let a sound problem stop the pet
            log.warning("chirp %s failed: %s", emotion, e)
