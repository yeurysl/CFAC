# api_territories.py

from flask import Blueprint, request, jsonify
from flask import current_app as app
from datetime import datetime
import os
from math import inf
import jwt
from bson import ObjectId  # keep if you later want to store ObjectIds
from extensions import csrf

from pymongo import MongoClient
from urllib.parse import urlparse

api_territories_bp = Blueprint("api_territories", __name__)

# -------------------------------
# DB helper (uses MONGODB_URI)
# -------------------------------
def get_db():
    global _client
    if _client is None:
        _client = MongoClient(os.environ["MONGODB_URI"], tls=True, tlsAllowInvalidCertificates=False)
    db_name = os.environ.get("MONGODB_DB")
    if not db_name:
        # try to read default db from URI; raise clear error if absent
        raise RuntimeError("MONGODB_DB not set and URI has no default database")
    return _client[db_name]


# -------------------------------
# Auth helper (uses JWT_SECRET)
# -------------------------------
def require_auth(f):
    from functools import wraps

    @wraps(f)
    def wrapper(*args, **kwargs):
        print("\n[AUTH] Checking Authorization Header...")
        auth = request.headers.get("Authorization", "")
        print(f"[AUTH] Raw Authorization Header: {auth}")

        if not auth.startswith("Bearer "):
            print("[AUTH] Missing or malformed Bearer token.")
            return jsonify({"error": "Unauthorized"}), 401

        token = auth.split(" ", 1)[1]
        print(f"[AUTH] Extracted JWT Token: {token[:40]}... (truncated)")

        secret = app.config.get("JWT_SECRET")
        if not secret:
            print("[AUTH ERROR] JWT_SECRET not configured in app.config (env).")
            return jsonify({"error": "Server auth misconfigured"}), 500

        try:
            payload = jwt.decode(token, secret, algorithms=["HS256"])
            print(f"[AUTH] Decoded JWT Payload: {payload}")
        except jwt.ExpiredSignatureError:
            print("[AUTH ERROR] Token expired.")
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError as e:
            print(f"[AUTH ERROR] Invalid token: {e}")
            return jsonify({"error": "Unauthorized"}), 401
        except Exception as e:
            print(f"[AUTH ERROR] Failed to decode JWT: {e}")
            return jsonify({"error": "Unauthorized"}), 401

        request.user = payload
        print(f"[AUTH] Authenticated user: {request.user}")
        return f(*args, **kwargs)

    return wrapper


# -------------------------------
# Geometry helpers
# -------------------------------
def ensure_closed_ring(ring):
    print(f"\n[GEOMETRY] Ensuring closed ring for coordinates. Input length: {len(ring)}")
    if not ring or len(ring) < 3:
        print("[GEOMETRY] Invalid ring: fewer than 3 vertices.")
        return None
    print(f"[GEOMETRY] First point: {ring[0]}, Last point: {ring[-1]}")
    if ring[0] != ring[-1]:
        print("[GEOMETRY] Ring not closed; appending first point to end.")
        ring = ring + [ring[0]]
    else:
        print("[GEOMETRY] Ring already closed.")
    print(f"[GEOMETRY] Final ring length: {len(ring)}")
    return ring


def calc_bbox(ring):
    print("\n[GEOMETRY] Calculating bounding box...")
    minLon, minLat, maxLon, maxLat = inf, inf, -inf, -inf
    for i, (lon, lat) in enumerate(ring):
        minLon = min(minLon, lon)
        minLat = min(minLat, lat)
        maxLon = max(maxLon, lon)
        maxLat = max(maxLat, lat)
        print(f"[GEOMETRY] Point {i}: ({lon}, {lat}) -> BBox so far: [{minLon}, {minLat}, {maxLon}, {maxLat}]")
    bbox = [minLon, minLat, maxLon, maxLat]
    print(f"[GEOMETRY] Final Bounding Box: {bbox}")
    return bbox


def calc_centroid(ring):
    print("\n[GEOMETRY] Calculating centroid for polygon...")
    lons = [p[0] for p in ring[:-1]]  # ignore duplicate last point
    lats = [p[1] for p in ring[:-1]]
    centroid = [sum(lons) / len(lons), sum(lats) / len(lats)]
    print(f"[GEOMETRY] Centroid calculated: {centroid}")
    return centroid


