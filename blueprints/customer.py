# blueprints/customer.py

from flask import (
    Blueprint, render_template, request, flash, redirect,
    url_for, session, current_app
)
from flask_login import login_required, current_user, login_user, logout_user
from bson.objectid import ObjectId
from datetime import datetime, timedelta
import stripe
import math
import logging
from flask import current_app
import pprint

from pymongo.errors import DuplicateKeyError

from extensions import bcrypt  # Import the initialized bcrypt instance
from decorators import customer_required
from forms import (
    CustomerLoginForm, RemoveFromCartForm, RegistrationForm,
    PasswordResetRequestForm, PasswordResetForm
)

# If you store your cart logic or other utilities (like calculate_cart_total) in a utils module:
from utility import calculate_cart_total  # Or remove if you do this differently

customer_bp = Blueprint('customer', __name__, url_prefix='/customer')

@customer_bp.route('/home') 
def customer_home():
    vehicle_sizes  = [
            {"display": "Coup 2 Seater", "value": "coupe_2_seater"},
            {"display": "Truck 2 Seater", "value": "truck_2_seater"},
            {"display": "Truck 4 Seater", "value": "truck_4_seater"},
            {"display": "Hatchback 2 Door", "value": "hatchback_2_door"},
            {"display": "Hatchback 4 Door", "value": "hatchback_4_door"},
            {"display": "Sedan 2 Door", "value": "sedan_2_door"},
            {"display": "Sedan 4 Door", "value": "sedan_4_door"},
            {"display": "SUV 4 Seater", "value": "suv_4_seater"},
            {"display": "SUV 6 Seater", "value": "suv_6_seater"},
            {"display": "Minivan 6 Seater", "value": "minivan_6_seater"}
    ]


    # Fetch services from the database
    services_collection = current_app.config['SERVICES_COLLECTION']
    services = list(services_collection.find({'active': True}))
    for service in services:
        service['_id'] = str(service['_id'])  # Convert ObjectId to string

    # Default image
    default_image = url_for('static', filename='default_service.jpg')

    return render_template('customer/home.html', services=services, vehicle_sizes=vehicle_sizes, default_image=default_image)
from notis import send_postmark_email

