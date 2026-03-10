"""
Fisherman Safety — Backend Server
===================================
Deploy this to Render.com (free tier).

Setup on Render:
  1. Push this file + requirements.txt to a GitHub repo
  2. New Web Service → connect repo → set:
       Build Command:  pip install -r requirements.txt
       Start Command:  gunicorn server:app
  3. Copy the Render URL (e.g. https://fisherman-safety.onrender.com)
  4. Paste it into tracker.html  → SERVER_URL
  5. Paste it into coast_guard_app.py → SERVER_URL
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__)
CORS(app)  # Allow tracker.html (GitHub Pages) to POST here

# In-memory store — persists while server is running
# Format: { "FSH001": { id, name, lat, lon, accuracy, updated } }
locations = {}

# ── Health check ──────────────────────────────────────────────────────────
@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "status": "online",
        "service": "Fisherman Safety Monitoring Server",
        "fishermen_tracked": len(locations),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

# ── Receive location from tracker.html ───────────────────────────────────
@app.route("/update_location", methods=["POST"])
def update_location():
    data = request.get_json(force=True)
    fid  = data.get("id", "").strip()
    if not fid:
        return jsonify({"error": "missing id"}), 400

    locations[fid] = {
        "id":       fid,
        "name":     data.get("name", fid),
        "lat":      float(data.get("lat", 0)),
        "lon":      float(data.get("lon", 0)),
        "accuracy": float(data.get("accuracy", 0)),
        "updated":  datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    print(f"[{locations[fid]['updated']}] Location updated: {fid} → "
          f"{locations[fid]['lat']:.5f}, {locations[fid]['lon']:.5f}")
    return jsonify({"status": "ok", "id": fid})

# ── Return all locations (coast_guard_app polls this) ────────────────────
@app.route("/locations", methods=["GET"])
def get_all_locations():
    return jsonify(list(locations.values()))

# ── Return single fisherman location (used by tracker.html on load) ──────
@app.route("/locations/<fid>", methods=["GET"])
def get_location(fid):
    loc = locations.get(fid)
    if loc:
        return jsonify(loc)
    # Return name from known fishermen list (so tracker.html can show name)
    known_names = {
        "FSH001": "Rajan Kumar",    "FSH002": "Murugan S",
        "FSH003": "Sathish P",      "FSH004": "Biju Thomas",
        "FSH005": "Anwar Hussain",  "FSH006": "Pradeep Nair",
        "FSH007": "Suresh Pillai",  "FSH008": "Dasan V",
        "FSH009": "Krishnan M",     "FSH010": "Joseph Antony",
    }
    name = known_names.get(fid)
    if name:
        return jsonify({"id": fid, "name": name})
    return jsonify({"error": "not found"}), 404

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
