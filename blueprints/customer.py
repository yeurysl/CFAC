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

    return render_template('home.html', services=services, vehicle_sizes=vehicle_sizes, default_image=default_image)




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

    # -- Missing line: Calculate the total cost
    total = calculate_cart_total(services_in_cart)

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
        total=total,  # Make sure you pass it here
        forms=forms,
        user_address=user_address
    )


@customer_bp.route('/add_to_cart', methods=['GET'])
@customer_required
def add_to_cart_get():
    """
    Adds a service to the user's cart via GET parameters,
    then redirects to the cart page.
    """
    try:
        # Extract query parameters
        service_id = request.args.get('service_id')
        vehicle_size = request.args.get('vehicle_size')
        appointment = request.args.get('appointment')

        if not service_id:
            flash("No service_id provided.", "warning")
            return redirect(url_for('customer.customer_home'))

        # Fetch the service from DB if needed
        services_collection = current_app.config['SERVICES_COLLECTION']
        service = services_collection.find_one({'_id': ObjectId(service_id)})
        if not service:
            flash("Service not found.", "danger")
            return redirect(url_for('customer.customer_home'))

        # Add item(s) to the session cart
        # Session cart could be a list of service_ids or a list of dicts
        if 'cart' not in session:
            session['cart'] = []

        # Example: store more than just service_id in the cart
        cart_item = {
            "service_id": service_id,
            "service_name": service.get('label', 'Unnamed Service'),
            "vehicle_size": vehicle_size,
            "appointment": appointment
        }

        # Add the item if it's not already in the cart
        # or you could just append duplicates if desired
        already_in_cart = any(
            item["service_id"] == service_id and item["vehicle_size"] == vehicle_size 
            for item in session['cart']
        )
        if not already_in_cart:
            session['cart'].append(cart_item)
            flash(f"Added {service.get('label', 'Service')} to your cart.", 'success')
        else:
            flash("Item is already in your cart.", 'info')

        return redirect(url_for('customer.cart'))
    
    except Exception as e:
        current_app.logger.error(f"Error adding service to cart: {e}")
        flash('An error occurred while adding the service to your cart.', 'danger')
        return redirect(url_for('customer.customer_home'))






# blueprints/customer.py

