#api_account.py
from flask import Blueprint, request, jsonify, current_app
from bson.objectid import ObjectId, InvalidId

# Create a new blueprint for account settings API endpoints
api_account_bp = Blueprint('api_account', __name__, url_prefix='/api/account')

def get_user_from_token(token):
    """
    For demonstration purposes, we assume that the token is simply the user's _id.
    In a production system, you would decode a JWT or perform other secure token validation.
    """
    users_collection = current_app.config.get('USERS_COLLECTION')
    try:
        user = users_collection.find_one({"_id": ObjectId(token)})
        return user
    except (InvalidId, TypeError):
        return None

@api_account_bp.route('/', methods=['GET'])
def fetch_account_settings():
    """
    GET /api/account
    Expects a query parameter, e.g., ?token=<user_token>.
    Returns the account settings for the authenticated user.
    """
    token = request.args.get('token')
    if not token:
        return jsonify({"error": "Missing token parameter."}), 400

    user = get_user_from_token(token)
    if not user:
        return jsonify({"error": "Invalid token or user not found."}), 404

    # Prepare account settings data
    account_settings = {
        "name": user.get("name", ""),
        "email": user.get("email", ""),
        "phone_number": user.get("phone_number", ""),
        "address": user.get("address", {})  # Assuming address is stored as a subdocument
    }
    return jsonify(account_settings), 200

@api_account_bp.route('/', methods=['PUT'])
def update_account_settings():
    """
    PUT /api/account
    Expects a JSON body with the fields to update.
    Also expects a 'token' field in the JSON (or in a header) that identifies the user.
    """
    data = request.get_json()
    if not data or 'token' not in data:
        return jsonify({"error": "Token is required in the request body."}), 400
    
    token = data.pop('token')
    user = get_user_from_token(token)
    if not user:
        return jsonify({"error": "Invalid token or user not found."}), 404

    # Prepare the update document. We assume that the incoming JSON contains the fields:
    # name, email, phone_number, address (which itself is a dict with street_address, city, country, zip_code).
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

    users_collection = current_app.config.get('USERS_COLLECTION')
    try:
        result = users_collection.update_one({"_id": ObjectId(token)}, {"$set": update_fields})
        if result.modified_count >= 1:
            return jsonify({"message": "Account settings updated successfully."}), 200
        else:
            return jsonify({"message": "No changes were made."}), 200
    except Exception as e:
        current_app.logger.error(f"Error updating account settings: {e}")
        return jsonify({"error": "Failed to update settings."}), 500
