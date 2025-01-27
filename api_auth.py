from flask import Blueprint, request, jsonify, current_app
from flask_bcrypt import check_password_hash
from bson.objectid import ObjectId
from extensions import csrf  # Import your CSRF instance if needed

api_bp = Blueprint('api', __name__, url_prefix='/api')

@api_bp.route('/login', methods=['POST'])
@csrf.exempt   # This disables CSRF protection for this route
def api_login():
    """
    API endpoint for employee/salesman login.
    Expects JSON { "username": "...", "password": "..." }.
    Returns JSON with a token or error information.
    """
    data = request.get_json()
    if not data or 'username' not in data or 'password' not in data:
        return jsonify({"error": "Username and password required."}), 400

    username = data['username'].strip().lower()
    password = data['password']

    # Access the USERS_COLLECTION from app config (set by your db.py / init_db)
    users_collection = current_app.config.get('USERS_COLLECTION')
    user = users_collection.find_one({
        'username': username,
        'user_type': {'$in': ['admin', 'tech', 'sales']}
    })
    if not user:
        return jsonify({"error": "Invalid username or user type."}), 401

    # For password checking, use flask_bcrypt's check_password_hash
    from flask_bcrypt import check_password_hash
    if not check_password_hash(user['password'], password):
        return jsonify({"error": "Invalid password."}), 401

    # For demonstration, return the user's ID as a token.
    # In production, you should generate a JWT or another secure token.
    token = str(user['_id'])
    return jsonify({"message": "Login successful", "token": token}), 200
