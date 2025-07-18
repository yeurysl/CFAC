# core.py
from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app, jsonify, Response
from flask_login import login_required, logout_user, current_user, login_user
from bson.objectid import ObjectId, InvalidId
from datetime import datetime
import re
import json
from dateutil.parser import parse 
import stripe
from forms import EmployeeLoginForm, UpdateAccountForm, GuestOrderForm
from extensions import User 
from utility import register_filters



core_bp = Blueprint('core', __name__)

@core_bp.route('/base')
def base():
    """
    Render a base template or partial layout.
    """
    return render_template('base.html')







@core_bp.route('/')
def home():
    # Hardcoded vehicle sizes
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

    try:
        # Fetch services from the database
        services_collection = current_app.config['SERVICES_COLLECTION']
        services = list(services_collection.find({'active': True}))

        if not services:
            current_app.logger.error("No active services found in the database.")

        # Convert MongoDB ObjectIds to strings
        for service in services:
            service['_id'] = str(service['_id'])

        # Print debugging information
        current_app.logger.info(f"Fetched {len(services)} services: {services}")

        # Default image
        default_image = url_for('static', filename='default_service.jpg')

        return render_template('home.html', vehicle_sizes=vehicle_sizes, services=services, default_image=default_image)

    except Exception as e:
        current_app.logger.error(f"Error fetching services: {e}", exc_info=True)
        return "Internal Server Error", 500

@core_bp.route('/aboutus')
def about():
    """
    About Us Page Route
    """
    return render_template('aboutus.html')


@core_bp.route('/careers')
def careers():
    """
    Careers Page Route
    """
    return render_template('careers.html')


@core_bp.route('/pdf')
def pdf():
    """
    Ceramic Page Route
    """
    products = [
        {
            'name': 'Ceramic Spray',
            'description': 'Cleans your tools thoroughly.',
            'price': 29.99,
            'image': 'limlex.png'
        }
    ]
    return render_template('pdf.html', products=products)




@core_bp.route('/header')
def header():
    """
    Render a header snippet or partial.
    """
    return render_template('header.html')


@core_bp.route('/logout')
@login_required
def logout():
    """
    Logout Route
    Logs out the current user, flashes a success message, and redirects to home.
    """
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('core.home'))


@core_bp.route('/account_settings', methods=['GET', 'POST'])
@login_required
def account_settings():
    """
    Account Settings Route
    Allows a logged-in user to update their name, email, phone number, and address.
    """
    users_collection = current_app.config['USERS_COLLECTION']
    user_id = current_user.id  # This is the string version of ObjectId

    try:
        user = users_collection.find_one({'_id': ObjectId(user_id)})
    except (InvalidId, TypeError):
        user = None

    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('core.home'))

    form = UpdateAccountForm()

    if request.method == 'POST':
        if form.validate_on_submit():
            # Extract form data
            name = form.name.data.strip()
            email = (form.email.data.lower().strip() 
                     if form.email.data else user.get('email', None))
            phone_number = form.phone_number.data.strip()
            street_address = form.street_address.data.strip()
            city = form.city.data.strip()
            country = form.country.data.strip()
            zip_code = form.zip_code.data.strip()

            # Prepare fields to update
            update_fields = {
                'name': name,
                'phone_number': phone_number,
                'address.street_address': street_address,
                'address.city': city,
                'address.country': country,
                'address.zip_code': zip_code
            }

            # Only update email if provided in the form
            if form.email.data:
                update_fields['email'] = email

            try:
                users_collection.update_one(
                    {'_id': ObjectId(user_id)},
                    {'$set': update_fields}
                )
                flash('Account settings updated successfully.', 'success')
                return redirect(url_for('core.account_settings'))
            except Exception as e:
                current_app.logger.error(f"Error updating user: {e}")
                flash('An error occurred while updating your account settings. Please try again.', 'danger')
                return redirect(url_for('core.account_settings'))
        else:
            flash('Please correct the errors in the form.', 'danger')
    else:
        # Pre-populate form with existing user data
        form.name.data = user.get('name', '')
        form.email.data = user.get('email', '')
        form.phone_number.data = user.get('phone_number', '')
        user_address = user.get('address', {})
        form.street_address.data = user_address.get('street_address', '')
        form.city.data = user_address.get('city', '')
        form.country.data = user_address.get('country', '')
        form.zip_code.data = user_address.get('zip_code', '')

    return render_template('account_settings.html', form=form, user=user)
