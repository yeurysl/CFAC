# api_territories.py
from flask import Blueprint, request, jsonify
from flask import current_app as app
from datetime import datetime
from bson import ObjectId
import jwt
from math import inf

api_territories_bp = Blueprint("api_territories", __name__)

def require_auth(f):
    # very simple bearer check using your JWT secret; adapt to your auth layer
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "Unauthorized"}), 401
        token = auth.split(" ", 1)[1]
        try:
            payload = jwt.decode(token, app.config["JWT_SECRET_KEY"], algorithms=["HS256"])
        except Exception as e:
            return jsonify({"error": "Unauthorized"}), 401
        request.user = payload  # attach for downstream use
        return f(*args, **kwargs)
    return wrapper

def ensure_closed_ring(ring):
    # ring: [[lon,lat], ...]
    if not ring or len(ring) < 4:
        return None
    if ring[0] != ring[-1]:
        ring = ring + [ring[0]]
    return ring

def calc_bbox(ring):
    minLon, minLat, maxLon, maxLat = inf, inf, -inf, -inf
    for lon, lat in ring:
        minLon = min(minLon, lon)
        minLat = min(minLat, lat)
        maxLon = max(maxLon, lon)
        maxLat = max(maxLat, lat)
    return [minLon, minLat, maxLon, maxLat]

def calc_centroid(ring):
    # simple average (ok for small local polygons); for production, use shapely/geo lib
    lons = [p[0] for p in ring[:-1]]  # ignore duplicated last == first
    lats = [p[1] for p in ring[:-1]]
    return [sum(lons) / len(lons), sum(lats) / len(lats)]

@api_territories_bp.route("/api/territories", methods=["POST"])
@require_auth
def create_territory():
    """
    Body:
    {
      "ring_lonlat": [[lon,lat], ..., [lon,lat]],  // may be open; we will close it
      "name": "Territory 7"  // optional; if missing we auto-name
    }
    """
    db = app.config["MONGO_DB"]
    data = request.get_json(silent=True) or {}

    ring = data.get("ring_lonlat")
    if not ring or len(ring) < 3:
        return jsonify({"error": "ring_lonlat must have >= 3 vertices"}), 400

    ring = ensure_closed_ring(ring + [])  # copy
    if not ring:
        return jsonify({"error": "invalid ring"}), 400

    # Auto-name if not provided: "Territory N" per user
    name = data.get("name")
    if not name:
        count = db.territories.count_documents({"user_id": request.user.get("sub")})
        name = f"Territory {count + 1}"

    doc = {
        "user_id": request.user.get("sub"),
        "name": name,
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "bbox": calc_bbox(ring),
        "centroid": {"type": "Point", "coordinates": calc_centroid(ring)},
        "created_at": datetime.utcnow()
    }

    res = db.territories.insert_one(doc)
    doc["_id"] = str(res.inserted_id)
    return jsonify(doc), 201

@api_territories_bp.route("/api/territories", methods=["GET"])
@require_auth
def list_territories():
    db = app.config["MONGO_DB"]
    cur = db.territories.find({"user_id": request.user.get("sub")}).sort("created_at", -1)
    items = []
    for d in cur:
        d["_id"] = str(d["_id"])
        items.append(d)
    return jsonify(items), 200
