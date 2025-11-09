# api_territories.py
from flask import Blueprint, request, jsonify
from flask import current_app as app
from datetime import datetime
import os
from math import inf
import jwt
from extensions import csrf
from pymongo import MongoClient
from bson import ObjectId
from pymongo import UpdateOne

api_territories_bp = Blueprint("api_territories", __name__)

# -------------------------------
# DB helper (uses MONGODB_URI)
# -------------------------------
_client = None  # reuse a single client across requests

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
        # If you prefer pulling from the URI's path, parse it here.
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
# Routes: Territories
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
    LIMIT = 3  # hard limit per user

    # Enforce limit
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
    name = data.get("name") or f"Territory {existing + 1}"
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

# -------------------------------
# Houses: indexing & persistence
# -------------------------------
def _ensure_houses_indexes(db):
    """
    Create the geospatial and de-dup indexes for houses.
    Idempotent: safe to call on each request.
    """
    try:
        # Geo index for spatial queries
        db.houses.create_index([("loc", "2dsphere")])
        # Uniqueness per territory by address+zip
        db.houses.create_index(
            [("territory_id", 1), ("address", 1), ("zip", 1)],
            unique=True,
            name="uniq_per_territory_addr_zip"
        )
        print("[HOUSES] Indexes ensured (2dsphere + unique key).")
    except Exception as e:
        print(f"[HOUSES WARN] Ensuring indexes failed: {e}")

def _normalize_house_for_db(h, user_id, territory_id):
    """
    Convert an item from Overpass into our Mongo shape for `houses`.
    """
    lon = float(h["lon"])
    lat = float(h["lat"])
    return {
        "user_id": user_id,
        "territory_id": ObjectId(territory_id),
        "address": h.get("address") or "",
        "city": h.get("city") or "",
        "state": h.get("state") or "",
        "zip": h.get("zip") or "",
        "loc": {"type": "Point", "coordinates": [lon, lat]},
        "source": "osm",
        "response": "awaiting response",
        "created_at": datetime.utcnow(),
    }



def _persist_houses_to_territory(db, user_id, territory_id, items):
    """
    Upsert houses under `houses` collection and update a summary onto the territory.
    Also:
      - attaches house_id (string) to each item in `items`
      - stores house_id in territories.houses_sample
    """
    _ensure_houses_indexes(db)

    terr_oid = ObjectId(territory_id)

    # Verify the territory belongs to the user
    terr = db.territories.find_one({"_id": terr_oid, "user_id": user_id})
    if not terr:
        raise ValueError("territory_not_found_or_forbidden")

    # -------------------- bulk upserts --------------------
    ops = []
    for h in items:
        doc = _normalize_house_for_db(h, user_id, territory_id)
        filt = {
            "territory_id": doc["territory_id"],
            "address": doc["address"],
            "zip": doc["zip"],
        }
        ops.append(UpdateOne(filt, {"$setOnInsert": doc}, upsert=True))

    result_summary = {"upserted": 0, "total_for_territory": 0, "sample": []}
    if ops:
        try:
            result = db.houses.bulk_write(ops, ordered=False)
            result_summary["upserted"] = int(getattr(result, "upserted_count", 0) or 0)
            print(f"[HOUSES] bulk upsert complete. upserted={result_summary['upserted']}")
        except Exception as e:
            # DuplicateKeyError is fine due to unique index; bulk_write may raise only if fatal
            print(f"[HOUSES] bulk upsert encountered error: {e}")

    # -------------------- attach house_id to items --------------------
    # Build a lookup from (lat,lon) -> house_id for all houses in this territory
    id_lookup = {}
    all_cursor = db.houses.find(
        {"territory_id": terr_oid},
        {"_id": 1, "loc.coordinates": 1}
    )

    for d in all_cursor:
        coords = d.get("loc", {}).get("coordinates", [None, None])
        if coords and coords[0] is not None and coords[1] is not None:
            lon, lat = coords
            key = (round(float(lat), 6), round(float(lon), 6))
            id_lookup[key] = str(d["_id"])

    # Mutate `items` in-place to include house_id
    for h in items:
        try:
            lat = float(h.get("lat"))
            lon = float(h.get("lon"))
        except (TypeError, ValueError):
            continue
        key = (round(lat, 6), round(lon, 6))
        house_id = id_lookup.get(key)
        if house_id:
            h["house_id"] = house_id

    # -------------------- recompute summary for this territory --------------------
    total = db.houses.count_documents({"territory_id": terr_oid})

    sample_cursor = db.houses.find(
        {"territory_id": terr_oid},
        {"_id": 1, "address": 1, "city": 1, "state": 1, "zip": 1, "loc.coordinates": 1}
    ).limit(20)

    sample = []
    for d in sample_cursor:
        coords = d.get("loc", {}).get("coordinates", [None, None])
        lon = coords[0] if len(coords) > 0 else None
        lat = coords[1] if len(coords) > 1 else None

        sample.append({
            "house_id": str(d["_id"]),          # 🔹 add house_id here
            "address": d.get("address", ""),
            "city": d.get("city", ""),
            "state": d.get("state", ""),
            "zip": d.get("zip", ""),
            "lon": lon,
            "lat": lat,
            "response": d.get("response", "awaiting response"), 
        })

    db.territories.update_one(
        {"_id": terr_oid},
        {
            "$set": {
                "houses_count": total,
                "houses_sample": sample,           # lightweight preview for UI, now with house_id
                "houses_last_refreshed_at": datetime.utcnow()
            }
        }
    )

    result_summary["total_for_territory"] = total
    result_summary["sample"] = sample
    return result_summary