@customer_bp.route('/start_payment', methods=['POST'])
@login_required
@customer_required
def start_payment():
    current_app.logger.info("Starting payment process from cart.")
    
    # Check if the cart exists
    if 'cart' not in session or not session['cart']:
        current_app.logger.info("Cart is empty; redirecting to customer home.")
        flash('Your cart is empty.', 'info')
        return redirect(url_for('customer.customer_home'))
    
    # Retrieve necessary collections
    users_collection = current_app.config['USERS_COLLECTION']
    services_collection = current_app.config['SERVICES_COLLECTION']
    orders_collection = current_app.config['ORDERS_COLLECTION']
    
    # Fetch the user
    user_id = current_user.id
    current_app.logger.info("Fetching user with id: %s", user_id)
    user = users_collection.find_one({'_id': ObjectId(user_id)})
    if not user:
        current_app.logger.error("User not found for id: %s", user_id)
        flash('User not found.', 'danger')
        return redirect(url_for('customer.customer_home'))
    
    # Build services_in_cart and calculate totals/fees (similar to your checkout logic)
    total_estimated_minutes = 0
    services_in_cart = []
    for cart_item in session['cart']:
        try:
            service = services_collection.find_one({'_id': ObjectId(cart_item['service_id'])})
        except Exception as e:
            current_app.logger.error("Error fetching service with id %s: %s", cart_item.get('service_id'), e)
            continue
        if service:
            vehicle_size = cart_item.get('vehicle_size')
            price_info = service.get('price_by_vehicle_size', {}).get(vehicle_size, {})
            service['price'] = price_info.get('price', 0)
            completion_time_str = price_info.get('completion_time', '0 minutes')
            estimated_minutes = int(completion_time_str.split()[0]) if completion_time_str else 0
            total_estimated_minutes += estimated_minutes
            service['label'] = service.get('label') or service.get('name', 'Unnamed Service')
            services_in_cart.append(service)
    services_total = calculate_cart_total(services_in_cart)
    preliminary_final_total = services_total / 0.55
    fee = preliminary_final_total - services_total
    travel_fee = 35 if services_total < 60 else 0
    final_price = preliminary_final_total + travel_fee
    current_app.logger.info("Fee Calculations: Services Total: %s, Fee: %s, Travel Fee: %s, Final Price: %s",
                             services_total, fee, travel_fee, final_price)
    
    user_address = user.get('address', {})
    
    # Create the order record
    order = {
        'user': user_id,
        'selectedServices': [item["service_name"].lower().replace(" ", "_").replace("&", "and").replace("-", "_")
                             for item in session['cart']],
        'services_total': services_total,
        'final_price': final_price,
        'order_date': datetime.now(),
        'service_date': None,
        'service_time': None,
        'status': "ordered",
        'payment_time': request.form.get('payment_time'),  # "pay_now" or "after"
        'payment_status': 'pending',
        'address': user_address,
        'fee': fee,
        'travel_fee': travel_fee,
        'creation_date': datetime.utcnow(),
        'estimated_minutes': total_estimated_minutes,
        'email': user.get('email', ''),
        'full_name': user.get('name', ''),
        'phone_number': user.get('phone_number', ''),
        'vehicle_size': session['cart'][0]['vehicle_size'] if session['cart'] else None,
        'is_guest': False
    }
    
    current_app.logger.info("Creating order with data: %s", order)
    order_result = orders_collection.insert_one(order)
    order_id = str(order_result.inserted_id)
    current_app.logger.info("Order created with id: %s", order_id)
    
    # Set Stripe API key
    stripe.api_key = current_app.config.get('STRIPE_SECRET_KEY')
    if not stripe.api_key:
        current_app.logger.error("STRIPE_SECRET_KEY is missing in app.config")
        flash('Payment processing configuration error. Please try again later.', 'danger')
        return redirect(url_for('customer.cart'))
    
    payment_time = request.form.get('payment_time')
    
    # Option 1: Full payment now ("pay_now")
    if payment_time == 'pay_now':
        current_app.logger.info("Payment option 'Pay Now' selected.")
        try:
            total_amount = int(math.ceil(final_price * 100))  # in cents
            payment_intent = stripe.PaymentIntent.create(
                amount=total_amount,
                currency="usd",
                payment_method_types=["card"],
                metadata={"order_id": order_id, "payment_type": "full_payment"}
            )
            line_items = [{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": f"Order Payment for Order #{order_id}"},
                    "unit_amount": total_amount,
                },
                "quantity": 1,
            }]
            customer_email = user.get("email")
            success_url = url_for('customer.thank_you', _external=True)
            cancel_url = current_app.config.get("CHECKOUT_CANCEL_URL", "https://cfautocare.biz/payment_cancel")
            payment_intent_data = {"metadata": {"order_id": order_id, "payment_type": "full_payment"}}
            
            current_app.logger.debug("Creating Checkout Session for full payment with parameters: line_items=%s, customer_email=%s, success_url=%s, cancel_url=%s",
                                       line_items, customer_email, success_url, cancel_url)
            
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=line_items,
                customer_email=customer_email,
                success_url=success_url,
                cancel_url=cancel_url,
                payment_intent_data=payment_intent_data,
                mode="payment"
            )
            
            current_app.logger.info("Checkout session created successfully with URL: %s", checkout_session.url)
            
            # Update the order record with full payment info
            order.update({
                "payment_status": "pending",
                "client_secret": payment_intent.client_secret,
                "payment_intent_id": payment_intent.id,
                "checkout_url": checkout_session.url,
                "has_payment_collected": "no"
            })
            orders_collection.update_one({"_id": ObjectId(order_id)}, {"$set": order})
            current_app.logger.info("Stripe payment intent and checkout URL stored successfully.")
            current_app.logger.info("Redirecting to Stripe Checkout Session URL: %s", checkout_session.url)
            send_full_payment_thankyou_email(order)
            current_app.logger.info("Full payment thank-you email sent to: %s", user.get("email"))
        
            return redirect(checkout_session.url)
        except stripe.error.StripeError as e:
            current_app.logger.error("StripeError: %s", e)
            flash('Payment processing error. Please try again.', 'danger')
            return redirect(url_for('customer.cart'))
    
    # Option 2: Pay 45% now and 55% later ("after")
    # Option 2: Pay 45% now and 55% later ("after")
    elif payment_time == 'after':
        current_app.logger.info("Payment option 'After' selected: 45% deposit now, 55% remaining later.")
        try:
            # Calculate amounts (in cents)
            deposit_amount = int(math.ceil(final_price * 0.45 * 100))
            remaining_amount = int(math.ceil(final_price * 0.55 * 100))
            current_app.logger.info("Deposit amount: %s cents; Remaining amount: %s cents", deposit_amount, remaining_amount)
            
            # Create deposit PaymentIntent and Checkout Session (45%)
            deposit_payment_intent = stripe.PaymentIntent.create(
                amount=deposit_amount,
                currency="usd",
                payment_method_types=["card"],
                metadata={"order_id": order_id, "payment_type": "deposit"}
            )
            deposit_line_items = [{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": f"Deposit Payment for Order #{order_id}"},
                    "unit_amount": deposit_amount,
                },
                "quantity": 1,
            }]
            deposit_checkout_session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=deposit_line_items,
                customer_email=user.get("email"),
                success_url=url_for('customer.thank_you', _external=True),
                cancel_url=current_app.config.get("CHECKOUT_CANCEL_URL", "https://cfautocare.biz/payment_cancel"),
                payment_intent_data={"metadata": {"order_id": order_id, "payment_type": "deposit"}},
                mode="payment"
            )
            
            current_app.logger.info("Deposit checkout session created with URL: %s", deposit_checkout_session.url)
            
            # Create remaining PaymentIntent and Checkout Session (55%)
            remaining_payment_intent = stripe.PaymentIntent.create(
                amount=remaining_amount,
                currency="usd",
                payment_method_types=["card"],
                metadata={"order_id": order_id, "payment_type": "remaining"}
            )
            remaining_line_items = [{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": f"Remaining Payment for Order #{order_id}"},
                    "unit_amount": remaining_amount,
                },
                "quantity": 1,
            }]
            remaining_checkout_session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=remaining_line_items,
                customer_email=user.get("email"),
                success_url=url_for('customer.thank_you', _external=True),
                cancel_url=current_app.config.get("CHECKOUT_CANCEL_URL", "https://cfautocare.biz/payment_cancel"),
                payment_intent_data={"metadata": {"order_id": order_id, "payment_type": "remaining"}},
                mode="payment"
            )
            
            current_app.logger.info("Remaining checkout session created with URL: %s", remaining_checkout_session.url)
            
            # Update order with both payment intents and checkout URLs
            order.update({
                "deposit_payment_status": "pending",
                "deposit_client_secret": deposit_payment_intent.client_secret,
                "deposit_payment_intent_id": deposit_payment_intent.id,
                "deposit_checkout_url": deposit_checkout_session.url,
                "remaining_payment_status": "pending",
                "remaining_client_secret": remaining_payment_intent.client_secret,
                "remaining_payment_intent_id": remaining_payment_intent.id,
                "remaining_checkout_url": remaining_checkout_session.url,
            })
            orders_collection.update_one({"_id": ObjectId(order_id)}, {"$set": order})
            current_app.logger.info("Order updated with both deposit and remaining payment info.")
            
                    # Send the thank-you email for the down payment (partial payment)
            send_partial_payment_thankyou_email(order)
            # Send remaining payment link via email
            subject = "Your Remaining Balance Payment Link"
            to_email = user.get("email")
            sender_email = current_app.config.get("POSTMARK_SENDER_EMAIL")

            html_body = f"""
            <!DOCTYPE html>
            <html lang="en">
            <head>
            <meta charset="UTF-8">
            <title>Complete Your Payment</title>
            <style>
                body {{
                font-family: Arial, sans-serif;
                background-color: #f4f4f4;
                margin: 0;
                padding: 0;
                }}
                .container {{
                max-width: 600px;
                margin: 20px auto;
                background-color: #ffffff;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 3px rgba(0,0,0,0.1);
                }}
                .header {{
                text-align: center;
                padding-bottom: 20px;
                }}
                .header h2 {{
                color: #07173d;
                }}
                .content {{
                font-size: 16px;
                color: #333333;
                line-height: 1.5;
                }}
                .button {{
                display: inline-block;
                padding: 10px 20px;
                margin-top: 20px;
                background-color: #07173d;
                color: #ffffff;
                text-decoration: none;
                border-radius: 4px;
                }}
                .footer {{
                margin-top: 30px;
                font-size: 12px;
                color: #999999;
                text-align: center;
                }}
            </style>
            </head>
            <body>
            <div class="container">
                <div class="header">
                <h2>Complete Your Payment</h2>
                </div>
                <div class="content">
                <p>Dear {user.get("name")},</p>
                <p>Thank you for submitting your deposit for Order #{order_id}.</p>
                <p>Please click the button below to complete your remaining payment of 55%:</p>
                <p><a href="{remaining_checkout_session.url}" class="button">Pay Remaining Balance</a></p>
                <p>Thank you!</p>
                </div>
                <div class="footer">
                &copy; {datetime.now().year} Centralfloridaautocare LLC. All rights reserved.
                </div>
            </div>
            </body>
            </html>
            """

            text_body = (
                f"Dear {user.get('name')},\n\n"
                f"Thank you for submitting your deposit for Order #{order_id}.\n"
                f"Please use the following link to complete your remaining payment of 55% when ready:\n\n"
                f"{remaining_checkout_session.url}\n\n"
                "Thank you!"
            )

            # Send the email with the updated HTML content.
            send_postmark_email(
                subject=subject,
                to_email=to_email,
                from_email=sender_email,
                text_body=text_body,
                html_body=html_body
            )
            current_app.logger.info("Remaining payment link sent via email to: %s", to_email)

            # Redirect the customer to the deposit (45%) checkout session
            current_app.logger.info("Redirecting to Deposit Checkout Session URL: %s", deposit_checkout_session.url)
            return redirect(deposit_checkout_session.url)



        except stripe.error.StripeError as e:
            current_app.logger.error("StripeError: %s", e)
            flash('Payment processing error. Please try again.', 'danger')
            return redirect(url_for('customer.cart'))

    
    # If neither option is valid, redirect back
    else:
        flash("Invalid payment option selected.", "danger")
        return redirect(url_for('customer.cart'))






