#api_sales.py
from flask import Blueprint, request, jsonify, current_app, render_template, Flask
from datetime import datetime
from flask_login import current_user  
import jwt
from bson import ObjectId
from config import Config
import stripe
from notis import send_payment_links
import requests
from jwt import ExpiredSignatureError, InvalidTokenError
from postmark_client import is_valid_email  # already imported above
import os
from datetime import datetime
import pytz


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

        # Set the 'is_guest' key to 'yes' for all guest orders.
        order_data["is_guest"] = True

        # Validate and set default values
        current_app.logger.info(f"Order data received: {order_data}")
        if "creation_date" not in order_data:
            order_data["creation_date"] = datetime.utcnow()

        # --- New: Calculate travel fee ---
        try:
            final_price = float(order_data.get("final_price", 0))
        except (ValueError, TypeError):
            final_price = 0.0

        # If final price is under $90, apply a $25 travel fee.
        if final_price < 90:
            order_data["travel_fee"] = 25.0
        else:
            order_data["travel_fee"] = 0.0
        # -----------------------------------

        # Insert the order into the database.
        result = orders_collection.insert_one(order_data)
        order_id = str(result.inserted_id)
        current_app.logger.info(f"Order inserted with id: {order_id}")

        final_price = float(order_data["final_price"])

        # Calculate down payment and remaining balance
        downpayment_amount = int(final_price * 100 * 0.40)  # 40% of the total price
        remaining_amount = int(final_price * 100 * 0.60)  # Remaining 60%

        # Set Stripe API key
        stripe.api_key = current_app.config['STRIPE_SECRET_KEY']

        # Create the PaymentIntent for the down payment (40%)
        downpayment_intent = stripe.PaymentIntent.create(
            amount=downpayment_amount,
            currency="usd",
            payment_method_types=["card"],
            metadata={"order_id": order_id, "payment_type": "downpayment"}
        )

        # Create the PaymentIntent for the remaining balance (60%)
        remaining_intent = stripe.PaymentIntent.create(
            amount=remaining_amount,
            currency="usd",
            payment_method_types=["card"],
            metadata={"order_id": order_id, "payment_type": "remaining_balance"},
            capture_method="manual"  # Manual capture, this will allow charging later
        )

        downpayment_checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": f"Down Payment for Order #{order_id}",
                    },
                    "unit_amount": downpayment_amount,
                },
                "quantity": 1,
            }],
            customer_email=order_data.get("guest_email"),
            success_url=current_app.config.get("CHECKOUT_SUCCESS_URL", "https://cfautocare.biz/payment_success?session_id={CHECKOUT_SESSION_ID}"),
            cancel_url=current_app.config.get("CHECKOUT_CANCEL_URL", "https://cfautocare.biz/payment_cancel"),
            payment_intent_data={
                "metadata": {"order_id": order_id, "payment_type": "downpayment"}
            },
            mode="payment"
        )

        # Create a Stripe Checkout session for the remaining balance
        remaining_checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": f"Remaining Balance for Order #{order_id}",
                    },
                    "unit_amount": remaining_amount,
                },
                "quantity": 1,
            }],
            customer_email=order_data.get("guest_email"),
            success_url=current_app.config.get("CHECKOUT_SUCCESS_URL", "https://cfautocare.biz/payment_success"),
            cancel_url=current_app.config.get("CHECKOUT_CANCEL_URL", "https://cfautocare.biz"),
            payment_intent_data={
                "metadata": {"order_id": order_id, "payment_type": "remaining_balance"}
            },
            mode="payment"
        )

        # Update the order with PaymentIntent info (down payment and remaining balance)
        update_data = {
            "payment_intent_downpayment": downpayment_intent.id,
            "client_secret_downpayment": downpayment_intent.client_secret,
            "payment_intent_remaining_balance": remaining_intent.id,
            "client_secret_remaining_balance": remaining_intent.client_secret,
            "downpayment_checkout_url": downpayment_checkout_session.url,
            "remaining_balance_checkout_url": remaining_checkout_session.url,
            "payment_status": "Pending", 
            "has_downpayment_collected": "no"  # We'll update this after the down payment is collected
        }
        orders_collection.update_one({"_id": ObjectId(order_id)}, {"$set": update_data})

        # Call the send_payment_links function from notis.py
        result = send_payment_links(order_id)

        # Check if sending payment links was successful
        if result[1] != 200:
            current_app.logger.error(f"Failed to send payment links: {result[0]}")
            return jsonify({"error": "Failed to send payment links"}), 500

        return jsonify({
            "message": "Order created successfully and payment links sent to customer!"
        }), 201

    except Exception as e:
        current_app.logger.error(f"Error creating order: {e}", exc_info=True)
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

        # Calculate 40% down payment amount
        downpayment_amount = int(float(final_price_dollars) * 100 * 0.40)  # 40% of the total price
        payment_time = order.get("payment_time", "pay_now")
        current_app.logger.info(f"Final price: {final_price_dollars} dollars, down payment: {downpayment_amount} cents.")
        current_app.logger.info(f"Payment time set to: {payment_time}")

        # Set your Stripe secret key
        stripe.api_key = current_app.config['STRIPE_SECRET_KEY']
        capture_method = "automatic"
        if payment_time == "pay_after_completion":
            capture_method = "manual"
        current_app.logger.info(f"Using capture method: {capture_method}")

        # Create the PaymentIntent via Stripe for the down payment
        intent = stripe.PaymentIntent.create(
            amount=downpayment_amount,
            currency="usd",
            capture_method=capture_method,
            payment_method_types=["card"],
            metadata={
                "order_id": order_id,
                "payment_time": payment_time
            }
        )
        current_app.logger.info(f"PaymentIntent created: {intent.id}")

        # Update the order to store PaymentIntent info
        update_data = {
            "payment_intent_id": intent.id,
            "client_secret": intent.client_secret,  # used on client side for confirmation
            "stripe_payment_status": intent.status,  # e.g., "requires_payment_method"
            "payment_status": "downpaymentcollected"  # Set the payment status to 'downpaymentcollected'
        }
        orders_collection.update_one({"_id": ObjectId(order_id)}, {"$set": update_data})
        current_app.logger.info("Order updated with PaymentIntent info and down payment status.")

        return jsonify({"client_secret": intent.client_secret}), 200

    except Exception as e:
        current_app.logger.exception("Error creating PaymentIntent")
        return jsonify({"error": str(e)}), 500



