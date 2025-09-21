#api_account.py
from flask import Blueprint, request, jsonify, current_app
from bson.objectid import ObjectId, InvalidId
import jwt
from extensions import csrf  

# Create a new blueprint for account settings API endpoints
api_account_bp = Blueprint('api_account', __name__, url_prefix='/api/account')



def get_user_from_token(token):
    users_collection = current_app.config.get('USERS_COLLECTION')
    try:
        # Use the secret from configuration rather than a hardcoded string.
        secret_key = current_app.config.get('JWT_SECRET', 'JWT_SECRET')
        payload = jwt.decode(token, secret_key, algorithms=['HS256'])
        print("Decoded payload:", payload)  # Debug print

        user_id = payload.get('sub')  # Assuming the user id is in the "sub" field
        if not user_id:
            print("No 'sub' in token payload.")
            return None

        # Look up the user by the decoded user_id
        user = users_collection.find_one({"_id": ObjectId(user_id)})
        print("User found in DB:", user)  # Debug print
        return user
    except (jwt.DecodeError, jwt.ExpiredSignatureError, InvalidId, TypeError) as e:
        print("Token decoding error:", e)  # Debug print
        return None


    

@api_account_bp.route('/', methods=['GET'])
def fetch_account_settings():
    # Get the Authorization header
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return jsonify({"error": "Missing or invalid Authorization header"}), 401
    
    # Extract token
    token = auth_header.replace("Bearer ", "").strip()
    user = get_user_from_token(token)
    if not user:
        return jsonify({"error": "Invalid token or user not found."}), 404

    # Prepare account settings data
    account_settings = {
        "name": user.get("name", ""),
        "email": user.get("email", ""),
        "phone_number": user.get("phone_number", ""),
        "address": user.get("address", {})
    }
    return jsonify(account_settings), 200

@csrf.exempt
@api_account_bp.route('/', methods=['PUT'])
def update_account_settings():
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return jsonify({"error": "Missing or invalid Authorization header"}), 401

    token = auth_header.replace("Bearer ", "").strip()
    user = get_user_from_token(token)
    if not user:
        return jsonify({"error": "Invalid token or user not found."}), 404

    data = request.get_json() or {}
    update_fields = {}

    if 'name' in data:
        update_fields['name'] = data['name'].strip()
    if 'email' in data:
        update_fields['email'] = data['email'].strip().lower()
    if 'phone_number' in data:
        update_fields['phone_number'] = data['phone_number'].strip()
    if 'address' in data and isinstance(data['address'], dict):
        update_fields['address'] = {
            'street_address': data['address'].get('street_address', "").strip(),
            'city': data['address'].get('city', "").strip(),
            'country': data['address'].get('country', "").strip(),
            'zip_code': data['address'].get('zip_code', "").strip()
        }

    users_collection = current_app.config.get('USERS_COLLECTION')
    result = users_collection.update_one({"_id": user['_id']}, {"$set": update_fields})

    if result.modified_count >= 1:
        return jsonify({"message": "Account settings updated successfully."}), 200
    else:
        return jsonify({"message": "No changes were made."}), 200
