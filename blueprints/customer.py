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
        if service:
            # Convert ObjectId to string
            service['_id'] = str(service['_id'])
            vehicle_size = item.get('vehicle_size')
            price_info = service.get('price_by_vehicle_size', {}).get(vehicle_size, {})
            service['price'] = price_info.get('price', 0)
            services_in_cart.append(service)

    # Calculate services total
    services_total = calculate_cart_total(services_in_cart)
    
    # Calculate  fee so that services_total represents 55% of the order.
    preliminary_final_total = services_total / 0.55
    fee = preliminary_final_total - services_total
    
    # Apply a $35 travel fee if services_total is under $60.
    travel_fee = 35 if services_total < 60 else 0
    
    # Final total includes services total,  fee, and travel fee.
    final_total = preliminary_final_total + travel_fee

    # Build forms for each service
    forms = {}
    for service in services_in_cart:
        form = RemoveFromCartForm()
        form.service_id.data = service['_id']  # already a string
        forms[service['_id']] = form

    user = users_collection.find_one({'_id': ObjectId(current_user.id)})
    user_address = user.get('address') if user and 'address' in user else None

    if request.method == 'POST':
        service_id = request.form.get('service_id')
        if service_id in [item['service_id'] for item in session.get('cart', [])]:
            session['cart'] = [item for item in session['cart'] if item['service_id'] != service_id]
            flash('Item removed from your cart.', 'success')
        else:
            flash('Item not found in your cart.', 'warning')
        return redirect(url_for('customer.cart'))

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




