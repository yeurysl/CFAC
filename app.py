from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from pymongo import MongoClient
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf import CSRFProtect
from flask_wtf.csrf import generate_csrf
from forms import RegistrationForm, RemoveFromCartForm, CustomerLoginForm, EmployeeLoginForm, UpdateAccountForm, GuestOrderForm
from functools import wraps
from flask_mail import Mail, Message
from werkzeug.middleware.proxy_fix import ProxyFix
from bson.objectid import ObjectId, InvalidId
from urllib.parse import urlparse, urljoin, quote_plus
from datetime import datetime, timedelta, time
from dateutil import parser
import phonenumbers
from flask import current_app
import re
import os


ENV = os.getenv('ENV', 'development')   




load_dotenv()

app = Flask(__name__)

# Apply ProxyFix to handle Heroku's proxy headers
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

app.secret_key = os.getenv('SECRET_KEY')
app.config['WTF_CSRF_TIME_LIMIT'] = None

bcrypt = Bcrypt(app)

csrf = CSRFProtect(app)


#Mongo DB SETUP\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\

MONGODB_URI = os.getenv('MONGODB_URI')

# MongoDB connection string
client = MongoClient(MONGODB_URI, tls=True, tlsAllowInvalidCertificates=True)


db = client["cfacdb"]
users_collection = db["users"]  
estimaterequests_collection = db["estimaterequests"]  
products_collection = db["products"]
orders_collection = db['orders']


@app.template_filter('urlencode')
def urlencode_filter(s):
    if isinstance(s, str):
        return quote_plus(s)
    else:
        return s


# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'employee_admin_login'
login_manager.login_message_category = 'info'  


@app.context_processor
def inject_csrf_token():
    return dict(csrf_token=generate_csrf)





# Session cookie settings for enhanced security
app.config['SESSION_COOKIE_SECURE'] = True          # Ensures cookies are sent over HTTPS only
app.config['SESSION_COOKIE_HTTPONLY'] = True        # Prevents JavaScript access to cookies
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'       # Mitigates CSRF attacks


# Flask-Mail SETUP
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = os.getenv('EMAIL_USER')  # Get email username from environment
app.config['MAIL_PASSWORD'] = os.getenv('EMAIL_PASSWORD')  # Get email password from environment
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('EMAIL_USER')

mail = Mail(app)





# User Model FLASK-LOGIN
class User(UserMixin):
    def __init__(self, identifier, user_type):
        self.id = identifier  # Can be username or email based on user_type
        self.user_type = user_type

# User Loader Callback


@login_manager.user_loader
def load_user(user_id):
    # For admin, tech, and sales users
    user = users_collection.find_one({
        'username': user_id,
        'user_type': {'$in': ['admin', 'tech', 'sales']}
    })
    if user:
        return User(user['username'], user['user_type'])
    
    # For customers
    user = users_collection.find_one({
        'email': user_id,
        'user_type': 'customer'
    })
    if user:
        return User(user['email'], user['user_type'])
    
    return None


#SINGLE DEFS\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\


# For Currency Format
def currency_format(value):
    """
    Formats a float value as currency.
    Example: 29.99 -> $29.99
    """
    try:
        value = float(value)
        if value < 0:
            return "-${:,.2f}".format(abs(value))
        return "${:,.2f}".format(value)
    except (ValueError, TypeError):
        return value  # Return the original value if conversion fails

# Register the currency filter
app.jinja_env.filters['currency'] = currency_format

# For Date Format
def format_date_with_suffix(date):
    """
    Formats a datetime object into 'Month DaySuffix Year' format.
    Example: October 10th 2024
    """
    if not isinstance(date, datetime):
        return date  # Return as-is if not a datetime object

    day = date.day
    suffix = 'th' if 11 <= day <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
    formatted_date = date.strftime(f'%B {day}{suffix} %Y')
    return formatted_date

# Register the date format filter
app.jinja_env.filters['format_date'] = format_date_with_suffix

#FORLOGINS
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in as an admin to access this page.', 'warning')
            return redirect(url_for('employee_admin_login', next=request.url))
        if current_user.user_type != 'admin':
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

def tech_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in as a tech to access this page.', 'warning')
            return redirect(url_for('employee_admin_login', next=request.url))
        if current_user.user_type != 'tech':
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function


def sales_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in as a sales user to access this page.', 'warning')
            return redirect(url_for('employee_admin_login', next=request.url))
        if current_user.user_type != 'sales':
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

def customer_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in as a customer to access this page.', 'warning')
            return redirect(url_for('customer_login', next=request.url))
        if current_user.user_type != 'customer':
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

#FOREMAILSENDING
def send_order_confirmation_email(to_email, order, products):
    msg = Message('Order Confirmation', recipients=[to_email])
    msg.html = render_template('/customer/order_confirmation_email.html', order=order, products=products)
    mail.send(msg)


