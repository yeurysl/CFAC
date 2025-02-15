from flask import Blueprint, request, jsonify, current_app
from bson import ObjectId
from datetime import datetime
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
import jwt
import math
import pytz




api_tech_bp = Blueprint('api_tech', __name__, url_prefix='/api/tech')

@api_tech_bp.route('/orders_with_downpayment', methods=['GET'])
def fetch_orders_with_downpayment():
    try:
        # Get the orders collection
        orders_collection = current_app.config.get('MONGO_CLIENT').orders

            # Query orders with downpayment
        orders_cursor = orders_collection.find({
                "has_downpayment_collected": "yes",
                "$or": [
                    {"orderhasbeenscheduled": {"$exists": False}},
                    {"orderhasbeenscheduled": False}
                ]
            })        
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

    # Get the update data from the request
    update_data = request.get_json()
    if "technician" in update_data:
        # Compute tech pay from services_total (rounded down)
        services_total = order.get("services_total", 0)
        tech_pay = math.floor(services_total)
        
        # Create a dictionary that includes all the fields you want to update
        update_fields = {
            "technician": update_data["technician"],
            "orderhasbeenscheduled": True,
            "updated_date": datetime.utcnow(),
            "tech_pay": tech_pay  # New field for the tech's pay
        }

        # Update the order with the new data
        result = orders_collection.update_one(
            {"_id": ObjectId(order_id)},
            {"$set": update_fields}
        )
        
        if result.modified_count > 0:
            return jsonify({"message": "Order updated successfully."}), 200
        else:
            return jsonify({"error": "Order update failed."}), 500
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


@api_tech_bp.route('/scheduled_orders', methods=['GET'])
def fetch_scheduled_orders():
    try:
        # Get the technician ID from the query parameters
        technician_id = request.args.get("technician")
        if not technician_id:
            return jsonify({"error": "Technician ID is required."}), 400

        orders_collection = current_app.config.get('ORDERS_COLLECTION')
        if orders_collection is None:
            return jsonify({"error": "Orders collection not configured."}), 500

        # Query for orders where the technician field matches the given technician_id.
        # This does not filter out orders based on any scheduling flag.
        orders_cursor = orders_collection.find({"technician": technician_id})
        orders = []
        for order in orders_cursor:
            order['_id'] = str(order['_id'])
            # Convert datetime fields to ISO strings if necessary
            if 'service_date' in order and isinstance(order['service_date'], datetime):
                order['service_date'] = order['service_date'].isoformat()
            orders.append(order)

        if not orders:
            return jsonify({"message": "No scheduled orders found."}), 404

        return jsonify({"orders": orders}), 200

    except Exception as e:
        current_app.logger.error(f"Error fetching scheduled orders: {str(e)}", exc_info=True)
        return jsonify({"error": f"Error fetching scheduled orders: {str(e)}"}), 500







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



@api_tech_bp.route('/orders/<order_id>/remaining_time', methods=['GET'])
def get_order_remaining_time(order_id):
    try:
        # Fetch the order from the database
        orders_collection = current_app.config.get('MONGO_CLIENT').orders
        order = orders_collection.find_one({"_id": ObjectId(order_id)})

        if not order:
            return jsonify({"error": "Order not found"}), 404

        # Ensure the 'service_date' exists and is a datetime object
        if 'service_date' not in order:
            return jsonify({"error": "Service date not found"}), 400
        
        if isinstance(order['service_date'], str):
            try:
                order['service_date'] = datetime.fromisoformat(order['service_date'])
            except ValueError:
                return jsonify({"error": "Invalid service date format"}), 400
        
        # Calculate the remaining time
        remaining_time = calculate_remaining_time(order['service_date'])
        
        if "error" in remaining_time:
            return jsonify(remaining_time), 400

        # Get the user's time zone from the query parameters (default to Eastern Time if not provided)
        user_timezone = request.args.get("user_timezone", "America/New_York")  # Default to Eastern Time (New York)

        # Convert the current UTC time to the user's local time zone
        utc_time = datetime.utcnow().replace(tzinfo=pytz.UTC)
        
        # Check if the user timezone is valid
        try:
            user_time_zone = pytz.timezone(user_timezone)
            local_time = utc_time.astimezone(user_time_zone)
        except pytz.UnknownTimeZoneError:
            return jsonify({"error": "Invalid time zone"}), 400

        # Return both remaining time and the current local time
        response = {
            "remaining_time": remaining_time,
            "current_time_local": local_time.isoformat()  # Convert current local time to ISO format
        }

        return jsonify(response), 200

    except Exception as e:
        current_app.logger.error(f"Error calculating remaining time for order {order_id}: {str(e)}")
        return jsonify({"error": f"Error fetching order remaining time: {str(e)}"}), 500
