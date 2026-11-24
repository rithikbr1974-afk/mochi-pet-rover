"""One speaker, one queue: chirps and the girl's voice take turns and never fight over the sound card.
On the Pi it plays through aplay; on a PC (no aplay) each sound is written to <data>/last_sound.wav."""
import logging
import os
import queue
import shutil
import subprocess
import threading
import wave

log = logging.getLogger("audio")


class Player:
    def __init__(self, cfg, data_dir):
        self.cfg = cfg
        self.data_dir = data_dir
        self.aplay = shutil.which("aplay")
        self.q = queue.Queue(maxsize=6)
        self.busy = False
        threading.Thread(target=self._run, name="audio", daemon=True).start()

    def play(self, pcm, rate):
        """pcm: 16-bit mono little-endian bytes. Dropped if 6 sounds are already waiting."""
        try:
            self.q.put_nowait((pcm, int(rate)))
        except queue.Full:
            log.info("sound queue full, dropped one")

    def clear(self):
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except queue.Empty:
                break

    def _run(self):
        while True:
            pcm, rate = self.q.get()
            self.busy = True
            try:
                self._play(pcm, rate)
            except Exception as e:  # a sound problem must never stop the pet
                log.warning("play failed: %s", e)
            self.busy = self.q.qsize() > 0

    def _play(self, pcm, rate):
        if not self.aplay:
            os.makedirs(self.data_dir, exist_ok=True)
            with wave.open(os.path.join(self.data_dir, "last_sound.wav"), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate)
                w.writeframes(pcm)
            return
        device = self.cfg.get("audio", {}).get("device", "default")
        for dev in dict.fromkeys((device, "default")):
            p = subprocess.run([self.aplay, "-q", "-D", dev, "-f", "S16_LE", "-r", str(rate), "-c", "1", "-"],
                               input=pcm, capture_output=True, timeout=60)
            if p.returncode == 0:
                return
            log.warning("aplay on %s failed: %s", dev, p.stderr.decode(errors="replace").strip()[:200])