# -------------------------------
# OSM / Overpass helper
# -------------------------------
import requests
from time import sleep

OVERPASS_URL = "https://overpass-api.de/api/interpreter"  # public endpoint; consider hosting your own later

def _ring_lonlat_to_overpass_poly(ring_lonlat):
    """
    Overpass 'poly' expects: 'lat lon lat lon ...' (note: LAT first).
    We accept [[lon,lat], ...] (your client format), ensure closed ring,
    then return the single string.
    """
    if not ring_lonlat or len(ring_lonlat) < 3:
        return None
    if ring_lonlat[0] != ring_lonlat[-1]:
        ring_lonlat = ring_lonlat + [ring_lonlat[0]]
    parts = []
    for lon, lat in ring_lonlat:
        parts.append(f"{float(lat):.7f} {float(lon):.7f}")
    return " ".join(parts)

def _fetch_osm_addresses_in_polygon(ring_lonlat, timeout_s=25):
    """
    Query Overpass for any node/way/relation that has address tags within the polygon.
    We return a list of dicts: { address, city, state, zip, lat, lon } best-effort.
    """
    poly = _ring_lonlat_to_overpass_poly(ring_lonlat)
    if not poly:
        raise ValueError("Invalid ring_lonlat for Overpass")

    # Overpass QL: select anything with addr:* tags inside the polygon
    # 'out center' gives us coordinates for ways/relations (nodes already have lat/lon)
    ql = f"""
    [out:json][timeout:{timeout_s}];
    (
      node["addr:housenumber"](poly:"{poly}");
      way["addr:housenumber"](poly:"{poly}");
      relation["addr:housenumber"](poly:"{poly}");
    );
    out center tags;
    """
    headers = {
        # Be polite (Overpass requires a descriptive UA). You can add your email.
        "User-Agent": "CFAC/1.0 (houses-in-area) contact: support@cfautocare.biz"
    }

    # Simple retry for 429/5xx
    for attempt in range(3):
        r = requests.post(OVERPASS_URL, data={"data": ql}, headers=headers, timeout=timeout_s + 5)
        if r.status_code == 429 or r.status_code >= 500:
            sleep(1 + attempt * 2)
            continue
        r.raise_for_status()
        break

    data = r.json()
    elements = data.get("elements", [])

    out = []
    for el in elements:
        tags = el.get("tags", {})
        # Coordinates
        if el.get("type") == "node":
            lat = el.get("lat")
            lon = el.get("lon")
        else:
            # way/relation: prefer 'center' (provided by 'out center')
            c = el.get("center") or {}
            lat = c.get("lat")
            lon = c.get("lon")

        if lat is None or lon is None:
            continue

        # Build a nice address line (best-effort from common OSM tags)
        number = tags.get("addr:housenumber")
        street = tags.get("addr:street") or tags.get("addr:road")
        unit   = tags.get("addr:unit")
        city   = tags.get("addr:city") or tags.get("addr:town") or tags.get("addr:village") or ""
        state  = tags.get("addr:state") or ""
        zipc   = tags.get("addr:postcode") or ""

        line = " ".join(filter(None, [number, street]))
        if unit:
            line += f", Unit {unit}"

        out.append({
            "address": line,
            "city": city,
            "state": state,
            "zip": zipc,
            "lat": float(lat),
            "lon": float(lon),
        })

    return out