@api_sales_bp.route('/webhook', methods=['POST'])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    endpoint_secret = current_app.config.get('STRIPE_WEBHOOK_SECRET')

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)

        if event['type'] == 'payment_intent.succeeded':
            intent = event['data']['object']
            current_app.logger.info(f"PaymentIntent succeeded: {intent['id']}")

            order_id = intent.get('metadata', {}).get('order_id')
            if not order_id:
                current_app.logger.error(f"Order ID not found in payment intent: {intent['id']}")
                return '', 400

            orders_collection = current_app.config['ORDERS_COLLECTION']
            order = orders_collection.find_one({"_id": ObjectId(order_id)})
            if not order:
                current_app.logger.error(f"Order not found: {order_id}")
                return '', 400

            payment_type = intent.get('metadata', {}).get('payment_type')
            if payment_type == 'downpayment':
                orders_collection.update_one(
                    {"_id": ObjectId(order_id)},
                    {"$set": {"has_downpayment_collected": "yes", "payment_status": "downpaymentcollected"}}
                )
                # Send thank-you email for the down payment
                from notis import send_downpayment_thankyou_email
                send_downpayment_thankyou_email(order)
            elif payment_type == 'remaining_balance':
                orders_collection.update_one(
                    {"_id": ObjectId(order_id)},
                    {"$set": {"payment_status": "completed"}}
                )
                # Send thank-you email for the remaining balance
                from notis import send_remaining_payment_thankyou_email
                send_remaining_payment_thankyou_email(order)
            return '', 200

    except Exception as e:
        current_app.logger.error(f"Error processing webhook: {e}")
        return '', 400