from datetime import datetime
from flask import render_template, current_app
from bson.objectid import ObjectId
from notis import send_postmark_email  # your email-sending helper

def send_full_payment_thankyou_email(order):
    """
    Sends a thank-you email for orders that were paid in full.
    """
    # Determine recipient from order data (adjust as needed)
    guest_email = order.get("guest_email") or order.get("email")
    if not guest_email:
        current_app.logger.error("No guest email found for full payment notification.")
        return

    customer_name = order.get("customer_name") or order.get("full_name", "Customer")
    order_id = str(order.get("_id", "N/A"))
    subject = "Thank You for Your Order - Payment Complete"

    # Render an HTML template (create templates/emails/full_payment_thankyou.html)
    html_body = render_template(
        "emails/full_payment_thankyou.html",
        order=order,
        customer_name=customer_name,
        order_id=order_id,
        current_year=datetime.now().year
    )

    text_body = (
        f"Dear {customer_name},\n\n"
        f"Thank you for your order #{order_id}. Your payment has been received in full.\n"
        "Please find your invoice attached below.\n\n"
        "Thank you!"
    )

    send_postmark_email(
        subject=subject,
        to_email=guest_email,
        from_email=current_app.config.get("POSTMARK_SENDER_EMAIL"),
        text_body=text_body,
        html_body=html_body
    )
    current_app.logger.info("Full payment thank-you email sent to: %s", guest_email)


