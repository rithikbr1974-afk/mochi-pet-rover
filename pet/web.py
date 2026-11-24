"""The app's server: http://<pet>:8080 (home network or her own hotspot). Standard library only.

GET  /                 the app (web/)          GET /api/status, /api/settings, /api/wifi, /api/places
GET  /camera.jpg       a frame from the robot phone (IP Webcam), fetched by the Pi
POST /api/<command>    JSON in, {"ok", "msg"} out (see Pet.HANDLERS)
CORS is open so the Android app's start page (a file:// page) can look for her before opening the app.
"""
import json
import logging
import os
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("web")
WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css",
         ".svg": "image/svg+xml", ".json": "application/json", ".png": "image/png", ".webmanifest": "application/manifest+json"}


def serve(pet, port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/api/status", "/status"):
                return self._send(200, pet.status())
            if path == "/api/settings":
                return self._send(200, pet.settings.describe())
            if path == "/api/wifi":
                return self._send(200, pet.wifi.status())
            if path == "/api/places":
                return self._send(200, pet.places.summary())
            if path == "/camera.jpg":
                return self._camera()
            name = "index.html" if path == "/" else path.lstrip("/")
            full = os.path.realpath(os.path.join(WEB, name))
            if full.startswith(os.path.realpath(WEB) + os.sep) and os.path.isfile(full):
                with open(full, "rb") as f:
                    return self._send(200, f.read(), TYPES.get(os.path.splitext(full)[1], "application/octet-stream"))
            self._send(404, {"error": "not found"})

        def _camera(self):
            url = pet.cfg.get("camera", {}).get("url", "").rstrip("/")
            if not url.startswith("http"):
                return self._send(404, {"error": "no camera set"})
            try:
                with urllib.request.urlopen(url + "/shot.jpg", timeout=2) as r:
                    return self._send(200, r.read(2_000_000), "image/jpeg")
            except Exception as e:
                return self._send(502, {"error": f"camera: {e}"})

        def do_POST(self):
            n = min(int(self.headers.get("Content-Length") or 0), 8192)
            try:
                payload = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self._send(400, {"ok": False, "msg": "bad json"})
            name = self.path.split("?")[0].strip("/")
            name = name[4:] if name.startswith("api/") else name
            ok, msg = pet.command(name, payload)
            self._send(200 if ok else 400, {"ok": ok, "msg": msg})

    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    httpd.daemon_threads = True
    log.info("app on port %s", port)
    return httpd
