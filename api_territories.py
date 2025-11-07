# api_territories.py
from flask import Blueprint, request, jsonify
from flask import current_app as app
from datetime import datetime
import os
from math import inf
import jwt
from extensions import csrf
from pymongo import MongoClient

api_territories_bp = Blueprint("api_territories", __name__)

# -------------------------------
# DB helper (uses MONGODB_URI)
# -------------------------------
_client = None  # <-- add this

def get_db():
    global _client
    uri = os.environ.get("MONGODB_URI")
    db_name = os.environ.get("MONGODB_DB")  # set this OR include /cfacdb in the URI

    if not uri:
        raise RuntimeError("MONGODB_URI not set")

    if _client is None:
        # Reuse a single client across requests
        _client = MongoClient(uri, tls=True, tlsAllowInvalidCertificates=False)

    if not db_name:
        # If you prefer pulling from the URI's path, parse it here instead of raising:
        # from urllib.parse import urlparse
        # parsed = urlparse(uri)
        # db_name = parsed.path.lstrip('/') or None
        raise RuntimeError("MONGODB_DB not set and URI has no default database name")

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
        print(f"[AUTH] Raw Authorization Header: {auth[:20]}... (truncated)" if auth else "[AUTH] Raw Authorization Header:")

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
    try:
        db = get_db()
    except Exception as e:
        print(f"[POST ERROR] DB handle unavailable: {e}")
        return jsonify({"error": "Server DB misconfigured"}), 500

    data = request.get_json(silent=True) or {}
    print(f"[POST] Received JSON data: {data}")

    ring = data.get("ring_lonlat")
    if not ring or len(ring) < 3:
        print("[POST ERROR] Invalid or missing 'ring_lonlat'.")
        return jsonify({"error": "ring_lonlat must have >= 3 vertices"}), 400

    ring = ensure_closed_ring(ring + [])
    if not ring:
        print("[POST ERROR] ensure_closed_ring returned None — invalid ring.")
        return jsonify({"error": "invalid ring"}), 400

    user_id = request.user.get("sub")
    LIMIT = 3  # ✅ hard limit per user

    # ✅ ENFORCE LIMIT
    try:
        existing = db.territories.count_documents({"user_id": user_id})
        print(f"[POST] Existing territories for user {user_id}: {existing}")
        if existing >= LIMIT:
            print(f"[POST] Limit reached (limit={LIMIT}). Rejecting creation.")
            return jsonify({
                "error": "territory_limit_reached",
                "message": f"You already have {LIMIT} territories.",
                "limit": LIMIT
            }), 400
    except Exception as e:
        print(f"[POST ERROR] Counting territories failed: {e}")
        return jsonify({"error": "Database query failed"}), 500

    # Name (auto if not provided)
    name = data.get("name")
    if not name:
        name = f"Territory {existing + 1}"
    print(f"[POST] Using territory name: '{name}'")

    bbox = calc_bbox(ring)
    centroid = calc_centroid(ring)

    doc = {
        "user_id": user_id,
        "name": name,
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "bbox": bbox,
        "centroid": {"type": "Point", "coordinates": centroid},
        "created_at": datetime.utcnow(),
    }

    try:
        res = db.territories.insert_one(doc)
        doc["_id"] = str(res.inserted_id)
        print(f"[POST] MongoDB insert OK. _id={doc['_id']}")
    except Exception as e:
        print(f"[POST ERROR] Failed to insert into MongoDB: {e}")
        return jsonify({"error": "Database insertion failed"}), 500

    return jsonify(doc), 201


@api_territories_bp.route("/api/territories", methods=["GET"])
@require_auth
@csrf.exempt
def list_territories():
    print("\n=== [GET] /api/territories called ===")
    try:
        db = get_db()
    except Exception as e:
        print(f"[GET ERROR] DB handle unavailable: {e}")
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
    for i, d in enumerate(cur, 1):
        d["_id"] = str(d["_id"])
        items.append(d)
        print(f"[GET] Loaded document #{i}: {d}")

    print(f"[GET] Total territories found: {len(items)}")
    return jsonify(items), 200