@customer_bp.route('/checkout', methods=['GET', 'POST'])
@login_required
@customer_required
def checkout():
    """
    Checkout route—creates an order using the final price (services total plus fees)
    and then, if the customer selects “Pay Now,” creates a Stripe PaymentIntent.
    The fees are calculated as in the cart page.
    """
    current_app.logger.info("Checkout route called. Request method: %s", request.method)
    
    if 'cart' not in session or not session['cart']:
        current_app.logger.info("Cart is empty; redirecting to customer home.")
        flash('Your cart is empty.', 'info')
        return redirect(url_for('customer.customer_home'))
    
    current_app.logger.debug("Session cart contents: %s", session.get('cart'))
    
    users_collection = current_app.config['USERS_COLLECTION']
    services_collection = current_app.config['SERVICES_COLLECTION']
    orders_collection = current_app.config['ORDERS_COLLECTION']
    
    user_id = current_user.id
    current_app.logger.info("Fetching user with id: %s", user_id)
    user = users_collection.find_one({'_id': ObjectId(user_id)})
    if not user:
        current_app.logger.error("User not found for id: %s", user_id)
        flash('User not found.', 'danger')
        return redirect(url_for('customer.customer_home'))
    current_app.logger.debug("User data: %s", user)
    
    # Initialize total estimated completion time
    total_estimated_minutes = 0

    # Build the services_in_cart with correct 'price' and estimated time
    services_in_cart = []
    for cart_item in session['cart']:
        current_app.logger.debug("Processing cart item: %s", cart_item)
        try:
            service = services_collection.find_one({'_id': ObjectId(cart_item['service_id'])})
        except Exception as e:
            current_app.logger.error("Error fetching service with id %s: %s", cart_item.get('service_id'), e)
            continue

        if service:
            vehicle_size = cart_item.get('vehicle_size')
            price_info = service.get('price_by_vehicle_size', {}).get(vehicle_size, {})
            
            # Get price and estimated completion time
            service['price'] = price_info.get('price', 0)
            completion_time_str = price_info.get('completion_time', '0 minutes')

            # Extract numeric value from completion time (e.g., "15 minutes" → 15)
            estimated_minutes = int(completion_time_str.split()[0]) if completion_time_str else 0
            total_estimated_minutes += estimated_minutes  # Add to total

            service['label'] = service.get('label') or service.get('name', 'Unnamed Service')
            services_in_cart.append(service)
            current_app.logger.debug("Added service: %s", service)
        else:
            current_app.logger.warning("Service not found for id: %s", cart_item.get('service_id'))

    # Log the total estimated minutes
    current_app.logger.info("Total estimated completion time: %s minutes", total_estimated_minutes)

    # Calculate services total using your helper function.
    services_total = calculate_cart_total(services_in_cart)
    current_app.logger.info("Calculated services total: %s", services_total)
    
    # --- Fee Calculations (same as in your cart page) ---
    # Preliminary final total such that services_total represents 55% of it.
    preliminary_final_total = services_total / 0.55
    #  fee is the difference between the preliminary total and the services total.
    fee = preliminary_final_total - services_total
    # Apply a $35 travel fee if services_total is under $60; otherwise, no travel fee.
    travel_fee = 35 if services_total < 60 else 0
    # Final price is the sum of the preliminary total and the travel fee.
    final_price = preliminary_final_total + travel_fee
    current_app.logger.info("Fee Calculations: Services Total: %s,  Fee: %s, Travel Fee: %s, Final Price: %s",
                              services_total, fee, travel_fee, final_price)
    # --- End Fee Calculations ---
    
    user_address = user.get('address') if user else None
    current_app.logger.debug("User address: %s", user_address)
    
    if request.method == 'POST':
        current_app.logger.info("POST request received on checkout.")
        # Get the service date, time, and payment option from the form.
        service_date_str = request.form.get('service_date')
        service_time_str = request.form.get('service_time')
        payment_time = request.form.get('payment_time')  # expected to be 'now' or 'after'
        current_app.logger.info("Form data received: service_date=%s, service_time=%s, payment_time=%s", 
                                service_date_str, service_time_str, payment_time)
        
        if not service_date_str or not service_time_str or not payment_time:
            current_app.logger.warning("Missing required form data.")
            flash('Missing required information.', 'danger')
            return redirect(url_for('customer.checkout'))
        
        # Parse the date and time from form input.
        try:
            service_date = datetime.strptime(service_date_str, '%Y-%m-%d').date()
            service_time = datetime.strptime(service_time_str, '%H:%M').time()
            service_datetime = datetime.combine(service_date, service_time)
            current_app.logger.info("Parsed service datetime: %s", service_datetime)
        except ValueError as ve:
            current_app.logger.error("Error parsing service date/time: %s", ve)
            flash('Invalid date or time format.', 'danger')
            return redirect(url_for('customer.checkout'))
        # Normalize service names into a JSON-friendly format
        def format_service_name(service_name):
            return service_name.lower().replace(" ", "_").replace("&", "and").replace("-", "_")


        # Create the order in the database using the final price.
        order = {
            'user': current_user.id,
            'selectedServices': [format_service_name(item["service_name"]) for item in session['cart']],
            'services_total': services_total,
            'final_price': final_price,
            'order_date': datetime.now(),
            'service_date': service_datetime,
            'service_time': service_time_str,
            'payment_time': payment_time,
            'payment_status': 'pending',  # default for "Pay After Completion"
            'address': user.get('address', {}),
            'fee': fee,
            'travel_fee': travel_fee,
            'creation_date': datetime.utcnow(),
            'estimated_minutes': total_estimated_minutes  # NEW FIELD

        }
        current_app.logger.info("Creating order with data: %s", order)
        order_result = orders_collection.insert_one(order)
        order_id = str(order_result.inserted_id)
        current_app.logger.info("Order created with id: %s", order_id)
        
        # If "Pay Now" is selected, create a Stripe PaymentIntent.
        if payment_time == 'now':
            current_app.logger.info("Payment option 'Pay Now' selected.")
            payment_method_id = request.form.get('payment_method_id')
            if not payment_method_id:
                current_app.logger.info("No payment_method_id provided; re-rendering checkout page with card input form.")
                flash('Please enter your card details to proceed with payment.', 'info')
                return render_template(
                    'customer/checkout.html',
                    selectedServices=services_in_cart,
                    final_price=final_price,
                    services_total=services_total,
                    fee=fee,
                    travel_fee=travel_fee,
                    user_address=user_address,
                    default_service_date=service_date_str,
                    stripe_publishable_key=current_app.config['STRIPE_PUBLISHABLE_KEY'],
                    order_id=order_id
                )
            
            current_app.logger.debug("Payment method id received: %s", payment_method_id)
            stripe.api_key = current_app.config.get('STRIPE_SECRET_KEY')
            if not stripe.api_key:
                current_app.logger.error("STRIPE_SECRET_KEY is missing in app.config")
                flash('Payment processing configuration error. Please try again later.', 'danger')
                return redirect(url_for('customer.checkout'))
            
            try:
                current_app.logger.info("Creating Stripe PaymentIntent for final_price %s (amount in cents: %s)", 
                                          final_price, int(math.ceil(final_price * 100)))
                intent = stripe.PaymentIntent.create(
                    amount=int(math.ceil(final_price * 100)),  # amount in cents
                    currency='usd',
                    payment_method=payment_method_id,
                    confirmation_method='manual',
                    confirm=True,
                    metadata={'order_id': order_id},
                    return_url=url_for('customer.my_orders', _external=True)
                )
                current_app.logger.info("Stripe PaymentIntent created with status: %s", intent.status)
                
                if intent.status == 'requires_action' and intent.next_action.type == 'use_stripe_sdk':
                    current_app.logger.info("Payment requires additional authentication.")
                    flash('Additional authentication required. Please complete the payment.', 'warning')
                    return redirect(intent.next_action.use_stripe_sdk.stripe_js)
                elif intent.status == 'succeeded':
                    current_app.logger.info("PaymentIntent succeeded. Updating order payment status to 'paid'.")
                    orders_collection.update_one({'_id': ObjectId(order_id)}, {'$set': {'payment_status': 'paid'}})
                else:
                    current_app.logger.error("Unexpected PaymentIntent status: %s", intent.status)
                    flash('Something went wrong with your payment. Please try again.', 'danger')
                    return redirect(url_for('customer.checkout'))
            except stripe.error.CardError as e:
                current_app.logger.error("Stripe CardError: %s", e.user_message)
                flash(f"Card error: {e.user_message}", 'danger')
                return redirect(url_for('customer.checkout'))
            except stripe.error.StripeError as e:
                current_app.logger.error("StripeError: %s", e)
                flash('Payment processing error. Please try again.', 'danger')
                return redirect(url_for('customer.checkout'))
            except Exception as e:
                current_app.logger.exception("Unexpected error during Stripe PaymentIntent creation: %s", e)
                flash('An unexpected error occurred. Please try again.', 'danger')
                return redirect(url_for('customer.checkout'))
        else:
            current_app.logger.info("Payment option 'Pay After Completion' selected; no immediate payment required.")
        
        flash('Your order has been placed successfully!', 'success')
        session.pop('cart', None)
        current_app.logger.info("Order processed. Redirecting to my_orders.")
        return redirect(url_for('customer.my_orders'))
    
    # For GET requests, set default service date to tomorrow.
    default_service_date = (datetime.today() + timedelta(days=1)).strftime('%Y-%m-%d')
    current_app.logger.info("Default service date for template set to: %s", default_service_date)
    current_app.logger.info("Rendering checkout template with final_price: %s", final_price)
    
    return render_template(
        'customer/checkout.html',
        selectedServices=services_in_cart,
        final_price=final_price,
        services_total=services_total,
        fee=fee,
        travel_fee=travel_fee,
        user_address=user_address,
        default_service_date=default_service_date,
        stripe_publishable_key=current_app.config['STRIPE_PUBLISHABLE_KEY']
    )





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