#FORCART
def calculate_cart_total(products):
    total = sum(product['price'] for product in products)
    return total




#ROUTES\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\


#Base Route
@app.route('/base')
def base():
    return render_template('/base.html')

#Home Page Route
@app.route('/')
def home():
    # Fetch all products
    products = list(products_collection.find())
    # Convert ObjectId to string for template usage
    for product in products:
        product['_id'] = str(product['_id'])
    
    # Select Sedan as the default product
    default_product = next((product for product in products if product['name'] == "Sedan Complete Detailing"), products[0] if products else None)
    
    return render_template('home.html', default_product=default_product, products=products)


# API endpoint to fetch all products (for dynamic features)
@app.route('/api/products')
def get_products():
    products = list(products_collection.find())
    for product in products:
        product['_id'] = str(product['_id'])  # Convert ObjectId to string
    return jsonify(products)


#About Us Page Route
@app.route('/aboutus')
def about():
    return render_template('/aboutus.html')
#Career Page Route
@app.route('/careers')
def career():
    return render_template('/careers.html')
#Render Header Route
@app.route('/header')
def header():
    return render_template('/header.html')

#Logout Route
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('home'))

#Test
@app.route('/protected')
@login_required
def protected():
    return "This is a protected page!"

#Account Settings Route

@app.route('/account_settings', methods=['GET', 'POST'])
@login_required
def account_settings():
    identifier = current_user.id
    user_type = current_user.user_type

    # Updated user_type checks: 'admin', 'tech', 'sales' use 'username'; 'customer' uses 'email'
    if user_type in ['admin', 'tech', 'sales']:
        user = users_collection.find_one({'username': identifier})
    elif user_type == 'customer':
        user = users_collection.find_one({'email': identifier})
    else:
        user = None

    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('home'))

    form = UpdateAccountForm()

    if request.method == 'POST':
        if form.validate_on_submit():
            # Extract form data
            name = form.name.data.strip()
            phone_number = form.phone_number.data.strip()
            street_address = form.street_address.data.strip()
            city = form.city.data.strip()
            country = form.country.data.strip()
            zip_code = form.zip_code.data.strip()

            # Update user information
            update_fields = {
                'name': name,
                'phone_number': phone_number,
                'address.street_address': street_address,
                'address.city': city,
                'address.country': country,
                'address.zip_code': zip_code
            }

            try:
                if user_type in ['admin', 'tech', 'sales']:
                    users_collection.update_one(
                        {'username': identifier},
                        {'$set': update_fields}
                    )
                elif user_type == 'customer':
                    users_collection.update_one(
                        {'email': identifier},
                        {'$set': update_fields}
                    )
                flash('Account settings updated successfully.', 'success')
                return redirect(url_for('account_settings'))
            except Exception as e:
                flash('An error occurred while updating your account settings. Please try again.', 'danger')
                current_app.logger.error(f"Error updating user: {e}")
                return redirect(url_for('account_settings'))
        else:
            # Handle form validation errors
            flash('Please correct the errors in the form.', 'danger')
    else:
        # Pre-populate form with existing user data
        form.name.data = user.get('name', '')
        form.phone_number.data = user.get('phone_number', '')
        form.street_address.data = user.get('address', {}).get('street_address', '')
        form.city.data = user.get('address', {}).get('city', '')
        form.country.data = user.get('address', {}).get('country', '')
        form.zip_code.data = user.get('address', {}).get('zip_code', '')

    return render_template('account_settings.html', form=form, user=user)

#Routes for Techs\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\
# Routes for Techs
@app.route('/tech/main')
@login_required
@tech_required
def tech_main():
    try:
        # Define the filter to fetch all 'ordered' orders
        filter_query = {'status': 'ordered'}
        
        # Fetch all 'ordered' orders sorted by order_date descending
        orders = list(orders_collection.find(filter_query).sort('order_date', -1))

        # Enrich orders with user and product details
        for order in orders:
            # Set user_display
            if order.get('user'):
                user = users_collection.find_one({'email': order['user']})
                order['user_display'] = user['email'] if user else 'Unknown'
            else:
                order['user_display'] = 'Guest'

            # Ensure dates are datetime objects
            if isinstance(order['order_date'], str):
                order['order_date'] = datetime.strptime(order['order_date'], '%Y-%m-%d %H:%M:%S')
            if isinstance(order['service_date'], str):
                order['service_date'] = datetime.strptime(order['service_date'], '%Y-%m-%d')

            # Fetch product details
            try:
                # Convert product IDs from strings to ObjectId instances
                product_ids = []
                for pid in order.get('products', []):
                    try:
                        product_ids.append(ObjectId(pid))
                    except InvalidId as e:
                        current_app.logger.error(f"Invalid product ID {pid} in order {order['_id']}: {e}")

                # Fetch products from the products_collection
                if product_ids:
                    products = list(products_collection.find({'_id': {'$in': product_ids}}))
                else:
                    products = []

                order['product_details'] = products
            except Exception as e:
                current_app.logger.error(f"Error fetching products for order {order['_id']}: {e}")
                order['product_details'] = []

        return render_template('tech/main.html', orders=orders)
    except Exception as e:
        current_app.logger.error(f"Error fetching orders: {e}")
        flash('An error occurred while fetching orders.', 'danger')
        return redirect(url_for('home'))
