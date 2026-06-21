#!/usr/bin/env python3
"""
Pi Zero Sensor Dashboard Server v2
Serves a professional real-time dashboard + full-screen chart modal.
Proxies EdgeX Core Data API (localhost only).
"""

import os, sys, json, time, urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler
from datetime import datetime

EDGEX_CORE_DATA = "http://localhost:59880"
EDGEX_METADATA = "http://localhost:59881"

HTML = None
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def load_html():
    global HTML
    if HTML is None:
        html_path = os.path.join(SCRIPT_DIR, "dashboard.html")
        with open(html_path) as f:
            HTML = f.read()
    return HTML

def fetch_edgex(endpoint):
    try:
        req = urllib.request.Request(f"{EDGEX_CORE_DATA}{endpoint}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}

def fetch_metadata(endpoint):
    try:
        req = urllib.request.Request(f"{EDGEX_METADATA}{endpoint}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}

def build_readings():
    devices = ["pizero1", "pizero2"]
    result = {"devices": {}, "timestamp": datetime.now().isoformat(), "totalReadings": 0}
    try:
        r = urllib.request.urlopen("http://localhost:59880/api/v3/reading/count", timeout=3)
        result["totalReadings"] = json.loads(r.read()).get("count", 0)
    except:
        pass

    for dev in devices:
        data = fetch_edgex(f"/api/v3/reading/device/name/{dev}?limit=100")
        readings = data.get("readings", [])

        meta = fetch_metadata(f"/api/v3/device/name/{dev}")
        device_info = meta.get("device", {})
        status = "UP" if device_info else "DOWN"

        latest = {}
        history = {}
        has_data = False

        for rd in readings:
            res = rd["resourceName"]
            origin = rd.get("origin", 0)
            try:
                val = float(rd.get("value", 0))
            except (ValueError, TypeError):
                continue

            if res not in latest or origin > latest[res].get("origin", 0):
                latest[res] = {"value": val, "time": origin // 1_000_000_000}

            if res not in history:
                history[res] = []
            history[res].append({"t": origin // 1_000_000_000, "v": val})
            has_data = True

        for res in history:
            history[res].sort(key=lambda x: x["t"])
            history[res] = history[res][-30:]

        result["devices"][dev] = {
            "status": status if has_data else "DOWN",
            "latest": latest,
            "history": history
        }

    return result

class DashboardHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(load_html().encode("utf-8"))

        elif self.path.startswith("/api/history?"):
            from urllib.parse import urlparse, parse_qs
            params = parse_qs(urlparse(self.path).query)
            device = params.get("device", [None])[0]
            resource = params.get("resource", [None])[0]
            hours = float(params.get("range", ["1"])[0])

            if not device or not resource:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error":"device and resource required"}')
                return

            now_ns = time.time_ns()
            start_ns = now_ns - int(hours * 3600 * 1_000_000_000)
            import math
            limit = min(int(hours * 200), 5000)

            url = f"{EDGEX_CORE_DATA}/api/v3/reading/device/name/{device}/start/{start_ns}/end/{now_ns}?limit={limit}"
            try:
                r = urllib.request.urlopen(url, timeout=8)
                edgex_data = json.loads(r.read())
                readings = edgex_data.get("readings", [])
                filtered = [
                    {"t": rd["origin"] / 1_000_000_000, "v": float(rd["value"].replace("e+", "e"))}
                    for rd in readings if rd["resourceName"] == resource
                ]
                filtered.sort(key=lambda x: x["t"])
                result = {
                    "device": device, "resource": resource,
                    "range_hours": hours, "points": len(filtered),
                    "data": filtered
                }
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode("utf-8"))
            except Exception as ex:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(ex)}).encode("utf-8"))

        elif self.path == "/api/readings":
            data = build_readings()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))

        elif self.path == "/manifest.json":
            self._serve_file(os.path.join(SCRIPT_DIR, "manifest.json"), "application/manifest+json")

        elif self.path == "/sw.js":
            self._serve_file(os.path.join(SCRIPT_DIR, "sw.js"), "text/javascript")

        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error":"not found"}')

    def _serve_file(self, path, mime):
        try:
            with open(path, 'rb') as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error":"file not found"}')

    def log_message(self, format, *args):
        if "404" in str(args):
            super().log_message(format, *args)

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9090
    server = HTTPServer(("0.0.0.0", port), DashboardHandler)
    print(f"📊 Pi Zero Dashboard → http://0.0.0.0:{port}")
    server.serve_forever()
