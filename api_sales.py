#api_sales.py
from flask import Blueprint, request, jsonify, current_app, render_template, Flask
from datetime import datetime
from flask_login import current_user  
import jwt
from bson import ObjectId
from config import Config
import stripe
from notis import send_postmark_email
from jwt import ExpiredSignatureError, InvalidTokenError
from postmark_client import is_valid_email  # already imported above
import os


api_sales_bp = Blueprint('api_sales', __name__, url_prefix='/api')




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

        # (Validation code omitted for brevity)

        # Set default values if needed.
        if "creation_date" not in order_data:
            order_data["creation_date"] = datetime.utcnow()
        order_data["is_guest"] = True

        # Insert the order into the database.
        result = orders_collection.insert_one(order_data)
        order_id = str(result.inserted_id)
        current_app.logger.info(f"Order inserted with id: {order_id}")

        # **Set the Stripe API key here**
        stripe.api_key = current_app.config.get('STRIPE_SECRET_KEY')

        # Create a PaymentIntent for this order.
        final_price = float(order_data["final_price"])  # in dollars
        amount = int(final_price * 100)  # convert dollars to cents

        intent = stripe.PaymentIntent.create(
            amount=amount,
            currency="usd",
            payment_method_types=["card"],
            metadata={"order_id": order_id}
        )
        current_app.logger.info(f"PaymentIntent created: {intent.id}")

        # (Rest of your code...)
        return jsonify({
            "message": "Order created successfully!",
            "order_id": order_id,
            "checkout_url": checkout_session.url,
            "client_secret": intent.client_secret
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
        current_app.logger.info("Received request to create payment intent.")
        data = request.get_json()
        order_id = data.get("order_id")
        if not order_id:
            current_app.logger.error("Missing order_id in request.")
            return jsonify({"error": "Missing order_id"}), 400

        # Retrieve the order from the collection
        orders_collection = current_app.config['ORDERS_COLLECTION']
        order = orders_collection.find_one({"_id": ObjectId(order_id)})
        current_app.logger.debug(f"Order fetched from DB: {order}")
        if not order:
            current_app.logger.error(f"Order with id {order_id} not found.")
            return jsonify({"error": "Order not found"}), 404

        final_price_dollars = order.get("final_price")
        if final_price_dollars is None:
            current_app.logger.error("Order missing final price.")
            return jsonify({"error": "Order missing final price"}), 400

        amount = int(float(final_price_dollars) * 100)
        payment_time = order.get("payment_time", "pay_now")
        current_app.logger.info(f"Final price: {final_price_dollars} dollars, converted to {amount} cents.")
        current_app.logger.info(f"Payment time set to: {payment_time}")

        stripe.api_key = current_app.config['STRIPE_SECRET_KEY']
        capture_method = "automatic"
        if payment_time == "pay_after_completion":
            capture_method = "manual"
        current_app.logger.info(f"Using capture method: {capture_method}")

        # Create the PaymentIntent
        intent = stripe.PaymentIntent.create(
            amount=amount,
            currency="usd",
            capture_method=capture_method,
            payment_method_types=["card"],
            metadata={
                "order_id": order_id,
                "payment_time": payment_time
            }
        )
        current_app.logger.info(f"PaymentIntent created: {intent.id}")

        # Patch the order to store the PaymentIntent info
        update_data = {
            "payment_intent_id": intent.id,
            "client_secret": intent.client_secret,  # optional: use with caution
            "stripe_payment_status": intent.status  # e.g., "requires_payment_method"
        }
        orders_collection.update_one({"_id": ObjectId(order_id)}, {"$set": update_data})
        current_app.logger.info("Order updated with PaymentIntent info.")

        return jsonify({"client_secret": intent.client_secret}), 200

    except Exception as e:
        current_app.logger.exception("Error creating PaymentIntent")
        return jsonify({"error": str(e)}), 500













@api_sales_bp.route("/send_test_email")
def send_test_email():
    try:
        # Use your environment variable for the sender email
        sender_email = os.getenv("POSTMARK_SENDER_EMAIL")
        # Define the recipient email for testing
        recipient_email = "yeurysl17@gmail.com"
        
        # Call your Postmark email helper instead of Flask-Mail
        response = send_postmark_email(
            subject="Test Email via Postmark",
            to_email=recipient_email,
            from_email=sender_email,
            text_body="This is a test email sent via Postmark!"
        )
        
        current_app.logger.info(f"Test email response: {response}")
        return "Postmark Test Email sent successfully!", 200
    except Exception as e:
        current_app.logger.error(f"Error sending test email via Postmark: {e}", exc_info=True)
        return f"Error: {str(e)}", 500