# -------------------------------
# Routes
# -------------------------------
@api_territories_bp.route("/api/territories", methods=["POST"])
@require_auth
@csrf.exempt
def create_territory():
    print("\n=== [POST] /api/territories called ===")
    db = _get_db()
    if not db:
        print("[POST ERROR] DB handle unavailable (check MONGODB_URI and DB name).")
        return jsonify({"error": "Server DB misconfigured"}), 500

    data = request.get_json(silent=True) or {}
    print(f"[POST] Received JSON data: {data}")

    ring = data.get("ring_lonlat")
    if not ring or len(ring) < 3:
        print("[POST ERROR] Invalid or missing 'ring_lonlat'.")
        return jsonify({"error": "ring_lonlat must have >= 3 vertices"}), 400

    print(f"[POST] Received ring with {len(ring)} points.")
    ring = ensure_closed_ring(ring + [])  # copy the list
    if not ring:
        print("[POST ERROR] ensure_closed_ring returned None — invalid ring.")
        return jsonify({"error": "invalid ring"}), 400

    # Auto-name if not provided
    name = data.get("name")
    user_id = request.user.get("sub")
    if not name:
        print(f"[POST] No name provided. Counting existing territories for user: {user_id}")
        try:
            count = db.territories.count_documents({"user_id": user_id})
        except Exception as e:
            print(f"[POST ERROR] Counting territories failed: {e}")
            return jsonify({"error": "Database query failed"}), 500
        print(f"[POST] Found {count} existing territories.")
        name = f"Territory {count + 1}"
    print(f"[POST] Using territory name: '{name}'")

    bbox = calc_bbox(ring)
    centroid = calc_centroid(ring)

    doc = {
        "user_id": user_id,  # keep as string unless your schema expects ObjectId
        "name": name,
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "bbox": bbox,
        "centroid": {"type": "Point", "coordinates": centroid},
        "created_at": datetime.utcnow(),
    }

    print(f"[POST] Document ready for insertion: {doc}")

    try:
        res = db.territories.insert_one(doc)
        doc["_id"] = str(res.inserted_id)
        print(f"[POST] MongoDB insert OK. _id={doc['_id']}")
    except Exception as e:
        print(f"[POST ERROR] Failed to insert into MongoDB: {e}")
        return jsonify({"error": "Database insertion failed"}), 500

    print(f"[POST] Successfully created territory: {doc}")
    return jsonify(doc), 201


@api_territories_bp.route("/api/territories", methods=["GET"])
@require_auth
@csrf.exempt
def list_territories():
    print("\n=== [GET] /api/territories called ===")
    db = _get_db()
    if not db:
        print("[GET ERROR] DB handle unavailable (check MONGODB_URI and DB name).")
        return jsonify({"error": "Server DB misconfigured"}), 500

    user_id = request.user.get("sub")
    print(f"[GET] Fetching territories for user_id: {user_id}")

    try:
        cur = db.territories.find({"user_id": user_id}).sort("created_at", -1)
        print("[GET] Query executed successfully.")
    except Exception as e:
        print(f"[GET ERROR] MongoDB query failed: {e}")
        return jsonify({"error": "Database query failed"}), 500

    items = []
    count = 0
    for d in cur:
        d["_id"] = str(d["_id"])
        items.append(d)
        count += 1
        print(f"[GET] Loaded document #{count}: {d}")

    print(f"[GET] Total territories found: {count}")
    return jsonify(items), 200


# Optional: add this to remove the 404 for /api/houses-in-area
@api_territories_bp.route("/api/houses-in-area", methods=["POST"])
@require_auth
@csrf.exempt
def houses_in_area():
    print("\n=== [POST] /api/houses-in-area called ===")
    body = request.get_json(silent=True) or {}
    print(f"[HOUSES] Input: {body}")
    # TODO: implement your spatial lookup here
    return jsonify({"ok": True, "message": "stub"}), 200