@core_bp.route('/employee_login', methods=['GET', 'POST'])
def employee_login():
    """
    Employee Login Route (for admin/tech/sales).
    """
    form = EmployeeLoginForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        password = form.password.data

        users_collection = current_app.config['USERS_COLLECTION']
        user_record = users_collection.find_one({
            'username': username,
            'user_type': {'$in': ['admin']}
        })

        if not user_record:
            flash('Invalid username or user type.', 'danger')
            return render_template('employee_login.html', form=form)

        # Check the password against the stored hash
        from flask_bcrypt import check_password_hash
        if check_password_hash(user_record['password'], password):
            # Build a User object for Flask-Login
            user_obj = User(str(user_record['_id']), user_record['user_type'])
            login_user(user_obj)
            flash(f'Logged in successfully as {user_record["user_type"]}.', 'success')
            return redirect(url_for('admin.admin_main'))
        else:
            flash('Invalid password.', 'danger')

    return render_template('employee_login.html', form=form)

@core_bp.route('/privacy_policy')
def privacy_policy():
    """
    Render the Privacy Policy page.
    """
    return render_template('privacy_policy.html')
@core_bp.route('/refund_policy')
def refund_policy():
    """
    Render the Refund and Service Issue Policy page.
    """
    return render_template('refund_policy.html')





@core_bp.route('/payment_success')
def payment_success():
    # Extract the Stripe Checkout session ID from the query parameters
    session_id = request.args.get("session_id")
    if not session_id:
        return "Session ID missing", 400

    # Set your Stripe secret key and retrieve the session details
    stripe.api_key = current_app.config['STRIPE_SECRET_KEY']
    try:
        # Expand the PaymentIntent so that we can access its metadata
        session = stripe.checkout.Session.retrieve(
            session_id,
            expand=["payment_intent"]
        )
    except Exception as e:
        current_app.logger.error(f"Error retrieving Stripe session: {e}")
        return "Error retrieving payment session", 500

    # Extract the internal order_id from the PaymentIntent metadata
    order_id = session.payment_intent.metadata.get("order_id")
    if not order_id:
        current_app.logger.error("Order ID missing from PaymentIntent metadata")
        return "Order ID missing", 400

    # Retrieve the order from your database
    orders_collection = current_app.config.get('ORDERS_COLLECTION')
    if orders_collection is None:
        return "Orders collection not configured", 500

    order = orders_collection.find_one({"_id": ObjectId(order_id)})
    if not order:
        current_app.logger.error(f"Order not found: {order_id}")
        return "Order not found", 404

    # Convert date fields to datetime objects (if they're stored as strings)
    for date_field in ['creation_date', 'service_date']:
        date_value = order.get(date_field)
        if isinstance(date_value, str):
            try:
                # If the string ends with 'Z', replace it with '+00:00' for ISO compatibility
                if date_value.endswith('Z'):
                    order[date_field] = datetime.fromisoformat(date_value.replace("Z", "+00:00"))
                else:
                    order[date_field] = datetime.fromisoformat(date_value)
            except ValueError:
                current_app.logger.error(
                    f"Invalid {date_field} format for order {order.get('_id')}: {date_value}"
                )
                order[date_field] = None

    return render_template("payment_success.html", order=order)





@core_bp.route('/public_profile/tech/<user_id>')
def public_tech_profile(user_id):
    users_collection = current_app.config['USERS_COLLECTION']
    try:
        user = users_collection.find_one({'_id': ObjectId(user_id)})
    except Exception as e:
        flash("Invalid user ID.", "danger")
        return redirect(url_for('core.home'))
    
    if not user or user.get('user_type') != 'tech':
        flash("Tech user not found.", "danger")
        return redirect(url_for('core.home'))
    
    return render_template("public_tech_profile.html", user=user)


@core_bp.route('/public_profile/sales/<user_id>')
def public_sales_profile(user_id):
    users_collection = current_app.config['USERS_COLLECTION']
    try:
        user = users_collection.find_one({'_id': ObjectId(user_id)})
    except Exception as e:
        flash("Invalid user ID.", "danger")
        return redirect(url_for('core.home'))
    
    if not user or user.get('user_type') != 'sales':
        flash("Sales user not found.", "danger")
        return redirect(url_for('core.home'))
    
    return render_template("public_sales_profile.html", user=user)




