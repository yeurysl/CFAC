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
from datetime import datetime
import os


if os.getenv('FLASK_ENV') == 'development':
    load_dotenv()


app = Flask(__name__)

# Apply ProxyFix to handle Heroku's proxy headers
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

app.secret_key = os.getenv('SECRET_KEY')

bcrypt = Bcrypt(app)
#Mongo DB SETUP

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
app.config['MAIL_USERNAME'] = os.getenv('EMAIL_USER')  # Get email username from environment
app.config['MAIL_PASSWORD'] = os.getenv('EMAIL_PASSWORD')  # Get email password from environment
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

#SINGLE DEFS


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('user_type') != 'admin':
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

def employee_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('user_type') != 'employee':
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

def customer_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in') or session.get('user_type') != 'customer':
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function



def calculate_cart_total(products):
    total = sum(product['price'] for product in products)
    return total


def is_safe_url(target):
    """Check if the target URL is safe for redirection."""
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc




#ROUTES



@app.route('/base')
def base():
    return render_template('/base.html')


@app.route('/')
def home():
    products = list(products_collection.find())  # Assuming you have products in your DB
    return render_template('home.html', products=products)





@app.route('/submit', methods=['POST'])
def submit():
    name = request.form.get('name')
    address = request.form.get('address')
    phone = request.form.get('phone')
    # Get the current date and time
    timestamp = datetime.now()

    if not name or not address or not phone:
        flash('Please fill out all fields.', 'warning')
        return redirect(url_for('home'))

    data = {
        'name': name,
        'address': address,
        'phone': phone,
         "date_requested": timestamp 
    }

    try:
        estimaterequests_collection.insert_one(data)
        print("Data inserted successfully.")
        flash('Your information has been successfully submitted!', 'success')

          # Send an email notification to you
        msg = Message(
            "New Estimate Request Submission",
            sender="yeurys@cfautocare.biz", 
            recipients=["yeurysl17@gmail.com"]
        )
        msg.body = (
            f"New Estimate Request:\n\n"
            f"Name: {name}\n"
            f"Address: {address}\n"
            f"Phone: {phone}\n"
            f"Date Requested: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        mail.send(msg)
        print("Notification email sent successfully.")
    except Exception as e:
        print("An error occurred while inserting data:", e)
        flash('An error occurred while submitting your information. Please try again.', 'danger')

    return redirect(url_for('home'))



@app.route('/aboutus')
def about():
    return render_template('/aboutus.html')

@app.route('/careers')
def career():
    return render_template('/careers.html')



@app.route('/header')
def header():
    return render_template('/header.html')





@app.route('/login', methods=['GET', 'POST'])
def login():
    # Check if the user is already logged in
    if current_user.is_authenticated:
        # Determine where to redirect based on user_type
        user_type = current_user.user_type
        if user_type == 'admin':
            return redirect(url_for('adminpage'))
        elif user_type == 'employee':
            return redirect(url_for('employeepage'))
        elif user_type == 'customer':
            return redirect(url_for('customerpage'))
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
                    return redirect(url_for('adminpage'))
                elif user['user_type'] == 'employee':
                    return redirect(url_for('employeepage'))
                elif user['user_type'] == 'customer':
                    return redirect(url_for('customerpage'))
                else:
                    flash('User type is not recognized.', 'danger')
                    return redirect(url_for('login'))
        else:
            flash('Invalid email or password', 'danger')
    
    # For GET requests, render the login form
    # Optionally, you can handle 'next' from query parameters
    next_page = request.args.get('next')
    return render_template('login.html', next=next_page)




@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('home'))


@app.route('/protected')
@login_required
def protected():
    return "This is a protected page!"




@app.route('/adminpage')
@login_required
@admin_required
def adminpage():
    # Fetch all documents from the estimaterequests collection
    requests = estimaterequests_collection.find()  # Retrieve all estimate requests
    
    # Pass the data to the admin page template
    return render_template('adminpage.html', requests=requests)



@app.route('/employeepage')
@login_required
@employee_required
def employeepage():
    return render_template('/employeepage.html')


@app.route('/customerpage')
@customer_required
def customerpage():
    products = list(products_collection.find())  # Assuming you have products in your DB
    return render_template('customerpage.html', products=products)




@app.route('/add_to_cart/<product_id>')
@login_required
@customer_required 
def add_to_cart(product_id):
    if 'cart' not in session:
        session['cart'] = []

    session['cart'].append(product_id)
    flash('Product added to cart!', 'success')
    return redirect(url_for('cart'))



@app.route('/cart')
@login_required
@customer_required 
def cart():
    if 'cart' not in session or not session['cart']:
        flash('Your cart is empty.', 'info')
        return render_template('cart.html', products=[])

    product_ids = [ObjectId(id) for id in session['cart']]
    products_in_cart = list(products_collection.find({'_id': {'$in': product_ids}}))
    total = calculate_cart_total(products_in_cart)
    return render_template('cart.html', products=products_in_cart, total=total)

@app.route('/products')
def products():
    # Your logic to display products
    products = list(products_collection.find())
    return render_template('products.html', products=products)




@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    if 'cart' not in session or not session['cart']:
        flash('Your cart is empty.', 'info')
        return redirect(url_for('home'))

    product_ids = [ObjectId(id) for id in session['cart']]
    products_in_cart = list(products_collection.find({'_id': {'$in': product_ids}}))
    total = calculate_cart_total(products_in_cart)

    if request.method == 'POST':
        if 'email' not in session:
            flash('Please log in to place your order.', 'warning')
            return redirect(url_for('checkout'))

        # Process the order
        # Placeholder for payment processing
        # In a real application, integrate with a payment gateway like Stripe

        # Create an order
        order = {
            'user': session.get('email', 'Guest'),
            'products': session['cart'],
            'total': total,
            'date': datetime.now()
        }
        orders_collection = db['orders']
        orders_collection.insert_one(order)

        # Clear the cart
        session.pop('cart', None)

        flash('Your order has been placed successfully!', 'success')
        return redirect(url_for('home'))

    return render_template('checkout.html', products=products_in_cart, total=total)






@app.route('/my_orders')
@login_required
def my_orders():
    user_email = current_user.id  # 'id' is set to email in the User class
    user_type = current_user.user_type

    if user_type != 'customer':
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('home'))
    
    user_orders = list(orders_collection.find({'user': user_email}).sort('date', -1))
    
    # Enrich orders with product details
    for order in user_orders:
        order['product_details'] = []
        for product_id in order['products']:
            product = products_collection.find_one({'_id': ObjectId(product_id)})
            if product:
                order['product_details'].append(product)
    
    return render_template('my_orders.html', orders=user_orders)






# app.py (Registration Route)

@app.route('/register', methods=['GET', 'POST'])
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
                return redirect(url_for('customerpage'))
        except Exception as e:
            flash('An error occurred while creating your account. Please try again.', 'danger')
            app.logger.error(f"Error inserting user: {e}")
            return redirect(url_for('register', next=next_page))
    
    # For GET requests, render the registration form with 'next' parameter
    return render_template('register.html', next=next_page)



# Use this function to add new users
if __name__ == '__main__':
    email = input("Enter email: ").strip()
    password = input("Enter password: ").strip()
    user_type = input("Enter user type ('admin' or 'employee'): ").strip().lower()
    
    if user_type not in ['admin', 'employee']:
        print("Invalid user type. Must be 'admin' or 'employee'.")
    else:
        add_user(email, password, user_type)
        app.run(debug=True)



