from flask import Blueprint, request, jsonify, current_app
from bson import ObjectId
from datetime import datetime
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
import jwt
import math
from apns2.client import APNsClient
from apns2.payload import Payload
import tempfile
import pytz
import base64
import os




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




from postmarker.core import PostmarkClient
from flask import request, jsonify, current_app
from bson import ObjectId
from datetime import datetime

def send_postmark_email(to_email, subject, text_body, html_body=None):
    client = PostmarkClient(server_token=current_app.config.get('POSTMARK_SERVER_TOKEN'))
    response = client.emails.send(
        From=current_app.config.get('POSTMARK_SENDER_EMAIL'),
        To=to_email,
        Subject=subject,
        TextBody=text_body,
        HtmlBody=html_body or ""
    )
    current_app.logger.info(f"Postmark email response: {response}")
    return response

@api_tech_bp.route('/orders/<order_id>/status', methods=['PATCH'])
def update_order_status(order_id):
    try:
        data = request.get_json()
        new_status = data.get("status")
        if not new_status:
            return jsonify({"error": "Missing status parameter"}), 400

        orders_collection = current_app.config.get('MONGO_CLIENT').orders

        result = orders_collection.update_one(
            {"_id": ObjectId(order_id)},
            {"$set": {"status": new_status}}
        )

        if result.matched_count == 0:
            return jsonify({"error": "Order not found"}), 404

        if new_status == "on_the_way":
            order = orders_collection.find_one({"_id": ObjectId(order_id)})
            if order and order.get("guest_email"):
                guest_email = order["guest_email"]
                subject = "Your Detailer Is In Route"

                # Plain text version of the email
                text_body = (
                    f"Hello {order.get('customer_name', 'Customer')},\n\n"
                    "Your technician is now on the way to complete the job. "
                    "If you have any questions, please contact your sales rep or visit our website."
                )

                # HTML email template with header and footer
                current_year = datetime.now().year
                html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Order Update Notification</title>
    <style>
        body {{
            margin: 0;
            padding: 0;
            background-color: #f4f4f4;
            font-family: Arial, sans-serif;
        }}
        .container {{
            width: 100%;
            background-color: #f4f4f4;
            padding: 20px 0;
        }}
        .email-wrapper {{
            width: 100%;
            max-width: 600px;
            margin: 0 auto;
            background-color: #ffffff;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 3px rgba(0,0,0,0.1);
        }}
        .header {{
            background-color: #07173d;
            padding: 20px;
            text-align: center;
            color: #ffffff;
        }}
        .header img {{
            max-width: 150px;
            height: auto;
        }}
        .content {{
            padding: 20px;
            color: #333333;
        }}
        .content h2 {{
            color: #07173d;
            margin-top: 0;
        }}
        .content p {{
            line-height: 1.6;
        }}
        .footer {{
            background-color: #f1f1f1;
            padding: 15px;
            text-align: center;
            font-size: 12px;
            color: #666666;
        }}
        a {{
            color: #163351;
            text-decoration: none;
        }}
        @media only screen and (max-width: 600px) {{
            .email-wrapper {{
                width: 100% !important;
            }}
            .header, .content, .footer {{
                padding: 15px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <table class="email-wrapper" cellpadding="0" cellspacing="0">
            <!-- Header -->
            <tr>
                <td class="header">
                    <img src="https://cfautocare.biz/static/creatives/Logo.png" alt="CFAC Logo">
                    <h1 style="margin: 10px 0 0 0;">Order Update Notification</h1>
                </td>
            </tr>
            <!-- Body Content -->
            <tr>
                <td class="content">
                    <p>Hello {order.get('customer_name', 'Customer')},</p>
                    <p>Your technician is now on the way to complete the job.</p>
                    <p>If you have any questions, please contact your sales rep or visit our website.</p>
                </td>
            </tr>
            <!-- Footer -->
            <tr>
                <td class="footer">
                    &copy; {current_year} Centralfloridaautocare LLC. All rights reserved.
                </td>
            </tr>
        </table>
    </div>
</body>
</html>
"""
                send_postmark_email(guest_email, subject, text_body, html_body)
            else:
                current_app.logger.warning(f"Order {order_id} has no guest email; skipping email notification.")

        return jsonify({"message": "Order status updated successfully", "new_status": new_status}), 200
    except Exception as e:
        current_app.logger.error(f"Error updating order status for {order_id}: {str(e)}")
        return jsonify({"error": f"Error updating order status: {str(e)}"}), 500
































#Testing Push notis



import pymongo

@api_tech_bp.route("/register_device_token", methods=["POST"])
def register_device_token():
    data = request.get_json()
    if not data or "device_token" not in data:
        current_app.logger.error("No device token provided in the request.")
        return jsonify({"error": "No device token provided"}), 400

    device_token = data["device_token"]
    user_id = data.get("user_id")  # This is optional

    # Optional: Validate device_token format (e.g., length check)
    if not device_token or len(device_token) < 10:  # Example check; adjust as needed.
        current_app.logger.error("Invalid device token provided.")
        return jsonify({"error": "Invalid device token provided"}), 400

    current_app.logger.info(f"Received device token: {device_token} for user: {user_id}")

    try:
        # Retrieve the device_tokens collection.
        db = current_app.config.get('MONGO_CLIENT')
        if db is None:
            current_app.logger.error("Database connection not configured!")
            return jsonify({"error": "Database connection error"}), 500

        device_tokens_collection = db.device_tokens

        result = device_tokens_collection.insert_one({
            "device_token": device_token,
            "user_id": user_id,
            "created_at": datetime.utcnow()
        })
        current_app.logger.info(f"Inserted device token record with _id: {result.inserted_id}")
        return jsonify({"status": "success", "inserted_id": str(result.inserted_id)}), 201

    except pymongo.errors.PyMongoError as e:
        current_app.logger.error(f"Error inserting device token: {str(e)}")
        return jsonify({"error": "Database error", "details": str(e)}), 500

if __name__ == '__main__':
    current_app.run(debug=True)






from bson import ObjectId
def get_device_token_for_tech(tech_id):
    current_app.logger.info(f"Attempting to fetch device token for technician {tech_id} from the device_tokens collection.")
    device_tokens_collection = current_app.config.get('MONGO_CLIENT').device_tokens
    user_record = device_tokens_collection.find_one({"user_id": tech_id})
    if user_record and "device_token" in user_record:
        token = user_record["device_token"]
        current_app.logger.info(f"Device token retrieved for technician {tech_id}: {token}")
        return token
    else:
        current_app.logger.error(f"Device token not found for technician {tech_id}.")
        return None


def send_notification_to_tech(tech_id, order_id, threshold, device_token, custom_message=None):
    # Use the custom message if provided, otherwise use the default message.
    if custom_message:
        message = custom_message
    else:
        message = f"Order {order_id} is now within {threshold} hours of service!"
        
    current_app.logger.info(f"Preparing to send notification to technician {tech_id}: {message}")

    # Retrieve the base64-encoded certificate from the environment.
    cert_b64 = os.environ.get("APNS_CERT_B64")
    if not cert_b64:
        current_app.logger.error("APNS certificate not configured in environment variable!")
        return {"status": "error", "detail": "Certificate not set"}

    try:
        # Decode and write the certificate to a temporary file.
        cert_content = base64.b64decode(cert_b64)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as temp_cert:
            temp_cert.write(cert_content)
            temp_cert_path = temp_cert.name

        current_app.logger.info(f"Using APNS certificate at temporary file: {temp_cert_path}")

        # Create the APNs payload.
        payload = Payload(alert={"title": "Order Reminder", "body": message}, sound="default", badge=1)
        
        # Create an APNs client. In production, set use_sandbox=False.
        client = APNsClient(temp_cert_path, use_sandbox=True, use_alternative_port=False)
        response = client.send_notification(device_token, payload, topic="biz.cfautocare.cfactech")
        current_app.logger.info(f"Push notification response: {response}")

        # Clean up the temporary certificate file.
        os.remove(temp_cert_path)
        return {"status": "sent", "detail": str(response)}
    except Exception as e:
        current_app.logger.error(f"Error sending push notification: {str(e)}")
        return {"status": "error", "detail": str(e)}


from flask import current_app
from datetime import datetime
import pytz
from flask import current_app
from datetime import datetime
import pytz


def notify_techs_for_upcoming_orders():
    current_app.logger.info("notify_techs_for_upcoming_orders triggered")
    try:
        # Connect to your orders collection.
        orders_collection = current_app.config.get('MONGO_CLIENT').orders
        if orders_collection is None:
            current_app.logger.error("Orders collection not found in MONGO_CLIENT configuration!")
            return

        current_app.logger.info("Connected to the orders collection successfully.")

        # Set the current time to UTC.
        current_time = datetime.utcnow().replace(tzinfo=pytz.UTC)
        current_app.logger.info(f"Current UTC time set to: {current_time}")

        query = {"status": "ordered"}
        current_app.logger.info(f"Executing query: {query}")

        try:
            matching_count = orders_collection.count_documents(query)
            current_app.logger.info(
                f"Found {matching_count} orders scheduled in the future with status not 'completed'."
            )
        except Exception as count_error:
            current_app.logger.error(f"Error counting documents with query {query}: {str(count_error)}")
            return

        try:
            orders_cursor = orders_collection.find(query)
        except Exception as find_error:
            current_app.logger.error(f"Error executing find with query {query}: {str(find_error)}")
            return

        # Define the thresholds in hours.
        thresholds = [12, 6, 2, 1]

        for order in orders_cursor:
            try:
                # 1. Retrieve the order ID.
                order_id = str(order.get("_id", "unknown"))
                current_app.logger.info(f"Found order with _id: {order_id}")

                # 2. Convert the service_date to a datetime object.
                service_date = order.get('service_date')
                if not service_date:
                    current_app.logger.error(f"Order {order_id} is missing the 'service_date' field.")
                    continue

                if isinstance(service_date, str):
                    try:
                        service_date = datetime.fromisoformat(service_date)
                    except Exception as conv_err:
                        current_app.logger.error(
                            f"Error converting service_date for order {order_id}: {str(conv_err)}"
                        )
                        continue

                if service_date.tzinfo is None:
                    service_date = service_date.replace(tzinfo=pytz.UTC)
                else:
                    service_date = service_date.astimezone(pytz.UTC)
                current_app.logger.info(f"Order {order_id} service_date converted to UTC: {service_date}")

                # 3. Retrieve already-notified thresholds.
                notified_thresholds = order.get("notified_thresholds", [])
                current_app.logger.info(f"Order {order_id} already notified thresholds: {notified_thresholds}")

                # 4. Calculate hours remaining.
                time_diff = service_date - current_time
                hours_remaining = time_diff.total_seconds() / 3600
                current_app.logger.info(
                    f"Order {order_id} is scheduled for {service_date}. Hours remaining: {hours_remaining:.2f}"
                )

                # 5. Retrieve technician information.
                tech_id = order.get("technician")
                if not tech_id:
                    current_app.logger.error(f"Order {order_id} is missing the 'technician' field.")
                    continue
                current_app.logger.info(f"Order {order_id} is associated with technician ID: {tech_id}")

                # 6. Check each threshold.
                for threshold in thresholds:
                    if hours_remaining <= threshold and threshold not in notified_thresholds:
                        if threshold == 1:
                            # Use a custom message when the order is 1 hour away.
                            custom_message = "Update your order status and let the client know you're on the way!"
                        else:
                            custom_message = None  # Use the default message

                        current_app.logger.info(
                            f"Order {order_id} is within {threshold} hours. Sending push notification to technician {tech_id}."
                        )
                        
                        # Retrieve the technician's device token.
                        current_app.logger.info(f"Fetching device token for technician {tech_id}.")
                        device_token = get_device_token_for_tech(tech_id)
                        current_app.logger.info(f"Device token for technician {tech_id} is: {device_token}")
                        if not device_token:
                            current_app.logger.error("Device token not found, cannot send notification.")
                            continue  # Skip to next threshold or order
                        
                        push_response = send_notification_to_tech(
                            tech_id, 
                            order_id, 
                            threshold, 
                            device_token,
                            custom_message=custom_message
                        )
                        current_app.logger.info(f"Notification push response for order {order_id}: {push_response}")
                        
                        if push_response.get("status") == "sent":
                            try:
                                orders_collection.update_one(
                                    {"_id": order["_id"]},
                                    {"$push": {"notified_thresholds": threshold}}
                                )
                            except Exception as update_err:
                                current_app.logger.error(
                                    f"Error updating order {order_id} with notified threshold {threshold}: {str(update_err)}"
                                )
                        else:
                            current_app.logger.error(
                                f"Notification for threshold {threshold} failed for order {order_id}, will retry later."
                            )
            except Exception as order_error:
                current_app.logger.error(f"Error processing order: {str(order_error)}")
    except Exception as e:
        current_app.logger.error(f"Error in notify_techs_for_upcoming_orders: {str(e)}")



def fetch_upcoming_orders():
    # Get current UTC time
    current_time = datetime.utcnow().replace(tzinfo=pytz.utc)
    # Modify your query to also exclude orders with status 'completed'
    query = {
            "status": "ordered"  
    }
    
    orders_collection = current_app.config.get('MONGO_CLIENT').orders
    orders = orders_collection.find(query)
    orders_list = list(orders)
    current_app.logger.info(f"Found {len(orders_list)} orders scheduled in the future with status not 'completed'.")
    return orders_list





# Scheduler to run the notification check every 5 minutes
from apscheduler.schedulers.background import BackgroundScheduler


def start_scheduler(app):
    scheduler = BackgroundScheduler()
    
    # For testing: run every 3 minutes.
    scheduler.add_job(
        func=lambda: app.app_context().push() or notify_techs_for_upcoming_orders(),
        trigger="interval",
        minutes=30  # Change this to minutes=60 (or another interval) in production.
    )
    
    app.logger.info("Scheduler call started")  # Log a simple fixed message
    
    scheduler.start()
    app.logger.info("Starting the notification scheduler")
    
    # Ensure the scheduler shuts down when the app exits.
    import atexit
    atexit.register(lambda: scheduler.shutdown())
