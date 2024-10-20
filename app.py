from flask import Flask, render_template, request, redirect, url_for, session, flash
from pymongo import MongoClient
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from functools import wraps
from flask_mail import Mail, Message
from werkzeug.middleware.proxy_fix import ProxyFix
from bson.objectid import ObjectId
from urllib.parse import urlparse, urljoin
from datetime import datetime, timedelta
import os


ENV = os.getenv('ENV', 'development')   

load_dotenv()

app = Flask(__name__)

# Apply ProxyFix to handle Heroku's proxy headers
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

app.secret_key = os.getenv('SECRET_KEY')

bcrypt = Bcrypt(app)


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
login_manager.login_view = 'login'  # Redirect to 'login' for @login_required




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
    def __init__(self, email, user_type):
        self.id = email
        self.user_type = user_type

# User Loader Callback
@login_manager.user_loader
def load_user(user_id):
    user = users_collection.find_one({'email': user_id})
    if user:
        return User(user['email'], user['user_type'])
    return None

#SINGLE DEFS\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\

#FORLOGINS
def admin_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if current_user.user_type != 'admin':
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function
def employee_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if current_user.user_type != 'employee':
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function
def customer_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
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
    products = list(products_collection.find())  # Assuming you have products in your DB
    return render_template('home.html', products=products)
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
#Login Route
@app.route('/login', methods=['GET', 'POST'])
def login():
    # Check if the user is already logged in
    if current_user.is_authenticated:
        # Determine where to redirect based on user_type
        user_type = current_user.user_type
        if user_type == 'admin':
            return redirect(url_for('admin_main'))
        elif user_type == 'employee':
            return redirect(url_for('employee_main'))
        elif user_type == 'customer':
            return redirect(url_for('customer_home'))
        else:
            flash('User type is not recognized.', 'danger')
            return redirect(url_for('home'))

    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']
        next_page = request.form.get('next')

        user = users_collection.find_one({'email': email})
        
        if user and bcrypt.check_password_hash(user['password'], password):
            user_obj = User(user['email'], user.get('user_type', 'customer'))
            login_user(user_obj)
            flash('Logged in successfully!', 'success')

            # Determine the redirect target
            if next_page and is_safe_url(next_page):
                return redirect(next_page)
            else:
                # Redirect based on user type
                if user['user_type'] == 'admin':
                    return redirect(url_for('admin_main'))
                elif user['user_type'] == 'employee':
                    return redirect(url_for('employee_main'))
                elif user['user_type'] == 'customer':
                    return redirect(url_for('customer_home'))
                else:
                    flash('User type is not recognized.', 'danger')
                    return redirect(url_for('login.html'))
        else:
            flash('Invalid email or password', 'danger')
    
    # For GET requests, render the login form
    # Optionally, you can handle 'next' from query parameters
    next_page = request.args.get('next')
    return render_template('login.html', next=next_page)
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


#Routes for Customers\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\
#Customer Page Route
@app.route('/customer/home')
@customer_required
def customer_home():
    products = list(products_collection.find())  # Assuming you have products in your DB
    return render_template('customer/home.html', products=products)

#Cart Page Route
@app.route('/customer/cart')
@login_required
@customer_required
def cart():
    if 'cart' not in session or not session['cart']:
        flash('Your cart is empty.', 'info')
        return render_template('customer/cart.html', products=[])

    product_ids = [ObjectId(id) for id in session['cart']]
    products_in_cart = list(products_collection.find({'_id': {'$in': product_ids}}))
    total = calculate_cart_total(products_in_cart)
    return render_template('customer/cart.html', products=products_in_cart, total=total)

#ATC Route for Function
@app.route('/customer/add_to_cart/<product_id>')
@login_required
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
#Registration Route
@app.route('/customer/register', methods=['GET', 'POST'])
def register():
    next_page = request.args.get('next')
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        next_page_form = request.form.get('next')
        
        # Basic Validation
        if not email or not password or not confirm_password:
            flash('Please fill out all fields.', 'warning')
            return redirect(url_for('register', next=next_page))
        
        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('register', next=next_page))
        
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
            'user_type': 'customer'  # or assign based on role
        }
        
        try:
            users_collection.insert_one(user)
            flash('Account created successfully!', 'success')
            
            # Automatically log in the user after registration
            user_obj = User(user['email'], user['user_type'])
            login_user(user_obj)
            
            # Redirect based on 'next' parameter
            if next_page and is_safe_url(next_page_form or next_page):
                return redirect(next_page_form or next_page)
            else:
                return redirect(url_for('customer_home'))
        except Exception as e:
            flash('An error occurred while creating your account. Please try again.', 'danger')
            app.logger.error(f"Error inserting user: {e}")
            return redirect(url_for('register', next=next_page))
    
    # For GET requests, render the registration form with 'next' parameter
    return render_template('customer/register.html', next=next_page)






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


#Edit Users Route
@app.route('/admin/edit_users/<user_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(user_id):
    user = users_collection.find_one({'_id': ObjectId(user_id)})
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('manage_users.html'))

    if request.method == 'POST':
        updated_data = {
            'email': request.form['email'],
            'user_type': request.form['user_type']  # Make sure to have this field in your form
        }
        users_collection.update_one({'_id': ObjectId(user_id)}, {'$set': updated_data})
        flash('User updated successfully.', 'success')
        return redirect(url_for('manage_users'))
    return render_template('edit_user', user=user)
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
 