import os
import stripe
import stripe
from flask import request, redirect, url_for, Blueprint
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")


@core_bp.route("/create-checkout-session", methods=["POST"])
def create_checkout_session():
    price_id = request.form.get("price_id")
    current_app.logger.info(f"👀 Received price_id: {price_id}")

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card", "afterpay_clearpay", "klarna", "affirm", "cashapp"],
            line_items=[{
                "price": price_id,
                "quantity": 1,
            }],
            mode="payment",
            shipping_address_collection={"allowed_countries": ["US"]},
            # point success_url at /thank-you
            success_url=url_for("core.thank_you", _external=True),
            cancel_url =url_for("core.shop", _external=True) + "?canceled=true",
        )
        current_app.logger.info(f"➡️ Redirecting to Stripe checkout: {session.url}")
        return redirect(session.url, code=303)

    except Exception as e:
        current_app.logger.error(f"❌ Stripe error: {e}")
        return str(e), 400


from flask import Blueprint, render_template


@core_bp.route("/shop")
def shop():
    products = [
        {
            'name': 'Brush Cleaner',
            'description': 'Cleans your tools thoroughly.',
            'price': 29.99,
            'image': 'brush.png'
        },
        {
            'name': 'Tank Scrubber',
            'description': 'Heavy-duty tank scrubbing device.',
            'price': 39.99,
            'image': 'tank.png'
        },
        {
            'name': 'Vacuum Pro',
            'description': 'Professional-grade vacuum.',
            'price': 49.99,
            'image': 'vac.png'
        }
    ]

    return render_template("shop.html", products=products)


@core_bp.route("/thank-you")
def thank_you():
    # You could pull the session_id from a query param and fetch more info here
    # session_id = request.args.get("session_id")
    return render_template("thank_you.html")




@core_bp.route("/founder")
def founder():
    return render_template("founder.html")



# ─────────── blueprints/core.py (or blueprints/guest.py) ───────────
from flask import (
    Blueprint, request, redirect, url_for, flash,
    current_app, session, render_template, Response
)
from bson.objectid import ObjectId
from datetime import datetime
import math, stripe, pprint
from notis import send_postmark_email            #  ← same helper you use for customers
from forms import GuestOrderForm

#  G U E S T   C H E C K O U T   (core.guest_order)
# ──────────────────────────────────────────────────────────────────────────────
from datetime import datetime
from pprint import pformat
import math, stripe
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, current_app, Response,
)
from bson import ObjectId
from forms import GuestOrderForm

import pprint                                    # add once at top of file
pp = pprint.PrettyPrinter(indent=2).pformat      # handy alias

