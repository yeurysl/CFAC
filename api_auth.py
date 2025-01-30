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
    # In PyJWT 2.x, jwt.encode() returns a str in Python 3, which is what we want.
    return token

@api_bp.route('/login', methods=['POST'])
@csrf.exempt
def api_login():
    data = request.get_json()
    if not data or 'username' not in data or 'password' not in data:
        return jsonify({"error": "Username and password required."}), 400

    username = data['username'].strip().lower()
    password = data['password']

    users_collection = current_app.config.get('USERS_COLLECTION')
    user = users_collection.find_one({
        'username': username,
        'user_type': {'$in': ['admin', 'tech', 'sales']}
    })
    if not user:
        return jsonify({"error": "Invalid username or user type."}), 401

    if not check_password_hash(user['password'], password):
        return jsonify({"error": "Invalid password."}), 401

    # Replace the old "token = str(user['_id'])" with a JWT
    secret_key = current_app.config['JWT_SECRET']
    jwt_token = generate_jwt(user['_id'], secret_key)

    return jsonify({
        "message": "Login successful",
        "token": jwt_token
    }), 200