def send_partial_payment_thankyou_email(order):
    """
    Sends a thank-you email for orders with a partial payment (deposit paid now,
    with remaining balance due later). The email shows both amounts.
    """
    guest_email = order.get("guest_email") or order.get("email")
    if not guest_email:
        current_app.logger.error("No guest email found for partial payment notification.")
        return

    customer_name = order.get("customer_name") or order.get("full_name", "Customer")
    order_id = str(order.get("_id", "N/A"))
    subject = "Thank You for Your Down Payment"

    # Calculate deposit and remaining amounts; adjust percentage as needed.
    final_price = float(order.get("final_price", 0))
    deposit_amount = final_price * 0.45
    remaining_amount = final_price * 0.55

    # Render an HTML template (create templates/emails/partial_payment_thankyou.html)
    html_body = render_template(
        "emails/partial_payment_thankyou.html",
        order=order,
        customer_name=customer_name,
        order_id=order_id,
        deposit_amount=f"{deposit_amount:.2f}",
        remaining_amount=f"{remaining_amount:.2f}",
        current_year=datetime.now().year
    )

    text_body = (
        f"Dear {customer_name},\n\n"
        f"Thank you for submitting your down payment for Order #{order_id}.\n"
        f"You have paid ${deposit_amount:.2f}. Your remaining balance is ${remaining_amount:.2f}.\n\n"
        "Please complete your remaining payment when you're ready.\n\n"
        "Thank you!"
    )

    send_postmark_email(
        subject=subject,
        to_email=guest_email,
        from_email=current_app.config.get("POSTMARK_SENDER_EMAIL"),
        text_body=text_body,
        html_body=html_body
    )
    current_app.logger.info("Partial payment thank-you email sent to: %s", guest_email)






