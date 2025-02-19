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




@api_tech_bp.route('/orders/<order_id>/status', methods=['PATCH'])
def update_order_status(order_id):
    try:
        # Get the new status from the request JSON payload.
        data = request.get_json()
        new_status = data.get("status")
        if not new_status:
            return jsonify({"error": "Missing status parameter"}), 400

        # Update the order in the database
        orders_collection = current_app.config.get('MONGO_CLIENT').orders
        result = orders_collection.update_one(
            {"_id": ObjectId(order_id)},
            {"$set": {"status": new_status}}
        )

        if result.matched_count == 0:
            return jsonify({"error": "Order not found"}), 404

        return jsonify({"message": "Order status updated successfully", "new_status": new_status}), 200
    except Exception as e:
        current_app.logger.error(f"Error updating order status for {order_id}: {str(e)}")
        return jsonify({"error": f"Error updating order status: {str(e)}"}), 500








































#Testing Push notis







from flask import current_app, jsonify, request
from datetime import datetime
import pytz
import math

from apns2.client import APNsClient
from apns2.payload import Payload
from flask import current_app

def send_notification_to_tech(tech_id, order_id, threshold):
    message = f"Order {order_id} is now within {threshold} hours of service!"
    current_app.logger.info(f"Preparing to send notification to technician {tech_id}: {message}")
    
    # For testing, you can use the device token printed by your app.
    # In a real scenario, retrieve the technician's device token from your database.
    # For example:
    # device_token = get_device_token_for_technician(tech_id)
    # For now, we'll assume the device token is provided directly.
    device_token = "099515daa605d1b4cb01caf37990538546b41f21a14715b93e8d2cd3de1b5bd7"
    
    # Construct the payload
    payload = Payload(alert={"title": "Test Notification", "body": message}, sound="default", badge=1)
    
    # Create an APNs client
    # Set use_sandbox=True if you are testing with a development build or on TestFlight using a development certificate.
    # For production builds with a production certificate, use_sandbox=False.
    try:
        client = APNsClient('pushcert.pem', use_sandbox=True, use_alternative_port=False)
        # The topic should match your app's bundle identifier.
        response = client.send_notification(device_token, payload, topic="biz.cfautocare.cfactech")
        current_app.logger.info(f"Push notification response for technician {tech_id}, order {order_id}: {response}")
        return {"status": "sent", "detail": str(response)}
    except Exception as e:
        current_app.logger.error(f"Error sending push notification: {str(e)}")
        return {"status": "error", "detail": str(e)}



















def notify_techs_for_upcoming_orders():
    try:
        orders_collection = current_app.config.get('MONGO_CLIENT').orders
        current_time = datetime.utcnow().replace(tzinfo=pytz.UTC)
        
        # Query orders that are scheduled in the future
        orders_cursor = orders_collection.find({
            "service_date": {"$gt": current_time}
        })
        
        thresholds = [12, 6, 2]  # in hours
        
        for order in orders_cursor:
            # Ensure service_date is a datetime object in UTC
            service_date = order.get('service_date')
            if isinstance(service_date, str):
                service_date = datetime.fromisoformat(service_date)
            if service_date.tzinfo is None:
                service_date = service_date.replace(tzinfo=pytz.UTC)
            else:
                service_date = service_date.astimezone(pytz.UTC)
            
            time_diff = service_date - current_time
            hours_remaining = time_diff.total_seconds() / 3600
            
            notified_thresholds = order.get("notified_thresholds", [])
            
            for threshold in thresholds:
                if hours_remaining <= threshold and threshold not in notified_thresholds:
                    tech_id = order.get("technician")
                    order_id = str(order.get("_id"))
                    
                    current_app.logger.info(
                        f"Order {order_id} is within {threshold} hours. Technician ID: {tech_id}. " +
                        f"Already notified thresholds: {notified_thresholds}"
                    )
                    
                    # Send notification to the technician's iOS app and log the response
                    push_response = send_notification_to_tech(tech_id, order_id, threshold)
                    current_app.logger.info(f"Notification push response: {push_response}")
                    
                    # Mark this threshold as notified
                    orders_collection.update_one(
                        {"_id": order["_id"]},
                        {"$push": {"notified_thresholds": threshold}}
                    )
    except Exception as e:
        current_app.logger.error(f"Error in notify_techs_for_upcoming_orders: {str(e)}")

from apscheduler.schedulers.background import BackgroundScheduler

def start_scheduler(app):
    scheduler = BackgroundScheduler()
    
    # The function runs every 5 minutes; adjust the interval as needed.
    scheduler.add_job(
        func=lambda: app.app_context().push() or notify_techs_for_upcoming_orders(), 
        trigger="interval", 
        minutes=5
    )
    
    scheduler.start()
    app.logger.info("Starting notification scheduler")
    
    # Ensure the scheduler is shut down when the app exits.
    import atexit
    atexit.register(lambda: scheduler.shutdown())

@api_tech_bp.route('/test_push', methods=['POST'])
def test_push_notification():
    try:
        data = request.get_json()
        current_app.logger.info(f"Received test push request with data: {data}")
        
        tech_id = data.get("technician")
        order_id = data.get("order_id", "test_order")
        threshold = data.get("threshold", 12)  # default threshold
        
        if not tech_id:
            current_app.logger.warning("Test push: Technician ID is missing in the request.")
            return jsonify({"error": "Technician ID is required."}), 400
        
        # Call your push notification function and log the response
        push_response = send_notification_to_tech(tech_id, order_id, threshold)
        current_app.logger.info(f"Test push notification sent. Response: {push_response}")
        
        return jsonify({"message": "Test push notification sent.", "push_response": push_response}), 200
    except Exception as e:
        current_app.logger.error(f"Error in test_push_notification: {str(e)}")
        return jsonify({"error": f"Error sending test push notification: {str(e)}"}), 500