#My schedule route
@app.route('/tech/my_schedule')
@login_required
@tech_required
def my_schedule():
    try:
        # Fetch scheduled orders assigned to the current employee
        filter_query = {'status': 'scheduled', 'scheduled_by': current_user.id}
        orders = list(orders_collection.find(filter_query).sort('service_date', 1))

        # Enrich orders with product and address details
        for order in orders:
            # Fetch product details
            product_ids = [ObjectId(pid) for pid in order.get('products', [])]
            products = list(products_collection.find({'_id': {'$in': product_ids}}))
            order['product_details'] = products

            # Ensure dates are datetime objects
            if isinstance(order['order_date'], str):
                order['order_date'] = datetime.strptime(order['order_date'], '%Y-%m-%d %H:%M:%S')
            if isinstance(order['service_date'], str):
                order['service_date'] = datetime.strptime(order['service_date'], '%Y-%m-%d')

            # Include address details
            if order.get('guest_address'):
                # For guest orders
                order['address'] = order['guest_address']
            elif order.get('user'):
                # For registered user orders, fetch the user's address from the users_collection
                user = users_collection.find_one({'email': order['user']})
                if user and 'address' in user:
                    order['address'] = user['address']
                else:
                    order['address'] = None
            else:
                order['address'] = None  # Or handle as needed

            # Construct full address string
            if order['address']:
                address_components = [
                    order['address'].get('street_address'),
                    order['address'].get('unit_apt'),
                    order['address'].get('city'),
                    order['address'].get('country'),
                    order['address'].get('zip_code')
                ]
                # Filter out empty components and join them
                full_address = ', '.join(filter(None, address_components))
                order['full_address'] = full_address
            else:
                order['full_address'] = None

        return render_template('tech/my_schedule.html', orders=orders)
    except Exception as e:
        current_app.logger.error(f"Error fetching schedule: {e}")
        flash('An error occurred while fetching your schedule.', 'danger')
        return redirect(url_for('home'))



#Schedule order route
@app.route('/tech/order/<order_id>/schedule', methods=['POST'])
@login_required
@tech_required  # Ensure this decorator is defined
def schedule_order(order_id):
    try:
        # Fetch the order by ID
        order = orders_collection.find_one({'_id': ObjectId(order_id)})

        if not order:
            flash('Order not found.', 'danger')
            return redirect(url_for('tech_main'))

        # Check if the current status is 'ordered'
        if order.get('status', '').lower() != 'ordered':
            flash('Only orders with status "ordered" can be scheduled.', 'warning')
            return redirect(url_for('tech_main'))

        # Update the status to 'scheduled' and add 'scheduled_by'
        orders_collection.update_one(
            {'_id': ObjectId(order_id)},
            {
                '$set': {
                    'status': 'scheduled',
                    'scheduled_by': current_user.id  # Assuming 'id' is username for techs
                }
            }
        )

        # Fetch updated order details
        updated_order = orders_collection.find_one({'_id': ObjectId(order_id)})

        # Determine if the order is a guest order or a registered customer order
        if updated_order.get('is_guest'):
            customer_email = updated_order.get('guest_email')
            customer_name = updated_order.get('guest_name', 'Guest')
        else:
            customer_email = updated_order.get('user')
            # Fetch customer name from users_collection
            user = users_collection.find_one({'email': customer_email})
            customer_name = user.get('name', 'Valued Customer') if user else 'Valued Customer'

        # Fetch technician's name
        scheduled_by_username = updated_order.get('scheduled_by')
        if scheduled_by_username:
            tech_user = users_collection.find_one({'username': scheduled_by_username})
            tech_name = tech_user.get('name', 'Technician') if tech_user else 'Technician'
        else:
            tech_name = 'Technician'  # Default value if not found

        # Send email notification if customer_email is available
        if customer_email:
            try:
                send_order_scheduled_email(customer_email, customer_name, updated_order, tech_name)
                flash(f'Order {order_id} has been scheduled successfully and notification sent to the customer.', 'success')
            except Exception as e:
                app.logger.error(f"Failed to send notification email for order {order_id}: {e}")
                flash(f'Order {order_id} has been scheduled, but failed to send notification email.', 'warning')
        else:
            flash(f'Order {order_id} has been scheduled successfully.', 'success')

        return redirect(url_for('tech_main'))
    except Exception as e:
        app.logger.error(f"Error scheduling order {order_id}: {e}")
        flash('An error occurred while scheduling the order.', 'danger')
        return redirect(url_for('tech_main'))


