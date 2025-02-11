from flask import Blueprint, request, jsonify, current_app
from bson import ObjectId
from datetime import datetime

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
            return jsonify({"error": "No orders with downpayment found."}), 404

        # Return the fetched orders
        return jsonify({"orders": orders}), 200

    except Exception as e:
        # Log the error with more detailed information
        current_app.logger.error(f"Error fetching orders with downpayment: {str(e)}")
        return jsonify({"error": f"Error fetching orders: {str(e)}"}), 500