@customer_bp.route('/cart', methods=['GET', 'POST'])
@customer_required
def cart():
    if 'cart' not in session or not session['cart']:
        flash('Your cart is empty.', 'info')
        return render_template('customer/cart.html', services=[], forms={}, user_address=None)

    users_collection = current_app.config['USERS_COLLECTION']
    services_collection = current_app.config['SERVICES_COLLECTION']

    services_in_cart = []
    for item in session['cart']:
        service = services_collection.find_one({'_id': ObjectId(item['service_id'])})
        current_app.logger.debug("Fetched service from DB for service_id %s: %s", item['service_id'], service)
        if service:
            # Convert ObjectId to string for template use
            service['_id'] = str(service['_id'])
            vehicle_size = item.get('vehicle_size')
            price_info = service.get('price_by_vehicle_size', {}).get(vehicle_size, {})
            service['price'] = price_info.get('price', 0)
            current_app.logger.debug(
                "Computed price for service '%s' (vehicle_size: %s): %s", 
                service.get('label', service.get('name', 'Unnamed Service')), vehicle_size, service['price']
            )
            services_in_cart.append(service)
        else:
            current_app.logger.warning("No service found for service_id: %s", item.get('service_id'))

    # Log the complete list of services in the cart
    current_app.logger.debug("Final services_in_cart list: %s", pprint.pformat(services_in_cart))
    
    # Calculate totals and fees
    services_total = calculate_cart_total(services_in_cart)
    preliminary_final_total = services_total / 0.55
    fee = preliminary_final_total - services_total
    travel_fee = 35 if services_total < 60 else 0
    final_total = preliminary_final_total + travel_fee
    
    # Log the computed totals
    current_app.logger.info(
        "Invoice Summary - Services Total: %s, Fee: %s, Travel Fee: %s, Final Total: %s",
        services_total, fee, travel_fee, final_total
    )
    
    # Build forms for each service
    forms = {}
    for service in services_in_cart:
        form = RemoveFromCartForm()
        form.service_id.data = service['_id']  # already a string
        forms[service['_id']] = form

    user = users_collection.find_one({'_id': ObjectId(current_user.id)})
    user_address = user.get('address') if user and 'address' in user else None
    
    # Log data that will be sent to the template
    current_app.logger.debug("Rendering cart template with: services_in_cart=%s, total=%s, fee=%s, travel_fee=%s, final_total=%s, user_address=%s",
                               pprint.pformat(services_in_cart), services_total, fee, travel_fee, final_total, user_address)
    
    return render_template(
        'customer/cart.html',
        services=services_in_cart,
        total=services_total,   # Services total
        fee=fee,      
        travel_fee=travel_fee,  # Travel Fee (if applicable)
        final_total=final_total,
        forms=forms,
        user_address=user_address
    )




from bson import ObjectId