#Send scheduled order confirmation to customer 
# app.py

def send_order_scheduled_email(to_email, customer_name, order, tech_name):
    """
    Sends an email notification to the customer when their order is scheduled.
    
    Args:
        to_email (str): Recipient's email address.
        customer_name (str): Recipient's name.
        order (dict): Order details.
        tech_name (str): Name of the technician who scheduled the order.
    """
    try:
        current_year = datetime.utcnow().year  # Calculate current year
        msg = Message(
            subject='Your Order Has Been Scheduled!',
            recipients=[to_email],
            html=render_template(
                'emails/order_scheduled_email.html', 
                customer_name=customer_name, 
                order=order, 
                tech_name=tech_name,
                current_year=current_year  # Pass current_year to the template
            )
        )
        mail.send(msg)
    except Exception as e:
        app.logger.error(f"Error sending email to {to_email}: {e}")
        raise e  # Re-raise the exception to handle it in the calling function

# Employee/Admin Login Route
@app.route('/tech_admin_login', methods=['GET', 'POST'])
def tech_admin_login():
    form = EmployeeLoginForm()
    if form.validate_on_submit():
        # Authenticate admin, tech, or sales using username
        user = users_collection.find_one({
            'username': form.username.data,
            'user_type': {'$in': ['admin', 'tech', 'sales']}
        })
        if user and bcrypt.check_password_hash(user['password'], form.password.data):
            user_obj = User(user['username'], user['user_type'])
            login_user(user_obj)
            flash(f'Logged in successfully as {user["user_type"]}.', 'success')
            next_page = request.args.get('next')
            # Redirect to appropriate dashboard
            if user['user_type'] == 'admin':
                return redirect(next_page or url_for('admin_main'))
            elif user['user_type'] == 'tech':
                return redirect(next_page or url_for('tech_main'))
            elif user['user_type'] == 'sales':
                return redirect(next_page or url_for('sales_main'))
            else:
                flash('Invalid user type.', 'danger')
                return redirect(url_for('tech_admin_login'))
        else:
            flash('Invalid username or password.', 'danger')
    return render_template('tech_admin_login.html', form=form)






#Routes for Sales\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\


@app.route('/sales/main')
@login_required
@sales_required
def sales_main():

    return render_template('sales/main.html')


#Schedule Guest Order Route
@app.route('/sales/schedule_guest_order', methods=['GET', 'POST'])
@login_required
@sales_required  # Ensure this decorator is defined
def schedule_guest_order():
    form = GuestOrderForm()
    
    # Populate product choices from the database
    products = list(products_collection.find())
    form.products.choices = [(str(product['_id']), product['name']) for product in products]
    
    if form.validate_on_submit():
        try:
            # Capture guest information
            guest_name = form.guest_name.data.strip()
            guest_email = form.guest_email.data.strip().lower() if form.guest_email.data else None
            guest_phone_number = form.guest_phone_number.data.strip() if form.guest_phone_number.data else None
            street_address = form.street_address.data.strip()
            unit_apt = form.unit_apt.data.strip()
            city = form.city.data.strip()
            country = form.country.data.strip()
            zip_code = form.zip_code.data.strip()
            
            # Capture order information
            service_date = form.service_date.data
            # Convert service_date from date to datetime
            service_datetime = datetime.combine(service_date, datetime.min.time())
            selected_product_ids = form.products.data  # List of product ID strings
            
            # Convert product IDs to ObjectId
            product_ids = []
            for pid in selected_product_ids:
                try:
                    product_ids.append(ObjectId(pid))
                except InvalidId:
                    flash(f"Invalid product ID: {pid}", 'danger')
                    return redirect(url_for('schedule_guest_order'))
            
            # Calculate total amount
            selected_products = list(products_collection.find({'_id': {'$in': product_ids}}))
            if not selected_products:
                flash("No valid products selected.", 'danger')
                return redirect(url_for('schedule_guest_order'))
            total_amount = sum(product.get('price', 0) for product in selected_products)
            
            # Create the order document
            order = {
                'user': None,  # No user associated since it's a guest order
                'is_guest': True,  # Explicitly mark as guest order
                'guest_name': guest_name,
                'guest_email': guest_email,
                'guest_phone_number': guest_phone_number,
                'guest_address': {
                    'street_address': street_address,
                    'unit_apt': unit_apt,
                    'city': city,
                    'country': country,
                    'zip_code': zip_code
                },
                'products': selected_product_ids,  # Store as string IDs
                'total': total_amount,
                'order_date': datetime.utcnow(),
                'service_date': service_datetime,  # Use datetime object
                'status': 'ordered',  # Changed from 'scheduled' to 'ordered'
                'salesperson': current_user.id,  # Add 'salesperson' field
                'creation_date': datetime.utcnow()
            }
            
            # Insert the order into the database
            inserted_order = orders_collection.insert_one(order)
            
            # Optional: Send confirmation email to guest
            if guest_email:
                send_guest_order_confirmation_email(guest_email, order, selected_products)
            
            # Flash success message and redirect
            flash(f"Guest order scheduled successfully by {current_user.id}!", 'success')
            return redirect(url_for('sales_main'))
        except Exception as e:
            current_app.logger.error(f"Error scheduling guest order: {e}")
            flash('An error occurred while scheduling the guest order. Please try again.', 'danger')
            return redirect(url_for('schedule_guest_order'))
    
    return render_template('sales/schedule_guest_order.html', form=form)

