"""The girl's voice: Piper TTS running on the Pi.

- The voice model loads once and stays in memory, in a background thread, so the pet starts at once.
- Cute pitch without a chipmunk tempo: Piper speaks slower (length_scale x pitch), and the audio plays faster
  (sample rate x pitch). The pitch goes up while the tempo stays at the chosen speed.
- Every sentence is cached as a WAV, so repeated lines play instantly. A Pi 3 needs about a second or more for a
  new sentence (measure).
- A missing voice model is downloaded once from Hugging Face (rhasspy/piper-voices) into <data>/voices.
"""
import hashlib
import logging
import os
import queue
import threading
import urllib.request
import wave

log = logging.getLogger("voice")
HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
VOICES = {   # id -> path in rhasspy/piper-voices (all female English voices, checked 2026-11-24)
    "en_US-amy-medium": "en/en_US/amy/medium/",
    "en_US-amy-low": "en/en_US/amy/low/",
    "en_US-kristin-medium": "en/en_US/kristin/medium/",
    "en_US-hfc_female-medium": "en/en_US/hfc_female/medium/",
    "en_US-lessac-medium": "en/en_US/lessac/medium/",
    "en_GB-jenny_dioco-medium": "en/en_GB/jenny_dioco/medium/",
    "en_GB-cori-medium": "en/en_GB/cori/medium/",
}


class Voice:
    def __init__(self, cfg, data_dir, player):
        self.cfg = cfg
        self.player = player
        self.dir = os.path.join(data_dir, "voices")
        self.cache = os.path.join(data_dir, "voice_cache")
        self.engine = None
        self.engine_id = None
        self.state = "not loaded"
        self.last = ""
        self.q = queue.Queue(maxsize=5)
        threading.Thread(target=self._run, name="voice", daemon=True).start()

    def conf(self):
        v = self.cfg.get("voice", {})
        return (bool(v.get("enabled", True)), v.get("model", "en_US-amy-medium"),
                float(v.get("pitch", 1.12)), float(v.get("speed", 1.0)), float(self.cfg.get("audio", {}).get("volume", 0.8)))

    def say(self, text):
        text = " ".join(str(text).split())[:300]
        if not text:
            return
        self.last = text
        log.info("say: %s", text)
        try:
            self.q.put_nowait(text)
        except queue.Full:
            log.info("voice queue full, dropped: %s", text)

    def preload(self):
        self.q.put(None)

    # ---- worker -----------------------------------------------------------------------------
    def _run(self):
        while True:
            text = self.q.get()
            on, model, pitch, speed, volume = self.conf()
            try:
                if not self._load(model):
                    continue
                if text is None or not on:
                    continue
                pcm, rate = self._synth(text, model, pitch, speed, volume)
                self.player.play(pcm, int(rate * pitch))
            except Exception as e:
                self.state = f"error: {e}"
                log.warning("voice failed: %s", e)

    def _load(self, model):
        if self.engine is not None and self.engine_id == model:
            return True
        try:
            from piper import PiperVoice
        except ImportError:
            self.state = "piper not installed"
            return False
        onnx = os.path.join(self.dir, model + ".onnx")
        if not os.path.exists(onnx):
            self._download(model)
        self.state = "loading"
        self.engine = PiperVoice.load(onnx)
        self.engine_id = model
        self.state = "ready"
        return True

    def _download(self, model):
        if model not in VOICES:
            raise ValueError(f"unknown voice {model}")
        os.makedirs(self.dir, exist_ok=True)
        for ext in (".onnx.json", ".onnx"):
            self.state = f"downloading {model}{ext}"
            url = HF + VOICES[model] + model + ext
            tmp = os.path.join(self.dir, model + ext + ".part")
            with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
                while chunk := r.read(1 << 16):
                    f.write(chunk)
            os.replace(tmp, os.path.join(self.dir, model + ext))

    def _synth(self, text, model, pitch, speed, volume):
        key = hashlib.sha1(f"{model}|{pitch:.2f}|{speed:.2f}|{volume:.2f}|{text}".encode()).hexdigest()[:20]
        path = os.path.join(self.cache, key + ".wav")
        if not os.path.exists(path):
            from piper import SynthesisConfig
            os.makedirs(self.cache, exist_ok=True)
            self.state = "speaking (new line)"
            syn = SynthesisConfig(length_scale=pitch / max(0.5, speed), volume=volume)
            with wave.open(path + ".part", "wb") as w:
                self.engine.synthesize_wav(text, w, syn_config=syn)
            os.replace(path + ".part", path)
            self._trim_cache()
        with wave.open(path, "rb") as w:
            self.state = "ready"
            return w.readframes(w.getnframes()), w.getframerate()

    def _trim_cache(self, keep=400):
        files = sorted((os.path.join(self.cache, f) for f in os.listdir(self.cache) if f.endswith(".wav")),
                       key=os.path.getmtime)
        for f in files[:-keep]:
            os.remove(f)