@core_bp.route("/guest/order", methods=["GET", "POST"])
def guest_order() -> Response:
    print("🔵 ENTER guest_order --------------------------------------------------")
    form = GuestOrderForm()

    # ── query-string --------------------------------------------------------
    service_ids  = request.args.get("service_id", "").split(",")
    vehicle_size = request.args.get("vehicle_size", "")
    appt_iso     = request.args.get("appointment", "")
    date_str, time_str = ("", "")
    if "T" in appt_iso:
        date_str, time_str = appt_iso.split("T")

    print(f"💠 Query params → service_ids={service_ids}  "
          f"vehicle_size='{vehicle_size}'  appointment='{appt_iso}'")

    # ── pre-fill WTForms ----------------------------------------------------
    if request.method == "GET":
        if date_str:
            form.service_date.data = datetime.strptime(date_str, "%Y-%m-%d").date()
        if time_str:
            form.service_time.data = datetime.strptime(time_str, "%H:%M").time()
        form.payment_time.data = "pay_now"

    # ── rebuild service list & pricing -------------------------------------
    services, subtotal, total_minutes = [], 0.0, 0
    for sid in filter(ObjectId.is_valid, service_ids):
        doc = current_app.config["SERVICES_COLLECTION"].find_one({"_id": ObjectId(sid)})
        if not doc:
            print(f"⚠️  Service id {sid} not found in DB")
            continue
        sz = doc.get("price_by_vehicle_size", {}).get(vehicle_size, {})
        price   = sz.get("price", 0)
        minutes = int(sz.get("completion_time", "0").split()[0] or 0)
        services.append({"label": doc["label"], "price": price, "minutes": minutes})
        subtotal      += price
        total_minutes += minutes

    print(f"💠 After service loop → services={pp(services)}")
    print(f"   subtotal={subtotal}  total_minutes={total_minutes}")

    gross      = math.ceil(subtotal / 0.55)
    travel_fee = 25 if gross < 90 else (15 if gross < 100 else 0)
    total      = gross + travel_fee
    deposit    = round(total * 0.25, 2)

    print(f"💠 Pricing → gross={gross} travel_fee={travel_fee} "
          f"total={total} deposit={deposit}")

    order = {
        "vehicle_size"     : vehicle_size.replace("_", " ").title(),
        "service_date"     : form.service_date.data.isoformat() if form.service_date.data else "",
        "service_time"     : form.service_time.data.strftime("%H:%M") if form.service_time.data else "",
        "services"         : services,
        "services_total"   : round(subtotal, 2),
        "travel_fee"       : travel_fee,
        "fee"              : round(gross * 0.45, 2),
        "total"            : total,
        "deposit"          : deposit,
        "estimated_minutes": total_minutes
    }
    print("💠 Built `order` dict →\n", pp(order))

    # ── POST: insert & redirect --------------------------------------------
    if form.validate_on_submit():
        print("🟢 WTForms validation PASSED – inserting order…")
        _id = current_app.config["ORDERS_COLLECTION"].insert_one({
            **order,
            "creation_date": datetime.utcnow().isoformat(),
            "status"       : "ordered",
            "payment_status": "Pending",
            "payment_time" : form.payment_time.data,
            "is_guest"     : True,
            "guest_name"   : form.guest_name.data,
            "guest_email"  : form.guest_email.data,
            "guest_phone_number": form.guest_phone_number.data,
            "guest_address": {
                "street" : form.street_address.data,
                "unit"   : form.unit_apt.data,
                "city"   : form.city.data,
                "zip"    : form.zip_code.data,
                "country": form.country.data,
            },
            "selectedServices": services,
        }).inserted_id
        print(f"✅ order {_id} INSERTED – redirecting to /guest/stripe/{_id}")
        return redirect(url_for("core.guest_stripe_checkout", order_id=str(_id)))

    if request.method == "POST":
        print("🔴 WTForms validation FAILED →", form.errors)

    print("🔵 EXIT guest_order (render template)")
    return render_template("guest_order.html", form=form, order=order)




def send_partial_payment_thankyou_email(order, balance_url):
    
    html_body = render_template("emails/partial_payment_thankyou.html",
                                order=order,
                                balance_url=balance_url,
                                )





import pprint
pp = pprint.PrettyPrinter(indent=2).pformat


