from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from pymongo import MongoClient
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf import CSRFProtect
from flask_wtf.csrf import generate_csrf
from forms import RegistrationForm, RemoveFromCartForm, CustomerLoginForm, EmployeeLoginForm, UpdateAccountForm
from functools import wraps
from flask_mail import Mail, Message
from werkzeug.middleware.proxy_fix import ProxyFix
from bson.objectid import ObjectId
from urllib.parse import urlparse, urljoin
from datetime import datetime, timedelta
from dateutil import parser
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
    # Attempt to find the user by username (for employees/admins)
    user = users_collection.find_one({
        'username': user_id,
        'user_type': {'$in': ['employee', 'admin']}
    })
    if user:
        return User(user['username'], user['user_type'])
    
    # Attempt to find the user by email (for customers)
    user = users_collection.find_one({
        'email': user_id,
        'user_type': 'customer'
    })
    if user:
        return User(user['email'], user['user_type'])
    
    return None

#SINGLE DEFS\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\

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

def employee_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in as an employee to access this page.', 'warning')
            return redirect(url_for('employee_admin_login', next=request.url))
        if current_user.user_type != 'employee':
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

    if user_type in ['employee', 'admin']:
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
                if user_type in ['employee', 'admin']:
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
                app.logger.error(f"Error updating user: {e}")
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


#Routes for Employees\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\
# Routes for Employees
@app.route('/employee/main')
@login_required
@employee_required
def employee_main():
    try:
        # Define the filter to fetch only 'ordered' orders
        filter_query = {'status': 'ordered'}
        
        # Fetch all 'ordered' orders sorted by order_date descending
        orders = list(orders_collection.find(filter_query).sort('order_date', -1))

        # Enrich orders with user and product details
        for order in orders:
            # Get user details
            user = users_collection.find_one({'email': order['user']})
            order['user_email'] = user['email'] if user else 'Unknown'

            # Ensure dates are datetime objects
            if isinstance(order['order_date'], str):
                order['order_date'] = datetime.strptime(order['order_date'], '%Y-%m-%d %H:%M:%S')
            if isinstance(order['service_date'], str):
                order['service_date'] = datetime.strptime(order['service_date'], '%Y-%m-%d')

            # Get product details
            product_ids = [ObjectId(pid) for pid in order['products']]
            products = list(products_collection.find({'_id': {'$in': product_ids}}))
            order['product_details'] = products

        return render_template('employee/main.html', orders=orders)
    except Exception as e:
        app.logger.error(f"Error fetching orders: {e}")
        flash('An error occurred while fetching orders.', 'danger')
        return redirect(url_for('home'))




@app.route('/employee/my_schedule')
@login_required
@employee_required  # Ensure this decorator is correctly implemented
def my_schedule():
    try:
        # Determine the unique identifier for the current employee
        # Replace 'username' with the appropriate attribute if different
        employee_identifier = current_user.id  # e.g., 'john_doe'

        # Define the filter to fetch orders with status 'scheduled' and scheduled_by current employee
        filter_query = {
            'status': 'scheduled',
            'scheduled_by': employee_identifier
        }

        # Fetch all matching orders sorted by service_date ascending
        scheduled_orders_cursor = orders_collection.find(filter_query).sort('service_date', 1)

        scheduled_orders = list(scheduled_orders_cursor)

        # Enrich orders with product details
        for order in scheduled_orders:
            product_ids = [ObjectId(pid) for pid in order.get('products', [])]
            products = list(products_collection.find({'_id': {'$in': product_ids}}))
            order['product_details'] = products

            # Format dates if necessary
            if isinstance(order.get('order_date'), str):
                order['order_date'] = datetime.strptime(order['order_date'], '%Y-%m-%d %H:%M:%S')
            if isinstance(order.get('service_date'), str):
                order['service_date'] = datetime.strptime(order['service_date'], '%Y-%m-%d')

        return render_template('employee/my_schedule.html', orders=scheduled_orders)
    except Exception as e:
        current_app.logger.error(f"Error fetching scheduled orders: {e}")
        flash('An error occurred while fetching your scheduled orders.', 'danger')
        return redirect(url_for('employee_main'))