@api_sales_bp.route('/collect_downpayment', methods=['POST'])
def collect_downpayment():
    order_id = request.json.get("order_id")
    payment_intent_id = request.json.get("payment_intent_id")

    orders_collection = current_app.config.get('ORDERS_COLLECTION')
    order = orders_collection.find_one({"_id": ObjectId(order_id)})

    if not order:
        return jsonify({"error": "Order not found"}), 404

    if order.get("payment_intent_downpayment") != payment_intent_id:
        return jsonify({"error": "Invalid PaymentIntent ID for down payment"}), 400

    # Capture the down payment
    try:
        intent = stripe.PaymentIntent.retrieve(payment_intent_id)
        intent.confirm()  # Confirm the payment intent for down payment

        # Update the order status after payment collection
        orders_collection.update_one(
            {"_id": ObjectId(order_id)},
            {"$set": {
                "has_downpayment_collected": "yes",
                "payment_status": "downpaymentcollected"
            }}
        )

        return jsonify({"message": "Down payment collected and order updated"}), 200
    except stripe.error.StripeError as e:
        return jsonify({"error": str(e)}), 500








@api_sales_bp.route('/collect_remaining_balance', methods=['POST'])
def collect_remaining_balance():
    order_id = request.json.get("order_id")
    payment_intent_id = request.json.get("payment_intent_id")

    orders_collection = current_app.config.get('ORDERS_COLLECTION')
    order = orders_collection.find_one({"_id": ObjectId(order_id)})

    if not order:
        return jsonify({"error": "Order not found"}), 404

    if order.get("payment_intent_remaining_balance") != payment_intent_id:
        return jsonify({"error": "Invalid PaymentIntent ID for remaining balance"}), 400

    # Capture the remaining balance
    try:
        intent = stripe.PaymentIntent.retrieve(payment_intent_id)
        intent.capture()  # Capture the remaining balance

        # Update the order status to 'completed' after the remaining balance is collected
        orders_collection.update_one(
            {"_id": ObjectId(order_id)},
            {"$set": {
                "payment_status": "completed"
            }}
        )

        return jsonify({"message": "Remaining balance collected and order completed"}), 200
    except stripe.error.StripeError as e:
        return jsonify({"error": str(e)}), 500




@api_sales_bp.route('/get_payment_intent', methods=['POST'])
def get_payment_intent():
    order_id = request.json.get("order_id")
    orders_collection = current_app.config.get('ORDERS_COLLECTION')
    order = orders_collection.find_one({"_id": ObjectId(order_id)})

    if not order:
        return jsonify({"error": "Order not found"}), 404

    payment_intent_id = order.get("payment_intent_id")
    if not payment_intent_id:
        return jsonify({"error": "PaymentIntent not found for order"}), 400

    # Fetch PaymentIntent from Stripe
    stripe.api_key = current_app.config['STRIPE_SECRET_KEY']
    try:
        payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)
        return jsonify({
            "client_secret": payment_intent.client_secret
        }), 200
    except stripe.error.StripeError as e:
        return jsonify({"error": str(e)}), 500





@api_sales_bp.route('/compensated_orders', methods=['GET'])
def fetch_compensated_orders():
    try:
        # Retrieve the salesperson's ID from the query parameter.
        salesperson_id = request.args.get("salesperson")
        if not salesperson_id:
            return jsonify({"error": "Salesperson ID is required."}), 400

        # Access the orders collection from your database configuration.
        orders_collection = current_app.config.get('ORDERS_COLLECTION')
        if orders_collection is None:
            return jsonify({"error": "Orders collection not configured."}), 500

        # Build the query.
        # This query returns all orders where the 'salesperson' field matches the provided salesperson_id.
        # You can further filter based on compensation status if needed.
        query = {"salesperson": salesperson_id}
        orders_cursor = orders_collection.find(query)
        orders = []

        for order in orders_cursor:
            order['_id'] = str(order['_id'])
            # Optionally convert datetime fields to ISO strings
            if 'creation_date' in order and isinstance(order['creation_date'], datetime):
                order['creation_date'] = order['creation_date'].isoformat()
            if 'service_date' in order and isinstance(order['service_date'], datetime):
                order['service_date'] = order['service_date'].isoformat()
            orders.append(order)

        if not orders:
            return jsonify({"message": "No compensated orders found."}), 404

        return jsonify({"orders": orders}), 200

    except Exception as e:
        current_app.logger.error(f"Error fetching compensated orders: {str(e)}", exc_info=True)
        return jsonify({"error": f"Error fetching compensated orders: {str(e)}"}), 500