@customer_bp.route('/add_to_cart', methods=['GET'])
@customer_required
def add_to_cart_get():
    """
    Adds multiple services to the user's cart via GET parameters,
    then redirects to the cart page.
    """
    try:
        # Extract parameters and log them
        service_ids = request.args.get('service_id')  # Can be a comma-separated list
        vehicle_size = request.args.get('vehicle_size')
        service_date = request.args.get('service_date')

        current_app.logger.info(
            f"Received request to add to cart: service_id={service_ids}, vehicle_size={vehicle_size}, service_date={service_date}"
        )

        if not service_ids:
            flash("No service_id provided.", "warning")
            current_app.logger.warning("No service_id provided in the request.")
            return redirect(url_for('customer.customer_home'))

        # Split service_ids and attempt to convert them to ObjectIds
        try:
            service_id_list = service_ids.split(",")
            object_id_list = [ObjectId(service_id.strip()) for service_id in service_id_list]
            current_app.logger.info(f"Converted service IDs to ObjectIds: {object_id_list}")
        except Exception as e:
            current_app.logger.error(f"Invalid ObjectId format: {service_ids} - Error: {e}")
            flash("Invalid service ID format.", "danger")
            return redirect(url_for('customer.customer_home'))

        # Fetch services from the database
        services_collection = current_app.config['SERVICES_COLLECTION']
        services = list(services_collection.find({"_id": {"$in": object_id_list}}))
        current_app.logger.info(f"Fetched services from DB: {services}")

        if not services:
            flash("Selected services not found.", "danger")
            current_app.logger.error(f"No services found in DB for IDs: {object_id_list}")
            return redirect(url_for('customer.customer_home'))

        # Ensure session cart exists
        if 'cart' not in session:
            session['cart'] = []

        # Normalize vehicle_size for price lookup
        normalized_vehicle_size = vehicle_size.lower().replace(" ", "_")
        current_app.logger.info(f"Normalized vehicle_size: '{vehicle_size}' -> '{normalized_vehicle_size}'")

        # Add each service to the cart if not already present
        for service in services:
            # Log the price details for debugging
            price_details = service.get('price_by_vehicle_size', {})
            current_app.logger.debug(
                f"Price details for service '{service.get('label', 'Unnamed Service')}': {price_details}"
            )
            
            # Attempt to retrieve the price detail using the normalized vehicle_size
            selected_price_detail = price_details.get(normalized_vehicle_size)
            if selected_price_detail is None:
                current_app.logger.error(
                    f"Price detail not found for normalized vehicle_size '{normalized_vehicle_size}' "
                    f"(original: '{vehicle_size}') in service '{service.get('label', 'Unnamed Service')}'. "
                    f"Available keys: {list(price_details.keys())}"
                )
            else:
                current_app.logger.info(
                    f"Found price detail for service '{service.get('label', 'Unnamed Service')}' and normalized "
                    f"vehicle_size '{normalized_vehicle_size}': {selected_price_detail}"
                )

            # Create the cart item (including price if available)
            cart_item = {
                "service_id": str(service["_id"]),
                "service_name": service.get("label", "Unnamed Service"),
                "vehicle_size": normalized_vehicle_size,  # store normalized value in the cart
                "service_date": service_date,
                "price": selected_price_detail.get("price") if selected_price_detail else None
            }

            already_in_cart = any(
                item["service_id"] == str(service["_id"]) and item["vehicle_size"] == normalized_vehicle_size
                for item in session['cart']
            )

            if not already_in_cart:
                session['cart'].append(cart_item)
                flash(f"Added {service.get('label', 'Service')} to your cart.", 'success')
                current_app.logger.info(f"Added {service.get('label', 'Service')} to cart with item details: {cart_item}")
            else:
                flash(f"{service.get('label', 'Service')} is already in your cart.", 'info')
                current_app.logger.info(f"{service.get('label', 'Service')} is already in the cart.")

        return redirect(url_for('customer.cart'))

    except Exception as e:
        current_app.logger.error(f"Unexpected error adding service to cart: {e}", exc_info=True)
        flash('An error occurred while adding services to your cart.', 'danger')
        return redirect(url_for('customer.customer_home'))




@customer_bp.errorhandler(Exception)
def handle_exception(e):
    current_app.logger.error("Unhandled exception: %s", e)
    flash("An unexpected error occurred.", "danger")
    return render_template('error.html', error=e), 500


@customer_bp.route('/thank_you')
@login_required
def thank_you():
    current_app.logger.info("Thank you page requested.")
    try:
        # Optionally log any session or order details you need.
        current_app.logger.debug("Session details: %s", session)
        return render_template('customer/thank_you.html')
    except Exception as e:
        current_app.logger.error("Error rendering thank you page: %s", e)
        flash("An error occurred while loading the thank you page.", "danger")
        return redirect(url_for('customer.customer_home'))