#Routes for Customers\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\
#Customer Page Route
@app.route('/customer/home')
@customer_required
def customer_home():
    # Fetch all products
    products = list(products_collection.find())
    # Convert ObjectId to string for template usage
    for product in products:
        product['_id'] = str(product['_id'])
    
    # Select Sedan as the default product
    default_product = next((product for product in products if product['name'] == "Sedan Complete Detailing"), products[0] if products else None)
    
    return render_template('customer/home.html', default_product=default_product, products=products)


#Cart Page Route
@app.route('/customer/cart', methods=['GET', 'POST'])
@customer_required  # Ensure this decorator is defined and correctly restricts access
def cart():
    if 'cart' not in session or not session['cart']:
        flash('Your cart is empty.', 'info')
        return render_template('customer/cart.html', products=[], forms={}, user_address=None)

    product_ids = [ObjectId(id) for id in session['cart']]
    products_in_cart = list(products_collection.find({'_id': {'$in': product_ids}}))
    total = calculate_cart_total(products_in_cart)

    # Create a dictionary of forms, one for each product
    forms = {}
    for product in products_in_cart:
        form = RemoveFromCartForm()
        form.product_id.data = str(product['_id'])
        forms[str(product['_id'])] = form

    # Fetch the current user's address
    user = users_collection.find_one({'email': current_user.id})  # Assuming 'id' is email for customers
    if user and 'address' in user:
        user_address = user['address']
    else:
        user_address = None  # Handle cases where address might not be available

    if request.method == 'POST':
        # Retrieve the product_id from the submitted form
        product_id = request.form.get('product_id')
        if product_id in session.get('cart', []):
            session['cart'].remove(product_id)
            flash('Item removed from your cart.', 'success')
        else:
            flash('Item not found in your cart.', 'warning')
        return redirect(url_for('cart'))

    return render_template('customer/cart.html', products=products_in_cart, total=total, forms=forms, user_address=user_address)
#ATC Route for Function
@app.route('/customer/add_to_cart/<product_id>')
@customer_required 
def add_to_cart(product_id):
    if 'cart' not in session:
        session['cart'] = []

    session['cart'].append(product_id)
    flash('Product added to cart!', 'success')
    return redirect(url_for('cart'))



#Display of Product Route for Function
@app.route('/products')
def products():
    # Your logic to display products
    products = list(products_collection.find())
    return render_template('products.html', products=products)

