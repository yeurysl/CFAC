from flask import Blueprint, request, jsonify, current_app
from datetime import datetime
from flask_login import current_user  


api_sales_bp = Blueprint('api_sales', __name__, url_prefix='/api')


@api_sales_bp.route('/orders', methods=['GET'])
def fetch_orders():
    try:
        orders_collection = current_app.config.get('ORDERS_COLLECTION')
        if orders_collection is None:
            return jsonify({"error": "Orders collection not configured."}), 500

        # Ensure the user is authenticated.
        if not current_user.is_authenticated:
            return jsonify({"error": "User not authenticated."}), 401

        # Only fetch orders that belong to the current user.
        # Assuming that when an order is created, it stores the user ID in the "user" field.
        query = {"user": current_user.get_id()}  # or current_user.id

        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        skip = (page - 1) * per_page

        total_orders = orders_collection.count_documents(query)
        orders_cursor = orders_collection.find(query).skip(skip).limit(per_page)

        orders = []
        for order in orders_cursor:
            order['_id'] = str(order['_id'])
            # Convert date fields to ISO strings if they exist
            if isinstance(order.get('order_date'), datetime):
                order['order_date'] = order['order_date'].isoformat()
            if isinstance(order.get('service_date'), datetime):
                order['service_date'] = order['service_date'].isoformat()
            orders.append(order)

        return jsonify({
            "orders": orders,
            "page": page,
            "per_page": per_page,
            "total_orders": total_orders
        }), 200
    except Exception as e:
        current_app.logger.error(f"Error fetching orders: {e}")
        return jsonify({"error": str(e)}), 500



@api_sales_bp.route('/services', methods=['GET'])
def get_services():
    try:
        # Access the database object from app.config
        db = current_app.config["MONGO_CLIENT"]
        services_collection = db.services  # Access the 'services' collection
        services = services_collection.find({"active": True})

        # Prepare the response
        service_list = []
        for service in services:
            service_list.append({
                "key": service["key"],
                "label": service["label"],
                "category": service["category"],
                "price_by_vehicle_size": service["price_by_vehicle_size"]
            })

        return jsonify({"services": service_list}), 200
    except Exception as e:
        current_app.logger.error(f"Error fetching services: {e}")
        return jsonify({"error": str(e)}), 500
    

@api_sales_bp.route('/guest_order', methods=['POST'])
def create_order():
    try:
        current_app.logger.info("Received a new order POST request.")
        orders_collection = current_app.config.get('ORDERS_COLLECTION')
        if orders_collection is None:
            current_app.logger.error("Orders collection not configured.")
            return jsonify({"error": "Orders collection not configured."}), 500

        order_data = request.get_json()
        if order_data is None:
            current_app.logger.error("No JSON data found.")
            return jsonify({"error": "Invalid or missing JSON data."}), 400

        # Log the received order data
        current_app.logger.info(f"Order data received: {order_data}")

        # Validate required fields according to the website order structure.
        # For example, your website order has keys:
        #   guest_name, guest_email, vehicle_size, guest_address, selectedServices
        required_fields = ["guest_name", "guest_email", "vehicle_size", "guest_address", "selectedServices"]
        missing = [field for field in required_fields if field not in order_data]
        if missing:
            current_app.logger.error(f"Missing required fields: {missing}")
            return jsonify({"error": f"Missing required fields: {missing}"}), 400

        # Ensure guest_address is a dictionary containing required sub-fields
        if not isinstance(order_data.get("guest_address"), dict):
            current_app.logger.error("guest_address must be provided as an object.")
            return jsonify({"error": "guest_address must be provided as an object."}), 400

        address_required = ["street_address", "unit_apt", "city", "country", "zip_code"]
        missing_address = [field for field in address_required if field not in order_data["guest_address"]]
        if missing_address:
            current_app.logger.error(f"Missing required address fields: {missing_address}")
            return jsonify({"error": f"Missing required address fields: {missing_address}"}), 400

        # Set default values if needed
        if "creation_date" not in order_data:
            order_data["creation_date"] = datetime.utcnow()
        # If you want to force guest orders, you might set:
        order_data["is_guest"] = True
        order_data["user"] = None  # if applicable

        # You may also set defaults for payment_time and payment_status, if not provided:
        if "payment_time" not in order_data:
            order_data["payment_time"] = "pay_now"
        if "payment_status" not in order_data:
            order_data["payment_status"] = "Unpaid"
        if "service_package" not in order_data:
            order_data["service_package"] = ""
        if "senior_rv_discount" not in order_data:
            order_data["senior_rv_discount"] = False
        if "status" not in order_data:
            order_data["status"] = "ordered"
        # scheduled_by and salesperson can be set if necessary.
        
        result = orders_collection.insert_one(order_data)
        current_app.logger.info(f"Order inserted with id: {result.inserted_id}")

        return jsonify({
            "message": "Order created successfully!",
            "order_id": str(result.inserted_id)
        }), 201

    except Exception as e:
        current_app.logger.error(f"Error creating order: {e}")
        return jsonify({"error": str(e)}), 500
