#api_sales.py
from flask import Blueprint, request, jsonify, current_app
from datetime import datetime
from flask_login import current_user  
import jwt
from bson import ObjectId
import stripe
from jwt import ExpiredSignatureError, InvalidTokenError


api_sales_bp = Blueprint('api_sales', __name__, url_prefix='/api')
stripe.api_key = current_app.config['STRIPE_SECRET_KEY']



def decode_jwt(token, secret_key):
    """
    Decode a JWT using the secret key.
    Returns the user_id if valid, or None if invalid/expired.
    """
    try:
        payload = jwt.decode(token, secret_key, algorithms=["HS256"])
        # 'sub' is the user ID
        return payload.get("sub")
    except (ExpiredSignatureError, InvalidTokenError, KeyError):
        return None






@api_sales_bp.route('/orders', methods=['GET'])
def fetch_orders():
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Missing or invalid Authorization header."}), 401

    token = auth_header.replace("Bearer ", "").strip()
    secret_key = current_app.config['JWT_SECRET']
    user_id = decode_jwt(token, secret_key)
    if not user_id:
        return jsonify({"error": "Invalid or expired token"}), 401

    # Optionally, you can verify the user exists:
    users_collection = current_app.config['USERS_COLLECTION']
    user = users_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        return jsonify({"error": "User not found"}), 404

    orders_collection = current_app.config.get('ORDERS_COLLECTION')
    if orders_collection is None:
        return jsonify({"error": "Orders collection not configured."}), 500

    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))
    skip = (page - 1) * per_page

    # Update the query to filter orders by the salesperson field.
    query = {"salesperson": user_id}
    total_orders = orders_collection.count_documents(query)
    orders_cursor = orders_collection.find(query).skip(skip).limit(per_page)

    orders = []
    for order in orders_cursor:
        order['_id'] = str(order['_id'])
        # Convert datetime fields to ISO strings if needed.
        if 'order_date' in order and isinstance(order['order_date'], datetime):
            order['order_date'] = order['order_date'].isoformat()
        if 'service_date' in order and isinstance(order['service_date'], datetime):
            order['service_date'] = order['service_date'].isoformat()
        orders.append(order)

    return jsonify({
        "orders": orders,
        "page": page,
        "per_page": per_page,
        "total_orders": total_orders
    }), 200


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
        required_fields = [
            "guest_name", "guest_email", "vehicle_size",
            "guest_address", "selectedServices", "services_total", "fee", "final_price"
        ]
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

@api_sales_bp.route('/orders/<order_id>', methods=['PUT', 'PATCH'])
def update_order(order_id):
    # Authenticate the user
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Missing or invalid Authorization header."}), 401

    token = auth_header.replace("Bearer ", "").strip()
    secret_key = current_app.config['JWT_SECRET']
    user_id = decode_jwt(token, secret_key)
    if not user_id:
        return jsonify({"error": "Invalid or expired token"}), 401

    # Optionally, verify the user exists (like in fetch_orders)
    users_collection = current_app.config['USERS_COLLECTION']
    user = users_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        return jsonify({"error": "User not found"}), 404

    orders_collection = current_app.config.get('ORDERS_COLLECTION')
    if orders_collection is None:
        return jsonify({"error": "Orders collection not configured."}), 500

    update_data = request.get_json()
    if update_data is None:
        return jsonify({"error": "Invalid or missing JSON data."}), 400

    current_app.logger.info(f"Update data received for order {order_id}: {update_data}")

    # Optionally perform validation on update_data.
    # For a partial update, you might not require all keys.
    
    # Set updated timestamp if needed:
    update_data["updated_date"] = datetime.utcnow()

    # Update the order (using $set for a partial update)
    result = orders_collection.update_one(
        {"_id": ObjectId(order_id), "salesperson": user_id},  # Ensure salesperson owns the order
        {"$set": update_data}
    )

    if result.matched_count == 0:
        return jsonify({"error": "Order not found or unauthorized"}), 404

    return jsonify({"message": "Order updated successfully!"}), 200



@api_sales_bp.route('/orders/<order_id>', methods=['DELETE'])
def delete_order(order_id):
    # Authenticate the user
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith("Bearer "):
        current_app.logger.error("Missing or invalid Authorization header.")
        return jsonify({"error": "Missing or invalid Authorization header."}), 401

    token = auth_header.replace("Bearer ", "").strip()
    secret_key = current_app.config['JWT_SECRET']
    user_id = decode_jwt(token, secret_key)
    if not user_id:
        current_app.logger.error("JWT decoding failed or token expired.")
        return jsonify({"error": "Invalid or expired token"}), 401

    current_app.logger.info(f"JWT decoded successfully. User ID: {user_id}")

    # Verify the user exists
    users_collection = current_app.config['USERS_COLLECTION']
    try:
        user_obj = users_collection.find_one({"_id": ObjectId(user_id)})
    except Exception as e:
        current_app.logger.error(f"Error fetching user: {e}")
        return jsonify({"error": "Error fetching user"}), 500

    if not user_obj:
        current_app.logger.error(f"User not found for ID: {user_id}")
        return jsonify({"error": "User not found"}), 404

    current_app.logger.info(f"User found: {user_obj.get('email', 'No Email Provided')} (ID: {user_id})")

    orders_collection = current_app.config.get('ORDERS_COLLECTION')
    if orders_collection is None:
        current_app.logger.error("Orders collection not configured.")
        return jsonify({"error": "Orders collection not configured."}), 500

    current_app.logger.info(f"Attempting to delete order with ID: {order_id} by user: {user_id}")

    # Try to fetch the order document first
    try:
        order_doc = orders_collection.find_one({"_id": ObjectId(order_id)})
    except Exception as e:
        current_app.logger.error(f"Error fetching order: {e}")
        return jsonify({"error": "Error fetching order"}), 500

    if order_doc:
        current_app.logger.info(f"Found order document: {order_doc}")
        # Log the salesperson stored in the order for clarity
        current_app.logger.info(f"Order salesperson: {order_doc.get('salesperson')}")
    else:
        current_app.logger.error(f"No order found with ID: {order_id}")
        return jsonify({"error": "Order not found"}), 404

    # Perform the deletion; ensure the salesperson matches.
    try:
        result = orders_collection.delete_one({
            "_id": ObjectId(order_id),
            "salesperson": user_id
        })
    except Exception as e:
        current_app.logger.error(f"Exception occurred while deleting order: {e}")
        return jsonify({"error": f"Exception occurred: {e}"}), 500

    current_app.logger.info(f"Delete result: {result.deleted_count} document(s) removed.")

    if result.deleted_count == 0:
        current_app.logger.error("Order not found or unauthorized deletion attempt.")
        return jsonify({"error": "Order not found or unauthorized"}), 404

    current_app.logger.info(f"Order {order_id} deleted successfully by user {user_id}.")
    return jsonify({"message": "Order deleted successfully!"}), 200











@api_sales_bp.route('/create_payment_intent', methods=['POST'])
def create_payment_intent():
    try:
        data = request.get_json()
        amount = data.get("amount")
        order_id = data.get("order_id")
        if not amount or not order_id:
            return jsonify({"error": "Missing amount or order_id"}), 400
        
        # Optionally, validate the order exists and is in a proper state

        # Create a PaymentIntent with the specified amount (in cents)
        intent = stripe.PaymentIntent.create(
            amount=amount,
            currency="usd",
            metadata={"order_id": order_id}
        )
        return jsonify({"client_secret": intent.client_secret}), 200
    except Exception as e:
        current_app.logger.error(f"Error creating PaymentIntent: {e}")
        return jsonify({"error": str(e)}), 500