#Checkout Page Route
@app.route('/customer/checkout', methods=['GET', 'POST'])
@login_required
@customer_required  # Ensure this decorator restricts access to customers
def checkout():
    if 'cart' not in session or not session['cart']:
        flash('Your cart is empty.', 'info')
        return redirect(url_for('customer_home'))

    product_ids = [ObjectId(id) for id in session['cart']]
    products_in_cart = list(products_collection.find({'_id': {'$in': product_ids}}))
    total = calculate_cart_total(products_in_cart)

    # Fetch the current user's address
    user = users_collection.find_one({'email': current_user.id})  # Assuming 'id' is email for customers
    if user and 'address' in user:
        user_address = user['address']
    else:
        user_address = None  # Handle cases where address might not be available

    if request.method == 'POST':
        # Retrieve service date and time from the form
        service_date_str = request.form.get('service_date')
        service_time_str = request.form.get('service_time')
        payment_method = request.form.get('payment_method')

        # Validate service date
        if not service_date_str:
            flash('Please select a service date.', 'warning')
            return redirect(url_for('checkout'))

        try:
            service_date = datetime.strptime(service_date_str, '%Y-%m-%d').date()
            today = datetime.now().date()
            if service_date < today:
                flash('Service date cannot be in the past.', 'danger')
                return redirect(url_for('checkout'))
        except ValueError:
            flash('Invalid service date format.', 'danger')
            return redirect(url_for('checkout'))

        # Validate service time
        if not service_time_str:
            flash('Please select a service time.', 'warning')
            return redirect(url_for('checkout'))

        try:
            # Convert service_time_str to a time object
            service_time = datetime.strptime(service_time_str, '%H:%M').time()

            # Define allowed time range
            min_time = time(6, 0)    # 6:00 AM
            max_time = time(16, 30)  # 4:30 PM

            if not (min_time <= service_time <= max_time):
                flash('Service time must be between 6:00 AM and 4:30 PM.', 'danger')
                return redirect(url_for('checkout'))
        except ValueError:
            flash('Invalid service time format.', 'danger')
            return redirect(url_for('checkout'))

        # Validate payment method
        if not payment_method:
            flash('Please select a payment method.', 'warning')
            return redirect(url_for('checkout'))

        # Determine initial status
        initial_status = 'ordered'  # Default status for new orders

        # Convert service_date to datetime.datetime
        service_datetime = datetime.combine(service_date, service_time)

        # Process the order
        order = {
            'user': current_user.id,
            'products': session['cart'],
            'total': total,
            'order_date': datetime.now(),
            'service_date': service_datetime,  # Now a datetime.datetime object
            'service_time': service_time_str,  # Stored as 'HH:MM' string
            'payment_method': payment_method,
            'status': initial_status,
            'address': {
                'street_address': user_address.get('street_address') if user_address else '',
                'unit_apt': user_address.get('unit_apt') if user_address else '',
                'city': user_address.get('city') if user_address else ''
            },
            'creation_date': datetime.utcnow()
        }
        orders_collection.insert_one(order)

        # Optional: Send confirmation email
        try:
            send_order_confirmation_email(current_user.id, order, products_in_cart)
            flash('Your order has been placed successfully!', 'success')
        except Exception as e:
            app.logger.error(f"Failed to send confirmation email: {e}")
            flash('Your order has been placed, but we could not send a confirmation email.', 'warning')

        # Clear the cart
        session.pop('cart', None)

        return redirect(url_for('customer_home'))
    else:
        # Set default service date to tomorrow
        default_service_date = (datetime.today() + timedelta(days=1)).strftime('%Y-%m-%d')
        return render_template(
            'customer/checkout.html',
            products=products_in_cart,
            total=total,
            default_service_date=default_service_date,
            user_address=user_address  # Pass user_address to the template
        )

# Customer Login Route
@app.route('/customer/login', methods=['GET', 'POST'])
def customer_login():
    form = CustomerLoginForm()
    if form.validate_on_submit():
        # Authenticate customer
        user = users_collection.find_one({'email': form.email.data, 'user_type': 'customer'})
        if user and bcrypt.check_password_hash(user['password'], form.password.data):
            user_obj = User(user['email'], user['user_type'])
            login_user(user_obj)
            flash('Logged in successfully as customer.', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('customer_home'))
        else:
            flash('Invalid email or password.', 'danger')
    return render_template('customer/login.html', form=form)

#My Orders Page Routes 
@app.route('/customer/my_orders')
@login_required
def my_orders():
    user_email = current_user.id  # 'id' is set to email in the User class
    user_type = current_user.user_type

    if user_type != 'customer':
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('customer_home'))
    
    user_orders = list(orders_collection.find({'user': user_email}).sort('order_date', -1))
    
    # Enrich orders with product details and technician's name
    for order in user_orders:
        # Fetch product details
        order['product_details'] = []
        for product_id in order['products']:
            product = products_collection.find_one({'_id': ObjectId(product_id)})
            if product:
                order['product_details'].append(product)
        
        # Fetch technician's name if the order is scheduled
        if order.get('status', '').lower() == 'scheduled' and order.get('scheduled_by'):
            tech_user = users_collection.find_one({'username': order['scheduled_by']})
            order['scheduled_by_name'] = tech_user.get('name', 'Technician') if tech_user else 'Technician'
        else:
            order['scheduled_by_name'] = 'Not scheduled yet'
    
    return render_template('customer/my_orders.html', orders=user_orders)



#Customer Register Route

@app.route('/customer/register', methods=['GET', 'POST'])
def register():
    form = RegistrationForm()  # Ensure you have a RegistrationForm defined
    if form.validate_on_submit():
        email = form.email.data.lower().strip()
        password = form.password.data
        # Add other form fields as necessary

        # Check if the email already exists
        existing_user = users_collection.find_one({'email': email})
        if existing_user:
            flash('Email already registered. Please log in.', 'danger')
            logger.warning(f"Attempted duplicate registration for email: {email}")
            return redirect(url_for('customer_login'))  # Ensure 'customer_login' route exists

        # Proceed to create a new user
        hashed_pw = generate_password_hash(password)
        user = {
            'email': email,
            'password': hashed_pw,
            # Include other necessary fields like name, etc.
        }

        try:
            users_collection.insert_one(user)
            flash('Account created successfully! Please log in.', 'success')
            logger.info(f"New user created: {email}")

            # Optionally, log the user in immediately
            user_obj = User(user['email'], user.get('user_type', 'customer'))  # Ensure you have a User class
            login_user(user_obj)

            return redirect(url_for('customer_home'))  # Redirect to a home/dashboard page
        except DuplicateKeyError:
            flash('Email already registered. Please log in.', 'danger')
            logger.warning(f"Duplicate key error on registration for email: {email}")
            return redirect(url_for('customer_login'))
        except Exception as e:
            flash('An error occurred while creating your account. Please try again.', 'danger')
            logger.error(f"Error creating user {email}: {e}")
            return redirect(url_for('register'))

    return render_template('customer/register.html', form=form)
