from flask import Flask, render_template, request, redirect, url_for, session, flash
from pymongo import MongoClient
from flask_bcrypt import Bcrypt
from functools import wraps
from flask_mail import Mail, Message
from bson.objectid import ObjectId
from urllib.parse import urlparse, urljoin
from datetime import datetime
import os



app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')

bcrypt = Bcrypt(app)
#Mongo DB SETUP
client = MongoClient("mongodb+srv://yeurys:ZvTt25OmDOp24yCW@cfac.8ba8p.mongodb.net/cfacdb?retryWrites=true&w=majority&appName=cfac", tls=True, tlsAllowInvalidCertificates=True)
db = client["cfacdb"]
users_collection = db["users"]  
estimaterequests_collection = db["estimaterequests"]  
products_collection = db["products"]


# Flask-Mail SETUP
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('EMAIL_USER')  # Get email username from environment
app.config['MAIL_PASSWORD'] = os.getenv('EMAIL_PASSWORD')  # Get email password from environment
mail = Mail(app)


#SINGLE DEFS

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

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
        if 'username' not in session or session.get('user_type') != 'customer':
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
    if 'user_type' in session:
        # Determine where to redirect based on user_type
        user_type = session['user_type']
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
        username = request.form['username']
        password = request.form['password'].encode('utf-8')
        next_page = request.form.get('next')

        user = users_collection.find_one({'username': username})
        
        if user and bcrypt.check_password_hash(user['password'], password):
            session['username'] = username
            session['user_type'] = user['user_type']  # Store user type in session

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
            flash('Invalid username or password', 'danger')
    
    # For GET requests, render the login form
    # Optionally, you can handle 'next' from query parameters
    next_page = request.args.get('next')
    return render_template('login.html', next=next_page)

@app.route('/logout')
def logout():
    session.pop('username', None)
    session.pop('user_type', None)
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
@login_required
def customerpage():
    products = list(products_collection.find())  # Assuming you have products in your DB
    return render_template('customerpage.html', products=products)




@app.route('/add_to_cart/<product_id>')
def add_to_cart(product_id):
    if 'cart' not in session:
        session['cart'] = []

    session['cart'].append(product_id)
    flash('Product added to cart!', 'success')
    return redirect(url_for('cart'))



@app.route('/cart')
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
        if 'username' not in session:
            flash('Please log in to place your order.', 'warning')
            return redirect(url_for('checkout'))

        # Process the order
        # Placeholder for payment processing
        # In a real application, integrate with a payment gateway like Stripe

        # Create an order
        order = {
            'user': session.get('username', 'Guest'),
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


# app.py (Relevant sections)

@app.route('/register', methods=['GET', 'POST'])
def register():
    next_page = request.args.get('next')  # Capture 'next' from query parameters
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        next_page_form = request.form.get('next')  # Capture 'next' from form data

        if not username or not password or not confirm_password:
            flash('Please fill out all fields.', 'warning')
            return redirect(url_for('register', next=next_page))

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('register', next=next_page))

        if users_collection.find_one({'username': username}):
            flash('Username already exists. Please choose another.', 'danger')
            return redirect(url_for('register', next=next_page))

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')

        # Create a new user with user_type set to 'customer'
        user = {
            'username': username,
            'password': hashed_password,
            'user_type': 'customer'
        }

        try:
            users_collection.insert_one(user)
            flash('Account created successfully! You can now log in.', 'success')
            
          

            # Determine the redirect target
            if next_page and is_safe_url(next_page_form or next_page):
                return redirect(next_page_form or next_page)
            else:
                return redirect(url_for('customerpage'))
        except Exception as e:
            flash('An error occurred while creating your account. Please try again.', 'danger')
            print("An error occurred while adding the user:", e)

    # For GET requests, render the registration form with 'next' parameter
    return render_template('register.html', next=next_page)




# Use this function to add new users
if __name__ == '__main__':
    username = input("Enter username: ").strip()
    password = input("Enter password: ").strip()
    user_type = input("Enter user type ('admin' or 'employee'): ").strip().lower()
    
    if user_type not in ['admin', 'employee']:
        print("Invalid user type. Must be 'admin' or 'employee'.")
    else:
        add_user(username, password, user_type)
        app.run(debug=True)