@app.route('/employee/order/<order_id>/schedule', methods=['POST'])
@login_required
@employee_required  # Assuming you have this decorator defined
def schedule_order(order_id):
    try:
        # Fetch the order by ID
        order = orders_collection.find_one({'_id': ObjectId(order_id)})

        if not order:
            flash('Order not found.', 'danger')
            return redirect(url_for('employee_main'))

        # Check if the current status is 'ordered'
        if order.get('status', '').lower() != 'ordered':
            flash('Only orders with status "ordered" can be scheduled.', 'warning')
            return redirect(url_for('employee_main'))

        # Update the status to 'scheduled' and add 'scheduled_by'
        orders_collection.update_one(
            {'_id': ObjectId(order_id)},
            {
                '$set': {
                    'status': 'scheduled',
                    'scheduled_by': current_user.id  # Adjust based on your user model
                }
            }
        )

        flash(f'Order {order_id} has been scheduled successfully by {current_user.id}.', 'success')
        return redirect(url_for('employee_main'))
    except Exception as e:
        app.logger.error(f"Error scheduling order {order_id}: {e}")
        flash('An error occurred while scheduling the order.', 'danger')
        return redirect(url_for('employee_main'))



# Employee/Admin Login Route
@app.route('/employee_admin_login', methods=['GET', 'POST'])
def employee_admin_login():
    form = EmployeeLoginForm()
    if form.validate_on_submit():
        # Authenticate employee or admin using username
        user = users_collection.find_one({'username': form.username.data, 'user_type': {'$in': ['employee', 'admin']}})
        if user and bcrypt.check_password_hash(user['password'], form.password.data):
            user_obj = User(user['username'], user['user_type'])  # Assuming User ID is username
            login_user(user_obj)
            flash(f'Logged in successfully as {user["user_type"]}.', 'success')
            next_page = request.args.get('next')
            # Redirect to appropriate dashboard
            if user['user_type'] == 'admin':
                return redirect(next_page or url_for('admin_main'))
            else:
                return redirect(next_page or url_for('employee_main'))
        else:
            flash('Invalid username or password.', 'danger')
    return render_template('employee_admin_login.html', form=form)

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
@customer_required
def cart():
    if 'cart' not in session or not session['cart']:
        flash('Your cart is empty.', 'info')
        return render_template('customer/cart.html', products=[], forms={})

    product_ids = [ObjectId(id) for id in session['cart']]
    products_in_cart = list(products_collection.find({'_id': {'$in': product_ids}}))
    total = calculate_cart_total(products_in_cart)

    # Create a dictionary of forms, one for each product
    forms = {}
    for product in products_in_cart:
        form = RemoveFromCartForm()
        form.product_id.data = str(product['_id'])
        forms[str(product['_id'])] = form

    if request.method == 'POST':
        # Retrieve the product_id from the submitted form
        product_id = request.form.get('product_id')
        if product_id in session.get('cart', []):
            session['cart'].remove(product_id)
            flash('Item removed from your cart.', 'success')
        else:
            flash('Item not found in your cart.', 'warning')
        return redirect(url_for('cart'))

    return render_template('customer/cart.html', products=products_in_cart, total=total, forms=forms)
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
@customer_required
def checkout():
    if 'cart' not in session or not session['cart']:
        flash('Your cart is empty.', 'info')
        return redirect(url_for('customer_home'))

    product_ids = [ObjectId(id) for id in session['cart']]
    products_in_cart = list(products_collection.find({'_id': {'$in': product_ids}}))
    total = calculate_cart_total(products_in_cart)

    if request.method == 'POST':
        # Retrieve service date from the form
        service_date_str = request.form.get('service_date')
        if not service_date_str:
            flash('Please select a service date.', 'warning')
            return redirect(url_for('checkout'))

        # Validate and parse the service date
        try:
            service_date = datetime.strptime(service_date_str, '%Y-%m-%d')
            now = datetime.now()
            if service_date.date() < now.date():
                flash('Service date cannot be in the past.', 'danger')
                return redirect(url_for('checkout'))
        except ValueError:
            flash('Invalid date format.', 'danger')
            return redirect(url_for('checkout'))

        # Determine initial status
        initial_status = 'ordered'  # Default status for new orders

        # Process the order
        order = {
            'user': current_user.id,
            'products': session['cart'],
            'total': total,
            'order_date': datetime.now(),
            'service_date': service_date,
            'status': initial_status  # Add the status field
        }
        orders_collection.insert_one(order)

        # Send confirmation email
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
            default_service_date=default_service_date
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
    
    user_orders = list(orders_collection.find({'user': user_email}).sort('date', -1))
    
    # Enrich orders with product details
    for order in user_orders:
        order['product_details'] = []
        for product_id in order['products']:
            product = products_collection.find_one({'_id': ObjectId(product_id)})
            if product:
                order['product_details'].append(product)
    
    return render_template('customer/my_orders.html', orders=user_orders)