#Routes For Admin\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\
#Admin Page Route
@app.route('/admin/main')
@login_required
@admin_required
def admin_main():
    try:
        # **1. Fetch All Estimate Requests**
        requests = list(estimaterequests_collection.find())

        # **2. Pagination Parameters**
        page = request.args.get('page', 1, type=int)  # Current page number
        per_page = 20  # Number of orders per page

        # **3. Fetch Total Number of Orders**
        total_orders = orders_collection.count_documents({})
        total_pages = (total_orders + per_page - 1) // per_page  # Ceiling division to get total pages

        # **4. Fetch Orders for the Current Page**
        orders = list(
            orders_collection.find()
            .sort('order_date', -1)  # Sort by order_date descending
            .skip((page - 1) * per_page)  # Skip orders for previous pages
            .limit(per_page)  # Limit to orders per page
        )

        # **5. Enrich Orders with Additional Details**
        for order in orders:
            # Determine if the order is a guest order or a customer order
            is_guest = order.get('is_guest', False)
            order['order_type'] = 'Guest Order' if is_guest else 'Customer Order'

            if is_guest:
                # For guest orders, fetch the salesperson's details
                salesperson_id = order.get('salesperson')
                if salesperson_id:
                    salesperson = users_collection.find_one({'username': salesperson_id, 'user_type': 'sales'})
                    order['salesperson_name'] = salesperson.get('name', 'Unknown') if salesperson else 'Unknown'
                else:
                    order['salesperson_name'] = 'Not Assigned'
            else:
                # For customer orders, fetch the user's email
                user = users_collection.find_one({'email': order.get('user')})
                order['user_email'] = user['email'] if user else 'Unknown'

            # Ensure dates are datetime objects
            for date_field in ['order_date', 'service_date']:
                if isinstance(order.get(date_field), str):
                    try:
                        if date_field == 'service_date':
                            order[date_field] = datetime.strptime(order[date_field], '%Y-%m-%d')
                        else:
                            order[date_field] = datetime.strptime(order[date_field], '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        app.logger.error(f"Invalid {date_field} format for order ID {order.get('_id')}: {order.get(date_field)}")
                        order[date_field] = None  # Handle invalid date formats as needed

            # Get product details
            product_ids = [ObjectId(pid) for pid in order.get('products', [])]
            products = list(products_collection.find({'_id': {'$in': product_ids}}))
            order['product_details'] = products

        # **6. Pass Variables to the Template**
        return render_template(
            'admin/main.html',
            requests=requests,
            orders=orders,
            page=page,
            per_page=per_page,
            total_pages=total_pages
        )
    except Exception as e:
        app.logger.error(f"Error in admin_main route: {e}")
        flash('An error occurred while fetching orders.', 'danger')
        return redirect(url_for('home'))


    
#View order Route

@app.route('/admin/view_order/<order_id>')
@login_required
@admin_required
def view_order(order_id):
    try:
        # Validate and convert the order_id to ObjectId
        try:
            order_obj_id = ObjectId(order_id)
        except InvalidId:
            flash('Invalid order ID.', 'danger')
            return redirect(url_for('admin_main'))

        # Fetch the order from the database
        order = orders_collection.find_one({'_id': order_obj_id})
        if not order:
            flash('Order not found.', 'danger')
            return redirect(url_for('admin_main'))

        # Determine if the order is a guest order or a customer order
        is_guest = order.get('is_guest', False)
        order['order_type'] = 'Guest Order' if is_guest else 'Customer Order'

        if is_guest:
            # For guest orders, fetch the salesperson's details
            salesperson_id = order.get('salesperson')
            if salesperson_id:
                salesperson = users_collection.find_one({'username': salesperson_id, 'user_type': 'sales'})
                order['salesperson_name'] = salesperson.get('name', 'Unknown') if salesperson else 'Unknown'
            else:
                order['salesperson_name'] = 'Not Assigned'
        else:
            # For customer orders, fetch the user's details
            user = users_collection.find_one({'email': order.get('user')})
            order['user_email'] = user['email'] if user else 'Unknown'
            order['user_name'] = user.get('name', 'N/A') if user else 'N/A'
            order['user_phone'] = user.get('phone_number', 'N/A') if user else 'N/A'
            order['user_address'] = user.get('address', {})

        # Fetch the user who scheduled the order using username
        scheduled_by_username = order.get('scheduled_by')
        if scheduled_by_username:
            scheduled_by_user = users_collection.find_one({'username': scheduled_by_username})
            if scheduled_by_user:
                order['scheduled_by_name'] = scheduled_by_user.get('name', 'Unknown')
                order['scheduled_by_email'] = scheduled_by_user.get('email', 'Unknown')
            else:
                order['scheduled_by_name'] = 'Unknown'
                order['scheduled_by_email'] = 'Unknown'
        else:
            order['scheduled_by_name'] = 'Not Scheduled'
            order['scheduled_by_email'] = ''

        # Ensure dates are datetime objects
        for date_field in ['order_date', 'service_date']:
            if isinstance(order.get(date_field), str):
                try:
                    if date_field == 'service_date':
                        order[date_field] = datetime.strptime(order[date_field], '%Y-%m-%d')
                    else:
                        order[date_field] = datetime.strptime(order[date_field], '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    app.logger.error(f"Invalid {date_field} format for order ID {order.get('_id')}: {order.get(date_field)}")
                    order[date_field] = None  # Handle invalid date formats as needed

        # Fetch product details
        product_ids = [ObjectId(pid) for pid in order.get('products', [])]
        products = list(products_collection.find({'_id': {'$in': product_ids}}))
        order['product_details'] = products

        return render_template('admin/view_order.html', order=order)
    except Exception as e:
        app.logger.error(f"Error in view_order route: {e}")
        flash('An error occurred while fetching the order details.', 'danger')
        return redirect(url_for('admin_main'))


#View Users Route
@app.route('/admin/view_user/<user_id>')
@login_required
@admin_required
def view_user(user_id):
    user = users_collection.find_one({'_id': ObjectId(user_id)})
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('manage_users'))

    # Ensure creation_date is a datetime object
    if 'creation_date' in user and isinstance(user['creation_date'], str):
        # If it's stored as a string, parse it back to datetime
        user['creation_date'] = datetime.strptime(user['creation_date'], '%Y-%m-%d %H:%M:%S')

    return render_template('admin/view_user.html', user=user)

#Delete User Route
@app.route('/admin/delete/<user_id>', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    if user_id == current_user.id:
        flash('You cannot delete your own account.', 'danger')
        return redirect(url_for('manage_users'))
    users_collection.delete_one({'_id': ObjectId(user_id)})
    flash('User deleted successfully.', 'success')
    return redirect(url_for('manage_users'))

@app.route('/admin/manage_users')
@login_required
@admin_required
def manage_users():
    try:
        # **1. Pagination Parameters**
        page = request.args.get('page', 1, type=int)
        per_page = 20

        # **2. Search Parameter (Optional)**
        search_query = request.args.get('search', '').strip()

        # **3. Build MongoDB Query**
        query = {}
        if search_query:
            # Search by email or ID
            try:
                query = {
                    '$or': [
                        {'email': {'$regex': search_query, '$options': 'i'}},
                        {'_id': ObjectId(search_query)}
                    ]
                }
            except InvalidId:
                # If search_query is not a valid ObjectId, ignore ID search
                query = {'email': {'$regex': search_query, '$options': 'i'}}

        # **4. Fetch Total Number of Users Matching the Query**
        total_users = users_collection.count_documents(query)
        total_pages = (total_users + per_page - 1) // per_page

        # **5. Fetch Users for the Current Page**
        users = list(
            users_collection.find(query)
            .sort('creation_date', -1)  # Sort by creation_date descending
            .skip((page - 1) * per_page)
            .limit(per_page)
        )

        return render_template(
            'admin/manage_users.html',
            users=users,
            page=page,
            per_page=per_page,
            total_pages=total_pages
        )
    except Exception as e:
        app.logger.error(f"Error in manage_users route: {e}")
        flash('An error occurred while fetching users.', 'danger')
        return redirect(url_for('admin_main'))
#Extra

@app.before_request
def redirect_to_https():
    if ENV == 'production':
        # Check if the request is already secure
        if not request.is_secure and request.headers.get('X-Forwarded-Proto', 'http') != 'https':
            url = request.url.replace("http://", "https://", 1)
            return redirect(url, code=301)
        


def is_safe_url(target):
    """Check if the target URL is safe for redirection."""
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc


@app.template_filter('format_time')
def format_time_filter(time_str):
    """
    Converts a 'HH:MM' string into 'h:MM AM/PM' format.
    """
    try:
        time_obj = datetime.strptime(time_str, '%H:%M')
        return time_obj.strftime('%I:%M %p').lstrip('0')  # Removes leading zero
    except (ValueError, TypeError):
        return 'Invalid Time'

if __name__ == '__main__':
    app.run(debug=True)
 