@customer_bp.route('/login', methods=['GET', 'POST'])
def customer_login():
    """
    Handles customer login via email or phone. 
    """
    from forms import CustomerLoginForm  # Or import at top
    users_collection = current_app.config['USERS_COLLECTION']

    form = CustomerLoginForm()
    if form.validate_on_submit():
        login_method = form.login_method.data
        password = form.password.data
        user = None

        if login_method == 'email':
            email = form.email.data.lower().strip()
            user = users_collection.find_one({'email': email, 'user_type': 'customer'})
        elif login_method == 'phone':
            phone_number = ''.join(filter(str.isdigit, form.phone_number.data)) if form.phone_number.data else None
            if phone_number:
                user = users_collection.find_one({'phone_number': phone_number, 'user_type': 'customer'})

        if user:
            from extensions import User  # Your custom Flask-Login user model
            try:
                if bcrypt.check_password_hash(user['password'], password):
                    user_obj = User(str(user['_id']), user['user_type'])
                    login_user(user_obj)
                    flash('Logged in successfully as customer.', 'success')
                    next_page = request.args.get('next')
                    return redirect(next_page or url_for('customer.customer_home'))
                else:
                    flash('Invalid credentials. Please try again.', 'danger')
            except ValueError:
                flash('Your account has an invalid password format. Please reset your password.', 'danger')
                return redirect(url_for('customer.reset_password_request'))
        else:
            flash('Invalid credentials. Please try again.', 'danger')

    return render_template('customer/login.html', form=form)




@customer_bp.route('/my_orders')
@customer_required
def my_orders():
    """
    Displays the current user's orders (including guest orders that match the user's email or phone),
    converting date strings to datetime objects so they can be formatted consistently.
    """
    users_collection = current_app.config['USERS_COLLECTION']
    orders_collection = current_app.config['ORDERS_COLLECTION']
    services_collection = current_app.config['SERVICES_COLLECTION']

    user_id = current_user.id
    user = users_collection.find_one({'_id': ObjectId(user_id)})
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('customer.customer_home'))

    # Build a query that returns orders belonging to the user or guest orders where the guest email
    # or phone number matches the current user's details.
    query = {
        "$or": [
            {"user": str(user_id)},
            {"$and": [
                {"is_guest": True},
                {"$or": [
                    {"guest_email": user.get("email")},
                    {"guest_phone_number": user.get("phone_number")}
                ]}
            ]}
        ]
    }
    user_orders = list(orders_collection.find(query).sort('order_date', -1))

    # Convert date strings to datetime objects (if necessary) so they can be formatted in the template.
    date_fields = ['creation_date', 'order_date', 'service_date']
    for order in user_orders:
        for field in date_fields:
            date_value = order.get(field)
            if date_value and isinstance(date_value, str):
                try:
                    # Replace trailing 'Z' with '+00:00' for ISO compatibility if necessary.
                    if date_value.endswith('Z'):
                        order[field] = datetime.fromisoformat(date_value.replace("Z", "+00:00"))
                    else:
                        order[field] = datetime.fromisoformat(date_value)
                except Exception as e:
                    current_app.logger.error(
                        f"Error converting {field} for order {order.get('_id')}: {date_value} - {e}"
                    )
                    order[field] = None

        # Build service details for display.
        order['service_details'] = []
        for item in order.get('services', []):
            service = services_collection.find_one({'_id': ObjectId(item['service_id'])})
            if service:
                # If you need to display a per-service price, adjust here.
                # Otherwise, you can simply include the service info.
                service['price'] = item.get('final_price', 0)
                order['service_details'].append(service)

        # Add a human-friendly technician name (if scheduled) or a default text.
        if order.get('status', '').lower() == 'scheduled' and order.get('scheduled_by'):
            tech_user = users_collection.find_one({'username': order['scheduled_by']})
            order['scheduled_by_name'] = tech_user.get('name', 'Technician') if tech_user else 'Technician'
        else:
            order['scheduled_by_name'] = 'Not scheduled yet'

    return render_template('customer/my_orders.html', orders=user_orders)




@customer_bp.route('/register', methods=['GET', 'POST'])
def register():
    """
    Handles new customer registration with email as required and phone number as optional.
    """
    users_collection = current_app.config['USERS_COLLECTION']
    form = RegistrationForm()

    if form.validate_on_submit():
        name = form.name.data.strip()
        email = form.email.data.lower().strip()
        phone_number = ''.join(filter(str.isdigit, form.phone_number.data)) if form.phone_number.data else None
        password = form.password.data
        unit_apt = form.unit_apt.data.strip() if form.unit_apt.data else ''
        city = form.city.data.strip()
        country = form.country.data.strip()
        zip_code = form.zip_code.data.strip()
        sms_opt_in = form.sms_opt_in.data

        # Use the globally initialized bcrypt to hash the password
        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')

        user_doc = {
            'name': name,
            'email': email,
            # 'phone_number' is conditionally added below
            'password': hashed_pw,
            'address': {
                'street_address': form.street_address.data.strip(),
                'unit_apt': unit_apt,
                'city': city,
                'country': country,
                'zip_code': zip_code
            },
            'user_type': 'customer',
            'created_at': datetime.utcnow(),
            'sms_opt_in': sms_opt_in
        }

        if phone_number:
            user_doc['phone_number'] = phone_number

        try:
            # Insert the new user
            users_collection.insert_one(user_doc)
            flash('Account created successfully! Please log in.', 'success')
            return redirect(url_for('customer.customer_login'))

        except DuplicateKeyError as e:
            current_app.logger.error(f"DuplicateKeyError during registration: {e.details}")
            flash('A user with the provided email or phone number already exists.', 'danger')
            return redirect(url_for('customer.register'))

        except Exception as e:
            current_app.logger.error(f"Error creating user: {e}")
            flash('An error occurred while creating your account. Please try again.', 'danger')
            return redirect(url_for('customer.register'))

    return render_template('customer/register.html', form=form)