@app.route('/customer/register', methods=['GET', 'POST'])
def register():
    form = RegistrationForm()
    next_page = request.args.get('next')
    
    if form.validate_on_submit():
        # Extract form data
        email = form.email.data.strip().lower()
        password = form.password.data
        name = form.name.data.strip()
        phone_number = form.phone_number.data.strip()
        street_address = form.street_address.data.strip()
        city = form.city.data.strip()
        country = form.country.data.strip()
        zip_code = form.zip_code.data.strip()
        unit_apt = form.unit_apt.data.strip() 
        
        # Check if email already exists
        if users_collection.find_one({'email': email}):
            flash('Email already registered. Please log in.', 'danger')
            return redirect(url_for('login'))
        
        # Hash the password
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        
      # Create the user document
        user = {
            'email': email,
            'password': hashed_password,
            'user_type': 'customer',
            'name': name,
            'phone_number': phone_number,
            'address': {
                'street_address': street_address,
                'unit_apt': unit_apt,
                'city': city,
                'country': country,
                'zip_code': zip_code
            },
            'creation_date': datetime.utcnow()  
        }
        try:
            users_collection.insert_one(user)
            flash('Account created successfully!', 'success')
            
            # Automatically log in the user after registration
            user_obj = User(user['email'], user['user_type'])
            login_user(user_obj)
            
            # Redirect based on 'next' parameter
            if next_page and is_safe_url(next_page):
                return redirect(next_page)
            else:
                return redirect(url_for('customer_home'))
        except Exception as e:
            flash('An error occurred while creating your account. Please try again.', 'danger')
            app.logger.error(f"Error inserting user: {e}")
            return redirect(url_for('register'))
    
    return render_template('customer/register.html', form=form, next=next_page)
#Routes For Admin\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\
#Admin Page Routes
@app.route('/admin/main')
@login_required
@admin_required
def admin_main():
    # Fetch all estimate requests
    requests = list(estimaterequests_collection.find())

    # Fetch all orders from the database
    orders = list(orders_collection.find().sort('order_date', -1))

    # Enrich orders with user and product details
    for order in orders:
        # Get user details
        user = users_collection.find_one({'email': order['user']})
        order['user_email'] = user['email'] if user else 'Unknown'

        # Ensure dates are datetime objects
        if isinstance(order['order_date'], str):
            order['order_date'] = datetime.strptime(order['order_date'], '%Y-%m-%d %H:%M:%S')
        if isinstance(order['service_date'], str):
            order['service_date'] = datetime.strptime(order['service_date'], '%Y-%m-%d')

        # Get product details
        product_ids = [ObjectId(pid) for pid in order['products']]
        products = list(products_collection.find({'_id': {'$in': product_ids}}))
        order['product_details'] = products

    # Pass both requests and orders to the template
    return render_template('admin/main.html', requests=requests, orders=orders)


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
    page = request.args.get('page', 1, type=int)
    per_page = 20
    total_users = users_collection.count_documents({})
    total_pages = (total_users + per_page - 1) // per_page  # Calculate total pages
    users = list(
        users_collection.find()
        .skip((page - 1) * per_page)
        .limit(per_page)
    )
    return render_template(
        'admin/manage_users.html',
        users=users,
        page=page,
        total_users=total_users,
        per_page=per_page,
        total_pages=total_pages  # Pass total_pages to the template
    )





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



if __name__ == '__main__':
    app.run(debug=True)
 