#//////////////////////////////////////// FETCH HOUSES 
@api_territories_bp.route("/api/houses-in-area", methods=["POST"])
@require_auth
@csrf.exempt
def houses_in_area():
    print("\n=== [POST] /api/houses-in-area called ===")
    try:
        db = get_db()
    except Exception as e:
        print(f"[HOUSES ERROR] DB handle unavailable: {e}")
        return jsonify({"error": "Server DB misconfigured"}), 500

    body = request.get_json(silent=True) or {}
    print(f"[HOUSES] Input: {body}")

    # Ensure geospatial index exists (no-op if already present)
    _ensure_houses_geo_index(db)

    # You can cap results to keep payload small
    LIMIT = min(int(body.get("limit", 500)), 1000)

    # Two modes: circle OR polygon
    circle = body.get("circle")
    polygon = body.get("polygon")

    if circle and polygon:
        print("[HOUSES ERROR] Both 'circle' and 'polygon' provided — ambiguous.")
        return jsonify({"error": "Provide either 'circle' or 'polygon', not both"}), 400

    query = None

    if circle:
        try:
            center = circle["center"]  # [lon, lat]
            radius_miles = float(circle["radius"])
            if not (isinstance(center, list) and len(center) == 2):
                raise ValueError("circle.center must be [lon, lat]")
            EARTH_RADIUS_MILES = 3959.0
            radius_radians = radius_miles / EARTH_RADIUS_MILES

            query = {
                "loc": {
                    "$geoWithin": {
                        "$centerSphere": [center, radius_radians]
                    }
                }
            }
            print(f"[HOUSES] Circle query center={center} radius_mi={radius_miles} (~{radius_radians:.6f} rad)")

        except Exception as e:
            print(f"[HOUSES ERROR] Bad circle payload: {e}")
            return jsonify({"error": f"Invalid circle: {e}"}), 400

    elif polygon:
        try:
            # polygon is [[lon, lat], ...]
            if not (isinstance(polygon, list) and len(polygon) >= 3):
                raise ValueError("polygon must be an array of [lon,lat] with >= 3 vertices")

            ring = [list(map(float, pt)) for pt in polygon]
            if len(ring) < 3:
                raise ValueError("polygon needs at least 3 vertices")

            # Ensure closed ring
            print(f"[HOUSES] Polygon received with {len(ring)} points; ensuring closed ring")
            ring = ensure_closed_ring(ring)
            if not ring:
                raise ValueError("invalid polygon ring")

            # GeoJSON polygon requires an array of linear rings
            geom = {
                "type": "Polygon",
                "coordinates": [ring]  # outer ring only (no holes)
            }

            # Use 2dsphere geometry query
            query = {
                "loc": {
                    "$geoWithin": {
                        "$geometry": geom
                    }
                }
            }
            print(f"[HOUSES] Polygon query prepared. Ring length={len(ring)} (closed)")

        except Exception as e:
            print(f"[HOUSES ERROR] Bad polygon payload: {e}")
            return jsonify({"error": f"Invalid polygon: {e}"}), 400

    else:
        print("[HOUSES ERROR] Missing 'circle' or 'polygon'")
        return jsonify({"error": "Provide 'circle' or 'polygon' in the request body"}), 400

    # Execute query
    try:
        cursor = db.houses.find(query).limit(LIMIT)
        items = list(cursor)
        print(f"[HOUSES] Matched {len(items)} house(s)")
    except Exception as e:
        print(f"[HOUSES ERROR] Mongo query failed: {e}")
        return jsonify({"error": "Database query failed"}), 500

    # Transform docs → client shape the iOS expects (lat/lon + minimal metadata)
    out = []
    for i, d in enumerate(items, 1):
        _id = str(d.get("_id", ""))
        addr = d.get("address") or d.get("addr") or ""
        city = d.get("city") or ""
        state = d.get("state") or ""
        zipc = d.get("zip") or d.get("zipcode") or ""

        lat = None
        lon = None
        if isinstance(d.get("loc"), dict):
            coords = d["loc"].get("coordinates")
            if isinstance(coords, list) and len(coords) == 2:
                lon, lat = float(coords[0]), float(coords[1])
        # (Optional) fallback if your schema has separate fields:
        if lat is None or lon is None:
            if "lat" in d and "lon" in d:
                lat = float(d["lat"])
                lon = float(d["lon"])

        if lat is None or lon is None:
            print(f"[HOUSES][WARN] Skipping _id={_id} — missing coordinates")
            continue

        out.append({
            "_id": _id,
            "address": addr,
            "city": city,
            "state": state,
            "zip": zipc,
            "lat": lat,
            "lon": lon,
        })
        if i <= 5:  # small preview
            print(f"[HOUSES] #{i}: {_id} {addr} {city} {state} {zipc} @ ({lat:.5f}, {lon:.5f})")

    return jsonify(out), 200


def _ensure_houses_geo_index(db):
    """
    Ensure a 2dsphere index on 'loc'. This is idempotent (Mongo no-ops if exists).
    Call on first request to be safe.
    """
    try:
        # if you also query by user_id/owner, consider a compound index:
        # db.houses.create_index([("user_id", 1), ("loc", "2dsphere")])
        db.houses.create_index([("loc", "2dsphere")])
        print("[HOUSES] 2dsphere index on 'loc' ensured")
    except Exception as e:
        print(f"[HOUSES WARN] Could not create 2dsphere index: {e}")