@customer_bp.route('/reset_password', methods=['GET', 'POST'])
def reset_password_request():
    """
    Initiates the password reset request for a customer (sends email).
    """
    users_collection = current_app.config['USERS_COLLECTION']
    from forms import PasswordResetRequestForm
    form = PasswordResetRequestForm()

    if form.validate_on_submit():
        email = form.email.data.lower().strip()
        user = users_collection.find_one({
            'email': email,
            'user_type': 'customer'
        })
        if user:
            from itsdangerous import URLSafeTimedSerializer, SignatureExpired
            s = URLSafeTimedSerializer(current_app.secret_key)
            token = s.dumps(user['email'], salt='password-reset-salt')
            reset_url = url_for('customer.reset_password', token=token, _external=True)

            # If you have a configured mail object:
            from flask_mail import Message
            msg = Message('Password Reset Request', recipients=[user['email']])
            msg.body = f'Please click the link to reset your password: {reset_url}'
            current_app.mail.send(msg)

            flash('A password reset link has been sent to your email.', 'info')
            return redirect(url_for('customer.customer_login'))
        else:
            flash('Email not found.', 'danger')

    return render_template('customer/reset_password_request.html', form=form)


@customer_bp.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """
    Completes the password reset process using a secure token.
    """
    users_collection = current_app.config['USERS_COLLECTION']
    from forms import PasswordResetForm
    from itsdangerous import URLSafeTimedSerializer, SignatureExpired

    s = URLSafeTimedSerializer(current_app.secret_key)
    try:
        email = s.loads(token, salt='password-reset-salt', max_age=3600)
    except SignatureExpired:
        flash('The password reset link has expired.', 'danger')
        return redirect(url_for('customer.reset_password_request'))

    form = PasswordResetForm()
    if form.validate_on_submit():
        user = users_collection.find_one({'email': email, 'user_type': 'customer'})
        if user:
            # Use the globally initialized bcrypt to hash the new password
            hashed_pw = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
            users_collection.update_one(
                {'_id': user['_id']},
                {'$set': {'password': hashed_pw}}
            )
            flash('Your password has been updated!', 'success')
            return redirect(url_for('customer.customer_login'))
        else:
            flash('User not found.', 'danger')
            return redirect(url_for('customer.reset_password_request'))

    return render_template('customer/reset_password.html', form=form)




@customer_bp.route('/view_order/<order_id>')
@login_required
def view_order(order_id):
    from bson.objectid import ObjectId
    orders_collection = current_app.config['ORDERS_COLLECTION']
    services_collection = current_app.config['SERVICES_COLLECTION']
    
    try:
        order = orders_collection.find_one({'_id': ObjectId(order_id)})
    except Exception as e:
        flash("Invalid order ID.", "danger")
        return redirect(url_for('customer.my_orders'))
    
    if not order:
        flash("Order not found.", "danger")
        return redirect(url_for('customer.my_orders'))
    
    # If the order has a "selectedServices" array of service keys,
    # look up the full service details.
    selected_keys = order.get("selectedServices", [])
    if selected_keys:
        # Query services collection for matching keys.
        services_cursor = services_collection.find({"key": {"$in": selected_keys}})
        services = list(services_cursor)
        # Optional: Order the results to match the order in selected_keys.
        service_map = {service["key"]: service for service in services}
        order["services"] = [service_map[key] for key in selected_keys if key in service_map]
    else:
        order["services"] = []
    
    return render_template('customer/view_order.html', order=order)
