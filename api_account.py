# api_account.py
from flask import Blueprint, request, jsonify, current_app
from bson.objectid import ObjectId, InvalidId
import jwt
from extensions import csrf  

# Create a new blueprint for account settings API endpoints
api_account_bp = Blueprint('api_account', __name__, url_prefix='/api/account')


def get_user_from_token(token):
    users_collection = current_app.config.get('USERS_COLLECTION')
    try:
        secret_key = current_app.config.get('JWT_SECRET', 'JWT_SECRET')
        current_app.logger.info(f"[Account] Decoding token: {token}")
        payload = jwt.decode(token, secret_key, algorithms=['HS256'])
        print("Decoded payload:", payload)
        current_app.logger.debug(f"[Account] Decoded payload: {payload}")

        user_id = payload.get('sub')
        if not user_id:
            print("No 'sub' in token payload.")
            current_app.logger.warning("[Account] Token missing 'sub'")
            return None

        user = users_collection.find_one({"_id": ObjectId(user_id)})
        print("User found in DB:", user)
        current_app.logger.info(f"[Account] User lookup result: {user}")
        return user
    except (jwt.DecodeError, jwt.ExpiredSignatureError, InvalidId, TypeError) as e:
        print("Token decoding error:", e)
        current_app.logger.error(f"[Account] Token decoding error: {e}")
        return None


@api_account_bp.route('/', methods=['GET'])
def fetch_account_settings():
    current_app.logger.info("[Account][GET] /api/account endpoint hit")

    # Get the Authorization header
    auth_header = request.headers.get('Authorization', '')
    current_app.logger.debug(f"[Account][GET] Raw Authorization header: {auth_header}")
    if not auth_header.startswith('Bearer '):
        current_app.logger.error("[Account][GET] Missing or invalid Authorization header")
        return jsonify({"error": "Missing or invalid Authorization header"}), 401
    
    # Extract token
    token = auth_header.replace("Bearer ", "").strip()
    current_app.logger.debug(f"[Account][GET] Extracted token: {token}")

    user = get_user_from_token(token)
    if not user:
        current_app.logger.error("[Account][GET] Invalid token or user not found")
        return jsonify({"error": "Invalid token or user not found."}), 404

    # Prepare account settings data
    account_settings = {
        "name": user.get("name", ""),
        "email": user.get("email", ""),
        "phone_number": user.get("phone_number", ""),
        "address": user.get("address", {})
    }
    current_app.logger.info(f"[Account][GET] Returning account settings for user: {user.get('_id')}")
    print("Account settings response:", account_settings)

    return jsonify(account_settings), 200


@csrf.exempt
@api_account_bp.route('/', methods=['PUT'])
def update_account_settings():
    current_app.logger.info("[Account][PUT] /api/account endpoint hit")

    auth_header = request.headers.get('Authorization', '')
    current_app.logger.debug(f"[Account][PUT] Raw Authorization header: {auth_header}")
    if not auth_header.startswith('Bearer '):
        current_app.logger.error("[Account][PUT] Missing or invalid Authorization header")
        return jsonify({"error": "Missing or invalid Authorization header"}), 401

    token = auth_header.replace("Bearer ", "").strip()
    current_app.logger.debug(f"[Account][PUT] Extracted token: {token}")

    user = get_user_from_token(token)
    if not user:
        current_app.logger.error("[Account][PUT] Invalid token or user not found")
        return jsonify({"error": "Invalid token or user not found."}), 404

    data = request.get_json() or {}
    print("Incoming update data:", data)
    current_app.logger.debug(f"[Account][PUT] Incoming JSON data: {data}")

    update_fields = {}

    if 'name' in data:
        update_fields['name'] = data['name'].strip()
    if 'email' in data:
        update_fields['email'] = data['email'].strip().lower()
    if 'phone_number' in data:
        update_fields['phone_number'] = data['phone_number'].strip()
    if 'address' in data and isinstance(data['address'], dict):
        address = data['address']
        update_fields['address'] = {
            'street_address': address.get('street_address', "").strip(),
            'city': address.get('city', "").strip(),
            'country': address.get('country', "").strip(),
            'zip_code': address.get('zip_code', "").strip()
        }

    current_app.logger.debug(f"[Account][PUT] Update fields: {update_fields}")

    users_collection = current_app.config.get('USERS_COLLECTION')
    try:
        result = users_collection.update_one({"_id": user['_id']}, {"$set": update_fields})
        current_app.logger.info(f"[Account][PUT] Update result: matched={result.matched_count}, modified={result.modified_count}")
        if result.modified_count >= 1:
            return jsonify({"message": "Account settings updated successfully."}), 200
        else:
            return jsonify({"message": "No changes were made."}), 200
    except Exception as e:
        print("Error updating account:", e)
        current_app.logger.error(f"[Account][PUT] Error updating account settings: {e}")
        return jsonify({"error": "Failed to update settings."}), 500





# app.py or blueprints/admin.py (where you handle account routes)
from flask import Blueprint, request, jsonify
from notis import send_reset_email  # Function to email reset link
import secrets
from datetime import datetime, timedelta

account_bp = Blueprint("account", __name__, url_prefix="/api/account")

@account_bp.route("/reset-password", methods=["POST"])
def reset_password_request():
    """
    Request a password reset link to be sent to the user's email.
    """
    data = request.get_json()
    if not data or "email" not in data:
        return jsonify({"error": "Email is required"}), 400

    email = data["email"].strip().lower()
    user = User.get_by_email(email)  # Your method to get a user

    if not user:
        # Avoid leaking which emails exist
        return jsonify({"message": "If an account exists for this email, a reset link has been sent."}), 200

    # Generate a secure random token
    reset_token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(hours=1)  # valid for 1 hour

    # Save the token and expiry to the user (adjust based on your DB)
    user.reset_token = reset_token
    user.reset_token_expiry = expires_at
    user.save()

    # Send reset email
    reset_link = f"https://www.cfautocare.biz/reset-password?token={reset_token}"
    send_reset_email(user.email, reset_link)

    return jsonify({"message": "If an account exists for this email, a reset link has been sent."}), 200
