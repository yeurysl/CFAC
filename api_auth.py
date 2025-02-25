#api_auth.py

from flask import Blueprint, request, jsonify, current_app
from flask_bcrypt import check_password_hash
from bson.objectid import ObjectId
from extensions import csrf  
from datetime import datetime, timedelta
import jwt


api_bp = Blueprint('api', __name__, url_prefix='/api')


def generate_jwt(user_id, secret_key, expires_in=4):
    """
    Generate a JWT containing the user_id in the 'sub' field.
    expires_in is in hours by default.
    """
    now = datetime.utcnow()
    payload = {
        "sub": str(user_id),      # The subject of the token
        "iat": now,               # Issued at
        "exp": now + timedelta(hours=expires_in)  # Expiration time
    }
    token = jwt.encode(payload, secret_key, algorithm="HS256")
    # If token is bytes, decode it to a string.
    if isinstance(token, bytes):
        token = token.decode('utf-8')
    return token









@api_bp.route('/login', methods=['POST'])
@csrf.exempt
def api_login():
    data = request.get_json()
    if not data or 'username' not in data or 'password' not in data:
        current_app.logger.error("Login failed: Missing username or password in payload.")
        return jsonify({"error": "Username and password required."}), 400

    username = data['username'].strip().lower()
    password = data['password']
    current_app.logger.info(f"Login attempt for username: {username}")

    users_collection = current_app.config.get('USERS_COLLECTION')
    user = users_collection.find_one({"username": username})
    
    if not user:
        current_app.logger.error(f"Login failed: No user found with username {username}.")
        return jsonify({"error": "Invalid username."}), 401

    # Ensure that the user document has both '_id' and 'username'
    if '_id' not in user or 'username' not in user:
        current_app.logger.error(f"Login failed: Incomplete user record for username {username}.")
        return jsonify({"error": "User record is incomplete."}), 500

    # Verify the password
    if not check_password_hash(user.get('password', ''), password):
        current_app.logger.error(f"Login failed: Invalid password for username {username}.")
        return jsonify({"error": "Invalid password."}), 401

    # Optional: Check that the user type is either 'tech' or 'sales'
    if user.get('user_type') not in ['tech', 'sales']:
        current_app.logger.error(f"Login failed: Unsupported user type {user.get('user_type')} for username {username}.")
        return jsonify({"error": "User type not supported."}), 401

    secret_key = current_app.config.get('JWT_SECRET')
    jwt_token = generate_jwt(user['_id'], secret_key)
    current_app.logger.info(f"Login successful for username {username}, user ID: {user['_id']}")

    return jsonify({
        "message": "Login successful",
        "token": jwt_token,
        "user_type": user.get('user_type')
    }), 200
