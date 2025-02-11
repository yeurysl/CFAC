from flask import Blueprint, request, jsonify, current_app
from bson import ObjectId

api_tech_bp = Blueprint('api_tech', __name__, url_prefix='/api/tech')

@api_tech_bp.route('/orders_with_downpayment', methods=['GET'])
def fetch_orders_with_downpayment():
    try:
        # Access the database client
        orders_collection = current_app.config.get('MONGO_CLIENT').orders  # Assuming 'orders' collection

        # Query for orders where `has_downpayment_collected` is 'yes'
        orders_cursor = orders_collection.find({"has_downpayment_collected": "yes"})

        orders = []
        for order in orders_cursor:
            # Convert _id to string
            order['_id'] = str(order['_id'])
            # Convert datetime fields if needed
            if 'service_date' in order:
                order['service_date'] = order['service_date'].isoformat()  # Convert to ISO string format
            if 'creation_date' in order:
                order['creation_date'] = order['creation_date'].isoformat()
            orders.append(order)

        return jsonify({"orders": orders}), 200
    except Exception as e:
        current_app.logger.error(f"Error fetching orders with downpayment: {e}", exc_info=True)
        return jsonify({"error": "Error fetching orders."}), 500
