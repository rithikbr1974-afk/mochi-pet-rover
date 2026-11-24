"""Mochi's current feeling: a label the app's eyes draw, plus valence (happy/upset) and arousal (calm/excited).
An emotion fades back to calm after a while. The mind (phase 5) will drive it from needs and rewards."""
import time

FEEL = {  # label -> (valence, arousal)
    "neutral": (0.0, 0.3), "happy": (0.8, 0.6), "excited": (0.9, 1.0), "angry": (-0.7, 0.9),
    "sad": (-0.7, 0.2), "curious": (0.3, 0.6), "sleepy": (0.1, 0.0), "love": (1.0, 0.5),
    "focused": (0.2, 0.5), "confused": (-0.2, 0.5),
}


class Emotion:
    def __init__(self):
        self.label = "neutral"
        self.until = 0.0

    def set(self, label, hold=8.0):
        if label in ("yes", "no", "spin"):
            label = "happy" if label != "no" else "confused"
        if label in FEEL:
            self.label = label
            self.until = time.time() + hold

    def now(self, busy=False):
        if time.time() > self.until:
            hour = time.localtime().tm_hour
            self.label = "focused" if busy else ("sleepy" if hour >= 23 or hour < 6 else "neutral")
        v, a = FEEL[self.label]
        return {"label": self.label, "valence": v, "arousal": a}
