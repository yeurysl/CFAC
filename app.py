from flask import Flask, render_template, request, redirect, url_for, session, flash
from pymongo import MongoClient
from flask_bcrypt import Bcrypt
from functools import wraps
from flask_mail import Mail, Message
from bson.objectid import ObjectId
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


def calculate_cart_total(products):
    total = sum(product['price'] for product in products)
    return total




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
        if session['user_type'] == 'admin':
            return redirect(url_for('adminpage'))
        elif session['user_type'] == 'employee':
            return redirect(url_for('employeepage'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password'].encode('utf-8')
        user = users_collection.find_one({'username': username})
        
        if user and bcrypt.check_password_hash(user['password'], password):
            session['username'] = username
            session['user_type'] = user['user_type']  # Store user type in session

            # Redirect based on user type
            if user['user_type'] == 'admin':
                return redirect(url_for('adminpage'))
            elif user['user_type'] == 'employee':
                return redirect(url_for('employeepage'))
            else:
                flash('User type is not recognized.', 'danger')
                return redirect(url_for('login'))
        else:
            flash('Invalid username or password', 'danger')
    
    return render_template('login.html')




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




@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    if 'cart' not in session or not session['cart']:
        flash('Your cart is empty.', 'info')
        return redirect(url_for('products'))

    product_ids = [ObjectId(id) for id in session['cart']]
    products_in_cart = list(products_collection.find({'_id': {'$in': product_ids}}))
    total = calculate_cart_total(products_in_cart)

    if request.method == 'POST':
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
        return redirect(url_for('products'))

    return render_template('checkout.html', products=products_in_cart, total=total)




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