@core_bp.route("/guest/start_payment", methods=["POST"])
def guest_start_payment():
    """
    Single-step flow:
        – rebuild pricing from posted hidden fields
        – insert order
        – immediately start Stripe checkout
    """
    print("🔵 ENTER start_payment + create order")

    # ── 0. basic config ----------------------------------------------------
    coll_services = current_app.config["SERVICES_COLLECTION"]
    coll_orders   = current_app.config["ORDERS_COLLECTION"]
    stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]

    # ── 1. pull form fields ------------------------------------------------
    service_ids   = request.form.get("service_ids", "").split(",")
    vehicle_size  = request.form.get("vehicle_size", "")
    appointment   = request.form.get("appointment", "")          # optional
    payment_time  = request.form.get("payment_time", "pay_now")   # radio btn

    guest_name    = request.form["guest_name"]
    guest_email   = request.form["guest_email"]
    guest_phone = request.form.get("guest_phone") \
            or request.form.get("guest_phone_number")  
    street        = request.form["street_address"]
    unit_apt      = request.form.get("unit_apt")
    city          = request.form["city"]
    zip_code      = request.form["zip_code"]
    country       = request.form["country"]

    print("💠 Raw POST →", pp(request.form.to_dict(flat=True)))

    # ── 2. rebuild services + pricing -------------------------------------
    services, subtotal, minutes = [], 0.0, 0
    for sid in filter(ObjectId.is_valid, service_ids):
        doc = coll_services.find_one({"_id": ObjectId(sid)})
        if not doc:
            continue
        sz = doc.get("price_by_vehicle_size", {}).get(vehicle_size, {})
        price   = sz.get("price", 0)
        mins    = int(sz.get("completion_time", "0").split()[0] or 0)
        services.append({"label": doc["label"], "price": price, "minutes": mins})
        subtotal += price
        minutes  += mins

    gross       = math.ceil(subtotal / 0.55)            # keep 45 % margin
    travel_fee  = 25 if gross < 90 else (15 if gross < 100 else 0)
    total       = gross + travel_fee
    deposit_amt = round(total * 0.25, 2)

    print(f"💠 Pricing → subtotal={subtotal} gross={gross} "
          f"travel_fee={travel_fee} total={total}")

    # ── 3. build + INSERT order doc ---------------------------------------
    order_doc = {
        "vehicle_size" : vehicle_size.replace("_", " ").title(),
        "appointment"  : appointment,
        "services"     : services,
        "services_total": round(subtotal, 2),
        "travel_fee"   : travel_fee,
        "fee"          : round(gross * 0.45, 2),
        "total"        : total,
        "deposit"      : deposit_amt,
        "estimated_minutes": minutes,
        "creation_date": datetime.utcnow().isoformat(),
        "status"       : "ordered",
        "payment_status": "Pending",
        "payment_time" : payment_time,
        "is_guest"     : True,
        "guest_name"   : guest_name,
        "guest_email"  : guest_email,
    **({"guest_phone_number": guest_phone} if guest_phone else {}),
        "guest_address": {
            "street": street, "unit": unit_apt, "city": city,
            "zip": zip_code, "country": country,
        },
        "selectedServices": services,
    }
    order_id = coll_orders.insert_one(order_doc).inserted_id
    print(f"✅ order {order_id} INSERTED")

    # ── 4. create Stripe checkout(s) --------------------------------------
    success_url = url_for("core.guest_thank_you", _external=True)
    cancel_url  = url_for("core.guest_order", _external=True)

    if payment_time == "pay_now":
        amount_cents = int(total * 100)
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            customer_email=guest_email,
            line_items=[{
                "price_data": {
                    "currency":"usd",
                    "product_data":{"name": f"Guest Order #{order_id}"},
                    "unit_amount": amount_cents,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=success_url,
            cancel_url =cancel_url,
            metadata={"order_id": str(order_id), "payment_type": "full"},
        )
        coll_orders.update_one({"_id": order_id},
                               {"$set": {"checkout_url": session.url}})
        print("✅ Stripe FULL session url →", session.url)
        return redirect(session.url)

    # ------------ deposit / balance -----------------
    elif payment_time == "after":
        dep_cents = int(deposit_amt * 100)
        bal_cents = int((total - deposit_amt) * 100)

        dep_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            customer_email=guest_email,
            line_items=[{
                "price_data": {
                    "currency":"usd",
                    "product_data":{"name": f"25 % Deposit – Order #{order_id}"},
                    "unit_amount": dep_cents,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=success_url,
            cancel_url =cancel_url,
            metadata={"order_id": str(order_id), "payment_type": "deposit"},
        )
        # you could also create the balance session here and store its URL
        coll_orders.update_one({"_id": order_id},
                               {"$set": {
                                   "deposit_checkout_url": dep_session.url,
                                   "remaining_amount_cents": bal_cents,
                               }})
        print("✅ Stripe DEPOSIT session url →", dep_session.url)
        return redirect(dep_session.url)

    else:
        flash("Invalid payment option.", "danger")
        return redirect(url_for("core.home"))


# ── Stripe one-off checkout (full amount OR deposit – you can branch later) ──
@core_bp.route("/guest/stripe/<order_id>")
def guest_stripe_checkout(order_id: str) -> Response:
    orders = current_app.config["ORDERS_COLLECTION"]
    order  = orders.find_one({"_id": ObjectId(order_id)})
    if not order:
        flash("Order not found.", "danger")
        return redirect(url_for("core.guest_order"))

    stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]

    amount_cents = int(order["total"] * 100)       # Stripe uses cents
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency"    : "usd",
                "product_data": {"name": f"Guest Order #{order_id}"},
                "unit_amount" : amount_cents,
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url=url_for("core.guest_thank_you", _external=True),
        cancel_url =url_for("core.guest_order", _external=True),
        metadata={"order_id": order_id},
    )
    return redirect(session.url, code=303)
# ──────────────────────────────────────────────────────────────────────────────





# 2c) Thank‑you page
@core_bp.route('/guest/thank-you')
def guest_thank_you():
    return render_template('guest_thank_you.html')
