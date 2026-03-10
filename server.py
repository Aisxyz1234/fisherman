"""
Fisherman Safety Monitoring System - Flask Server v5.0
=======================================================
Accepts location from:
  - Traccar Client app (Android) — GET request with query parameters
  - GPS Logger app              — POST request with JSON body
  - Any HTTP POST with JSON     — generic format

Run:
  pip install flask flask-cors
  python server.py

Traccar Client settings on phone:
  Server URL:  http://192.168.0.125:5000
  Device ID:   FSH001   (change for each fisherman)
  Interval:    60 seconds
  Port:        5000
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime
import json, os, threading, socket

app = Flask(__name__)
CORS(app)

# ── Location store ─────────────────────────────────────────────────────────
LOCATIONS_FILE = "fisherman_locations.json"
locations = {}
lock = threading.Lock()

# ── Registered fishermen names (so we show names not just IDs) ─────────────
FISHERMAN_NAMES = {
    "FSH001": "Rajan Kumar",
    "FSH002": "Murugan S",
    "FSH003": "Sathish P",
    "FSH004": "Biju Thomas",
    "FSH005": "Anwar Hussain",
    "FSH006": "Pradeep Nair",
    "FSH007": "Suresh Pillai",
    "FSH008": "Dasan V",
    "FSH009": "Krishnan M",
    "FSH010": "Joseph Antony",
}

def load_locations():
    global locations
    if os.path.exists(LOCATIONS_FILE):
        try:
            with open(LOCATIONS_FILE, encoding="utf-8") as f:
                locations = json.load(f)
        except:
            locations = {}

def save_locations():
    try:
        with open(LOCATIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(locations, f, indent=2)
    except:
        pass

def store_location(fid, name, lat, lon, acc=0):
    """Store location and print to console."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with lock:
        locations[fid] = {
            "id":       fid,
            "name":     name,
            "lat":      lat,
            "lon":      lon,
            "accuracy": acc,
            "updated":  ts,
            "status":   "active"
        }
        save_locations()
    print(f"[{ts}] GPS OK — {name} ({fid}): {lat:.5f}, {lon:.5f}  acc={acc:.0f}m")
    return ts

load_locations()

# ══════════════════════════════════════════════════════════════════
#  TRACCAR CLIENT ENDPOINT
#  Traccar sends:  GET /?id=FSH001&lat=9.93&lon=76.26&...
#  This is the standard Traccar OsmAnd protocol
# ══════════════════════════════════════════════════════════════════
@app.route("/")
def traccar_or_index():
    """
    Traccar Client sends location as GET request to root URL with params.
    If no params, return server status.
    """
    # check if this is a Traccar location update
    fid = request.args.get("id", "").strip()
    lat = request.args.get("lat", "")
    lon = request.args.get("lon", "")

    if fid and lat and lon:
        # ── This is a Traccar location update ──
        try:
            lat  = float(lat)
            lon  = float(lon)
            acc  = float(request.args.get("accuracy", 0))
            name = FISHERMAN_NAMES.get(fid, f"Fisherman {fid}")
            store_location(fid, name, lat, lon, acc)
            return "OK", 200
        except Exception as e:
            print(f"Traccar parse error: {e}")
            return "ERROR", 400

    # ── No params — return server status ──
    with lock:
        count = len(locations)
    return jsonify({
        "status":  "running",
        "service": "Fisherman Safety Monitoring Server",
        "version": "5.0",
        "active_fishermen": count,
        "time":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "note":    "Traccar Client: set server URL to this address, port 5000"
    })

# ══════════════════════════════════════════════════════════════════
#  GENERIC JSON POST ENDPOINT
#  For GPS Logger app or any custom POST
# ══════════════════════════════════════════════════════════════════
@app.route("/update_location", methods=["POST", "GET"])
def update_location():
    """Accept location via POST JSON or GET params."""
    try:
        # try JSON body first
        data = request.get_json(silent=True)

        # if no JSON, try form data
        if not data:
            data = request.form.to_dict()

        # if no form data, try query params
        if not data:
            data = request.args.to_dict()

        if not data:
            return jsonify({"status": "error", "message": "No data received"}), 400

        fid  = str(data.get("id",  "")).strip()
        lat  = float(data.get("lat",  0))
        lon  = float(data.get("lon",  0))
        acc  = float(data.get("accuracy", 0))
        name = str(data.get("name", FISHERMAN_NAMES.get(fid, f"Fisherman {fid}"))).strip()

        if not fid:
            return jsonify({"status": "error", "message": "id required"}), 400

        ts = store_location(fid, name, lat, lon, acc)
        return jsonify({"status": "ok", "timestamp": ts})

    except Exception as e:
        print(f"update_location error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ══════════════════════════════════════════════════════════════════
#  GET ALL LOCATIONS — Coast Guard app reads this
# ══════════════════════════════════════════════════════════════════
@app.route("/locations")
def get_locations():
    with lock:
        data = list(locations.values())
    return jsonify(data)

@app.route("/locations/<fisherman_id>")
def get_one(fisherman_id):
    with lock:
        loc = locations.get(fisherman_id)
    if loc:
        return jsonify(loc)
    return jsonify({"status": "not found"}), 404

@app.route("/status")
def status():
    with lock:
        locs = list(locations.values())
    return jsonify({
        "status": "ok",
        "fishermen_tracked": len(locs),
        "fishermen": locs
    })

# ══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    # get correct local IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except:
        ip = "127.0.0.1"

    print("=" * 65)
    print("  Fisherman Safety Monitoring Server  v5.0")
    print("=" * 65)
    print(f"\n  Server IP : {ip}")
    print(f"  Port      : 5000")
    print()
    print("  TRACCAR CLIENT SETTINGS (on fisherman's phone):")
    print(f"    Server URL  :  http://{ip}:5000")
    print(f"    Device ID   :  FSH001  (change per fisherman)")
    print(f"    Port        :  5000")
    print(f"    Interval    :  60 seconds")
    print(f"    Protocol    :  OSMand  (or OsmAnd)")
    print()
    print("  Coast Guard app reads from:")
    print(f"    http://{ip}:5000/locations")
    print()
    print("  Test in browser:")
    print(f"    http://{ip}:5000/status")
    print()
    print("  Press Ctrl+C to stop")
    print("=" * 65)

    app.run(host="0.0.0.0", port=5000, debug=False)