def calculate_remaining_time(scheduled_time: datetime) -> dict:
    current_time = datetime.utcnow().replace(tzinfo=pytz.UTC)
    time_diff = scheduled_time - current_time

    # Calculate remaining hours and minutes
    hours_remaining = time_diff.total_seconds() // 3600
    minutes_remaining = (time_diff.total_seconds() % 3600) // 60

    # Check if time difference is negative (i.e., past the scheduled time)
    if time_diff.total_seconds() < 0:
        return {"error": "Order time has passed"}
    
    return {
        "hours_remaining": int(hours_remaining),
        "minutes_remaining": int(minutes_remaining)
    }



@api_sales_bp.route('/orders/<order_id>/remaining_time', methods=['GET'])
def get_order_remaining_time(order_id):
    try:
        # Fetch the order from the database
        orders_collection = current_app.config.get('MONGO_CLIENT').orders
        order = orders_collection.find_one({"_id": ObjectId(order_id)})

        if not order:
            return jsonify({"error": "Order not found"}), 404

        # Ensure the 'service_date' exists and convert it to a datetime object if needed
        if 'service_date' not in order:
            return jsonify({"error": "Service date not found"}), 400

        if isinstance(order['service_date'], str):
            try:
                order['service_date'] = datetime.fromisoformat(order['service_date'])
            except ValueError:
                return jsonify({"error": "Invalid service date format"}), 400

        # Print the service date for debugging
        print("Service Date:", order['service_date'])

        # If available, do the same for the creation_date
        if 'creation_date' in order:
            if isinstance(order['creation_date'], str):
                try:
                    order['creation_date'] = datetime.fromisoformat(order['creation_date'])
                except ValueError:
                    print(f"Invalid creation date format for order {order['_id']}")
            print("Creation Date:", order.get('creation_date'))
        else:
            print(f"Creation Date not found for order {order['_id']}")

        # Calculate the remaining time until the service
        remaining_time = calculate_remaining_time(order['service_date'])
        if "error" in remaining_time:
            return jsonify(remaining_time), 400

        # Use the current time in UTC
        current_time_utc = datetime.utcnow().replace(tzinfo=pytz.UTC)

        # Ensure the service date is in UTC
        scheduled_time = order['service_date']
        if scheduled_time.tzinfo is None:
            scheduled_time = scheduled_time.replace(tzinfo=pytz.UTC)
        else:
            scheduled_time = scheduled_time.astimezone(pytz.UTC)

        # Return the remaining time along with the current and scheduled times in UTC
        response = {
            "remaining_time": remaining_time,
            "current_time_utc": current_time_utc.isoformat(),
            "scheduled_time_utc": scheduled_time.isoformat()
        }

        return jsonify(response), 200

    except Exception as e:
        print(f"Error calculating remaining time for order {order_id}: {str(e)}")
        current_app.logger.error(f"Error calculating remaining time for order {order_id}: {str(e)}")
        return jsonify({"error": f"Error fetching order remaining time: {str(e)}"}), 500






































































import pymongo
from flask import request, jsonify, current_app
from datetime import datetime

@api_sales_bp.route("/register_device_token", methods=["POST"])
def register_device_token_sales():
    data = request.get_json()
    if not data or "device_token" not in data:
        current_app.logger.error("No device token provided in the request.")
        return jsonify({"error": "No device token provided"}), 400

    device_token = data["device_token"]
    user_id = data.get("user_id")

    # Validate
    if not device_token or len(device_token) < 10:
        current_app.logger.error("Invalid device token provided.")
        return jsonify({"error": "Invalid device token provided"}), 400

    db = current_app.config.get('MONGO_CLIENT')
    if db is None:
        current_app.logger.error("Database connection not configured!")
        return jsonify({"error": "Database connection error"}), 500

    device_tokens_collection = db.device_tokens

    try:
        # Use upsert: update if document with user_id exists, otherwise insert a new one.
        result = device_tokens_collection.update_one(
            {"user_id": user_id},  # Query by user_id
            {
                "$set": {
                    "device_token": device_token,
                    "updated_at": datetime.utcnow()
                },
                "$setOnInsert": {
                    "created_at": datetime.utcnow()
                }
            },
            upsert=True
        )

        if result.upserted_id:
            # Means a new doc was created
            current_app.logger.info(f"Inserted device token for user {user_id}, _id={result.upserted_id}")
            return jsonify({"status": "success", "inserted_id": str(result.upserted_id)}), 201
        else:
            # Means an existing doc was updated
            current_app.logger.info(f"Updated device token for user {user_id}.")
            return jsonify({"status": "success", "message": "Token updated"}), 200

    except pymongo.errors.PyMongoError as e:
        current_app.logger.error(f"Error upserting device token: {str(e)}")
        return jsonify({"error": "Database error", "details": str(e)}), 500