@customer_bp.route('/checkout', methods=['GET', 'POST'])
@login_required
@customer_required
def checkout():
    """
    Checkout route—handles scheduling and payment method selection for services.
    """
    if 'cart' not in session or not session['cart']:
        flash('Your cart is empty.', 'info')
        return redirect(url_for('customer.customer_home'))

    users_collection = current_app.config['USERS_COLLECTION']
    services_collection = current_app.config['SERVICES_COLLECTION']
    orders_collection = current_app.config['ORDERS_COLLECTION']

    user_id = current_user.id
    user = users_collection.find_one({'_id': ObjectId(user_id)})
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('customer.customer_home'))

    # Build the services_in_cart with correct 'price' for each service
    services_in_cart = []
    for cart_item in session['cart']:
        service = services_collection.find_one({'_id': ObjectId(cart_item['service_id'])})
        if service:
            vehicle_size = cart_item.get('vehicle_size')
            price_info = service.get('price_by_vehicle_size', {}).get(vehicle_size, {})
            service['price'] = price_info.get('price', 0)
            service['label'] = service.get('label') or service.get('label', 'Unnamed Service')
            services_in_cart.append(service)

    # Calculate total
    total = calculate_cart_total(services_in_cart)

    user_address = user.get('address') if user else None

    if request.method == 'POST':
        # Handle date, time, and Stripe payment
        service_date_str = request.form.get('service_date')
        service_time_str = request.form.get('service_time')
        payment_method_id = request.form.get('payment_method_id')

        if not service_date_str or not service_time_str or not payment_method_id:
            flash('Missing required information.', 'danger')
            return redirect(url_for('customer.checkout'))

        # Parse the date and time
        try:
            service_date = datetime.strptime(service_date_str, '%Y-%m-%d').date()
            service_time = datetime.strptime(service_time_str, '%H:%M').time()
            service_datetime = datetime.combine(service_date, service_time)
        except ValueError as ve:
            flash('Invalid date or time format.', 'danger')
            return redirect(url_for('customer.checkout'))

        # Initialize Stripe with your secret key
        stripe.api_key = current_app.config.get('STRIPE_SECRET_KEY')
        if not stripe.api_key:
            current_app.logger.error("STRIPE_SECRET_KEY is missing in app.config")
            flash('Payment processing configuration error. Please try again later.', 'danger')
            return redirect(url_for('customer.checkout'))

        try:
            # Create a Stripe PaymentIntent with return_url
            intent = stripe.PaymentIntent.create(
                amount=int(math.ceil(total * 100)),  # Convert to cents, rounding up
                currency='usd',
                payment_method=payment_method_id,
                confirmation_method='manual',
                confirm=True,
                metadata={'integration_check': 'accept_a_payment'},
                return_url=url_for('customer.my_orders', _external=True)  # Set return_url to 'my_orders' page
            )

            if intent.status == 'requires_action' and intent.next_action.type == 'use_stripe_sdk':
                # Inform the frontend to handle the additional action
                flash('Additional authentication required. Please complete the payment.', 'warning')
                return redirect(intent.next_action.use_stripe_sdk.stripe_js)

            elif intent.status == 'succeeded':
                # Payment succeeded, create the order
                order = {
                    'user': current_user.id,
                    'services': session['cart'],
                    'total': total,
                    'order_date': datetime.now(),
                    'service_date': service_datetime,
                    'service_time': service_time_str,
                    'payment_method': payment_method_id,
                    'status': 'ordered',
                    'address': user.get('address', {}),
                    'creation_date': datetime.utcnow()
                }
                orders_collection.insert_one(order)

                flash('Your order has been placed successfully!', 'success')
                session.pop('cart', None)
                return redirect(url_for('customer.my_orders'))

            else:
                # Invalid status
                flash('Something went wrong with your payment. Please try again.', 'danger')
                return redirect(url_for('customer.checkout'))

        except stripe.error.CardError as e:
            # Card was declined
            flash(f"Card error: {e.user_message}", 'danger')
            return redirect(url_for('customer.checkout'))
        except stripe.error.StripeError as e:
            # Generic Stripe error
            flash('Payment processing error. Please try again.', 'danger')
            return redirect(url_for('customer.checkout'))
        except Exception as e:
            # Other errors
            current_app.logger.error(f"Checkout error: {e}")
            flash('An unexpected error occurred. Please try again.', 'danger')
            return redirect(url_for('customer.checkout'))

    # Provide a default service date for the template
    default_service_date = (datetime.today() + timedelta(days=1)).strftime('%Y-%m-%d')

    return render_template(
        'customer/checkout.html',
        services=services_in_cart,
        total=total,
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
    Displays the current user's orders.
    """
    users_collection = current_app.config['USERS_COLLECTION']
    orders_collection = current_app.config['ORDERS_COLLECTION']
    services_collection = current_app.config['SERVICES_COLLECTION']  # Ensure this is defined

    user_id = current_user.id
    user = users_collection.find_one({'_id': ObjectId(user_id)})
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('customer.customer_home'))

    # Check if Stripe redirected back with payment_intent
    payment_intent_id = request.args.get('payment_intent')
    if payment_intent_id:
        try:
            # Retrieve the PaymentIntent from Stripe
            intent = stripe.PaymentIntent.retrieve(payment_intent_id)

            if intent.status == 'succeeded':
                # Payment succeeded; check if the order already exists to prevent duplication
                existing_order = orders_collection.find_one({'payment_intent_id': payment_intent_id})
                if not existing_order:
                    # Assuming you stored the cart in the session before redirecting to Stripe
                    cart = session.get('cart', [])
                    if not cart:
                        flash('No items found in your cart to complete the order.', 'danger')
                        return redirect(url_for('customer.customer_home'))

                    # Calculate total again to ensure consistency
                    services_in_cart = []
                    for cart_item in cart:
                        service = services_collection.find_one({'_id': ObjectId(cart_item['service_id'])})
                        if service:
                            vehicle_size = cart_item.get('vehicle_size')
                            price_info = service.get('price_by_vehicle_size', {}).get(vehicle_size, {})
                            service['price'] = price_info.get('total', 0)
                            service['label'] = service.get('label') or service.get('label', 'Unnamed Service')
                            services_in_cart.append(service)

                    total = calculate_cart_total(services_in_cart)

                    # Create the order
                    order = {
                        'user': current_user.id,
                        'services': cart,  # Store service IDs and details
                        'total': total,
                        'order_date': datetime.now(),
                        'service_date': intent.metadata.get('service_date'),  # Assuming you passed this metadata
                        'service_time': intent.metadata.get('service_time'),  # Assuming you passed this metadata
                        'payment_method': intent.payment_method,
                        'payment_intent_id': payment_intent_id,  # Store PaymentIntent ID
                        'status': 'ordered',
                        'address': user.get('address', {}),
                        'creation_date': datetime.utcnow()
                    }
                    orders_collection.insert_one(order)

                    flash('Your order has been placed successfully!', 'success')
                    session.pop('cart', None)
            elif intent.status == 'requires_action':
                # Additional authentication required; should have been handled already
                flash('Additional authentication required. Please complete the payment.', 'warning')
            else:
                flash('Your payment could not be processed. Please try again.', 'danger')
        except stripe.error.StripeError as e:
            current_app.logger.error(f"Stripe error during order finalization: {e}")
            flash('Payment verification failed. Please contact support.', 'danger')
        except Exception as e:
            current_app.logger.error(f"Error during order finalization: {e}")
            flash('An unexpected error occurred. Please try again.', 'danger')

        # Retrieve the user's orders
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
    for order in user_orders:
        order['service_details'] = []
        for item in order.get('services', []):
            service = services_collection.find_one({'_id': ObjectId(item['service_id'])})
            if service:
                service['price'] = item.get('total', 0)
                order['service_details'].append(service)

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
