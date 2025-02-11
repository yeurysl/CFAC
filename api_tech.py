from flask import Blueprint, request, jsonify, current_app
from bson import ObjectId
from datetime import datetime
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
import jwt




api_tech_bp = Blueprint('api_tech', __name__, url_prefix='/api/tech')

@api_tech_bp.route('/orders_with_downpayment', methods=['GET'])
def fetch_orders_with_downpayment():
    try:
        # Get the orders collection
        orders_collection = current_app.config.get('MONGO_CLIENT').orders

        # Query orders with downpayment
        orders_cursor = orders_collection.find({"has_downpayment_collected": "yes"})
        orders = []

        # Iterate through the orders and collect them
        for order in orders_cursor:
            order['_id'] = str(order['_id'])  # Convert ObjectId to string

            # Check if 'service_date' is a string, and if so, convert it to a datetime object
            if isinstance(order['service_date'], str):
                try:
                    # Try parsing the string to datetime
                    order['service_date'] = datetime.fromisoformat(order['service_date'])
                except ValueError:
                    # If the string format is invalid, leave it as is (or handle as needed)
                    current_app.logger.error(f"Invalid date format for order ID {order['_id']}")

            # Convert datetime to ISO format if it's a datetime object
            if isinstance(order['service_date'], datetime):
                order['service_date'] = order['service_date'].isoformat()

            orders.append(order)

        if not orders:
            # No orders with downpayment found, return a message
            return jsonify({"message": "No orders available to be scheduled"}), 404

        # Return the fetched orders
        return jsonify({"orders": orders}), 200

    except Exception as e:
        # Log the error with more detailed information
        current_app.logger.error(f"Error fetching orders with downpayment: {str(e)}")
        return jsonify({"error": f"Error fetching orders: {str(e)}"}), 500



@api_tech_bp.route('/orders/<order_id>', methods=['PATCH'])
def update_order(order_id):
    # Check authentication
    token = request.headers.get('Authorization').replace('Bearer ', '')
    user_id = decode_jwt(token, current_app.config['JWT_SECRET'])
    if not user_id:
        return jsonify({"error": "Invalid token"}), 401

    # Fetch the order from the database
    orders_collection = current_app.config.get('ORDERS_COLLECTION')
    order = orders_collection.find_one({"_id": ObjectId(order_id)})

    if not order:
        return jsonify({"error": "Order not found"}), 404

    # Update technician field if provided
    update_data = request.get_json()
    if "technician" in update_data:
        orders_collection.update_one(
            {"_id": ObjectId(order_id)},
            {"$set": {"technician": update_data["technician"]}}
        )
        return jsonify({"message": "Order updated successfully."}), 200
    else:
        return jsonify({"error": "Technician not provided"}), 400
def decode_jwt(token, secret_key):
    try:
        # Decode the JWT token
        payload = jwt.decode(token, secret_key, algorithms=["HS256"])
        # Return the user ID (or whatever you want from the payload)
        return payload.get("sub")
    except ExpiredSignatureError:
        return None  # Token has expired
    except InvalidTokenError:
        return None  # Invalid token