# -------------------------------
# Route: Fetch houses in area (with optional persistence)
# -------------------------------
@api_territories_bp.route("/api/houses-in-area", methods=["POST"])
@require_auth
@csrf.exempt
def houses_in_area():
    print("\n=== [POST] /api/houses-in-area called ===")
    body = request.get_json(silent=True) or {}
    print(f"[HOUSES] Input: {body}")

    polygon = body.get("polygon")  # preferred: [[lon,lat], ...]
    circle  = body.get("circle")   # optional: {"center":[lon,lat], "radius": miles}
    limit   = min(int(body.get("limit", 800)), 2000)

    if polygon and circle:
        return jsonify({"error": "Provide either 'polygon' or 'circle', not both"}), 400
    if not polygon and not circle:
        return jsonify({"error": "Provide 'polygon' (preferred) or 'circle'"}), 400

    try:
        if polygon:
            ring = [list(map(float, pt)) for pt in polygon]
            items = _fetch_osm_addresses_in_polygon(ring)
        else:
            # Optional: circle path via Overpass by approximating a polygon
            center = circle["center"]  # [lon,lat]
            radius_mi = float(circle["radius"])

            import math
            def circle_to_ring(lon, lat, radius_miles, steps=36):
                R = 3959.0  # miles
                ang = radius_miles / R
                ring = []
                lat0 = math.radians(lat)
                lon0 = math.radians(lon)
                for k in range(steps):
                    bearing = 2*math.pi*k/steps
                    lat1 = math.asin(math.sin(lat0)*math.cos(ang) +
                                     math.cos(lat0)*math.sin(ang)*math.cos(bearing))
                    lon1 = lon0 + math.atan2(math.sin(bearing)*math.sin(ang)*math.cos(lat0),
                                             math.cos(ang)-math.sin(lat0)*math.sin(lat1))
                    ring.append([math.degrees(lon1), math.degrees(lat1)])
                return ring

            ring = circle_to_ring(center[0], center[1], radius_mi, steps=36)
            items = _fetch_osm_addresses_in_polygon(ring)

        # Trim if needed
        if len(items) > limit:
            items = items[:limit]

        print(f"[HOUSES] Returning {len(items)} item(s) from OSM")
        for i, h in enumerate(items[:5], 1):
            print(f"[HOUSES] #{i}: {h.get('address','')} {h.get('city','')} {h.get('state','')} {h.get('zip','')} @ ({h.get('lat'):.5f}, {h.get('lon'):.5f})")

        # ------------------ optional persistence ------------------
        persist = bool(body.get("persist", False))
        territory_id = body.get("territory_id")

        result_summary = None
        if persist:
            if not territory_id:
                return jsonify({"error": "territory_id_required_when_persisting"}), 400

            try:
                db = get_db()
            except Exception as e:
                print(f"[HOUSES ERROR] DB handle unavailable: {e}")
                return jsonify({"error": "Server DB misconfigured"}), 500

            try:
                result_summary = _persist_houses_to_territory(
                    db=db,
                    user_id=request.user.get("sub"),
                    territory_id=territory_id,
                    items=items
                )
            except ValueError as ve:
                if str(ve) == "territory_not_found_or_forbidden":
                    return jsonify({"error": "territory_not_found_or_forbidden"}), 403
                print(f"[HOUSES ERROR] persist value error: {ve}")
                result_summary = {"error": "persist_failed"}
            except Exception as e:
                print(f"[HOUSES ERROR] persist failed: {e}")
                result_summary = {"error": "persist_failed"}

        payload = {"items": items}
        if result_summary is not None:
            payload["persist_result"] = result_summary

        return jsonify(payload), 200

    except requests.HTTPError as e:
        print(f"[HOUSES ERROR] Overpass HTTP error: {e}")
        return jsonify({"error": "Overpass unavailable"}), 502
    except Exception as e:
        print(f"[HOUSES ERROR] {e}")
        return jsonify({"error": str(e)}), 400

@api_territories_bp.route("/api/track-responses", methods=["POST"])
@require_auth
@csrf.exempt
def track_responses():
    """
    Stub endpoint for tracking responses on houses/territories.
    No features implemented yet.
    """
    print("\n=== [POST] /api/track-responses called ===")
    body = request.get_json(silent=True) or {}
    print(f"[TRACK RESPONSES] Input (stub only): {body}")

    return jsonify({
        "ok": True,
        "message": "track_responses stub endpoint – no features implemented yet"
    }), 200