@api_sales_bp.route("/sales/<salesman_id>/device_token", methods=["GET"])
def retrieve_salesman_device_token(salesman_id):
    """
    Retrieve the device token for the given salesman.
    """
    token = get_device_token_for_user(salesman_id)
    if token:
        current_app.logger.info(f"Device token retrieved for salesman {salesman_id}: {token}")
        return jsonify({"status": "success", "device_token": token}), 200
    else:
        current_app.logger.warning(f"No device token found for salesman {salesman_id}")
        return jsonify({"error": "Device token not found for salesman"}), 404


def get_device_token_for_user(user_id):
    current_app.logger.info(f"Attempting to fetch device token for user {user_id} from the device_tokens collection.")
    # Retrieve the device_tokens collection from your MongoDB client
    device_tokens_collection = current_app.config.get('MONGO_CLIENT').device_tokens
    user_record = device_tokens_collection.find_one({"user_id": user_id})
    
    if user_record and "device_token" in user_record:
        token = user_record["device_token"]
        current_app.logger.info(f"Device token retrieved for user {user_id}: {token}")
        return token
    else:
        current_app.logger.warning(f"Device token not found for user {user_id}.")
        return None
    

import os
import base64
import traceback
import tempfile
from apns2.client import APNsClient
from apns2.payload import Payload
from flask import current_app


def send_notification_to_salesman(salesman_id, order_id, device_token, custom_message=None):
    """
    Send a push notification to a salesman's device.
    """
    message = custom_message or f"The Tech for {order_id} is on the way."
    current_app.logger.info(f"Preparing to send notification to salesman {salesman_id}: {message}")

    # Retrieve the certificate from the environment variable.
    cert_b64 = os.environ.get("APNS_CERT_B64_SALESMAN")
    if not cert_b64:
        current_app.logger.error("APNS certificate for salesman not configured in environment variable!")
        return {"status": "error", "detail": "Salesman certificate not set"}

    try:
        current_app.logger.info("Decoding APNs certificate from base64.")
        cert_content = base64.b64decode(cert_b64)
        current_app.logger.info("Writing APNs certificate to a temporary file.")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as temp_cert:
            temp_cert.write(cert_content)
            temp_cert_path = temp_cert.name
        current_app.logger.info(f"APNs certificate written to temporary file: {temp_cert_path}")

        # Construct the APNs payload.
        current_app.logger.info("Constructing APNs payload...")
        payload = Payload(alert={"title": "Order Update", "body": message}, sound="default", badge=1)
        current_app.logger.info(f"Payload constructed: alert={payload.alert}, sound={payload.sound}, badge={payload.badge}")

        # Specify the topic (bundle identifier) for your sales app.
        topic = "com.Centralfloridaautocare.cfacios"  # Update this if your sales app's bundle identifier is different.
        current_app.logger.info(f"Using topic: {topic}")

        # Create the APNs client.
        current_app.logger.info("Creating APNs client...")
        client = APNsClient(temp_cert_path, use_sandbox=False, use_alternative_port=False)
        current_app.logger.info("APNs client created successfully.")

        # Send the notification.
        current_app.logger.info("Sending push notification to device...")
        response = client.send_notification(device_token, payload, topic=topic)
        current_app.logger.info(f"Push notification response: {response}")

        # Clean up the temporary certificate file.
        os.remove(temp_cert_path)
        current_app.logger.info("Temporary certificate file removed.")
        return {"status": "sent", "detail": str(response)}
    except Exception as e:
        current_app.logger.error("Error sending push notification to salesman:")
        current_app.logger.error(traceback.format_exc())
        return {"status": "error", "detail": str(e) or "No error detail provided"}
