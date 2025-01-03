from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory
from pymongo import MongoClient
import stripe
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv
from utility import format_us_phone_number, send_postmark_email
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf import CSRFProtect
from flask_wtf.csrf import generate_csrf
from forms import RegistrationForm, RemoveFromCartForm, CustomerLoginForm, EmployeeLoginForm, UpdateAccountForm, GuestOrderForm, PasswordResetRequestForm, PasswordResetForm, EditOrderForm, DeleteOrderForm, SalesProfileForm, CollectPaymentForm, UpdateCompensationStatusForm
from functools import wraps
from werkzeug.middleware.proxy_fix import ProxyFix
import math
from bson.objectid import ObjectId, InvalidId
from pymongo.errors import DuplicateKeyError
from urllib.parse import urlparse, urljoin, quote_plus
from bson.decimal128 import Decimal128, create_decimal128_context
import decimal
from postmarker.core import PostmarkClient
import time
from bson.json_util import dumps, loads
from datetime import datetime, date, timedelta
from dateutil import parser
import phonenumbers
from phonenumbers import NumberParseException
from itsdangerous import URLSafeTimedSerializer, SignatureExpired
from flask import current_app
from twilio.rest import Client
import logging
import re
import os


ENV = os.getenv('ENV', 'development')   




load_dotenv()

app = Flask(__name__)

# Expose Python's zip function to Jinja2 templates
app.jinja_env.globals.update(zip=zip)

# Configure Stripe
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
STRIPE_PUBLISHABLE_KEY = os.getenv('STRIPE_PUBLISHABLE_KEY')


TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')

# Initialize Twilio Client
twilio_client = Client(
    os.getenv('TWILIO_ACCOUNT_SID'),
    os.getenv('TWILIO_AUTH_TOKEN')
)
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')


# Apply ProxyFix to handle Heroku's proxy headers
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

app.secret_key = os.getenv('SECRET_KEY')
app.config['WTF_CSRF_TIME_LIMIT'] = None

bcrypt = Bcrypt(app)

csrf = CSRFProtect(app)
decimal.getcontext().prec = 28 

#Mongo DB SETUP\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\

MONGODB_URI = os.getenv('MONGODB_URI')

# MongoDB connection string
client = MongoClient(MONGODB_URI, tls=True, tlsAllowInvalidCertificates=True)


db = client["cfacdb"]
users_collection = db["users"]  
estimaterequests_collection = db["estimaterequests"]  
products_collection = db["products"]
orders_collection = db['orders']
services_collection = db["services"]  # Your new services collection


POSTMARK_SERVER_TOKEN = os.getenv('POSTMARK_SERVER_TOKEN')
postmark_client = PostmarkClient(server_token=POSTMARK_SERVER_TOKEN)


@app.template_filter('urlencode')
def urlencode_filter(s):
    if isinstance(s, str):
        return quote_plus(s)
    else:
        return s


# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'tech_admin_login'
login_manager.login_message_category = 'info'  

#Init Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.context_processor
def inject_csrf_token():
    return dict(csrf_token=generate_csrf)




#AWS Set up

AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
AWS_DEFAULT_REGION = os.getenv('AWS_DEFAULT_REGION')






# Define SMS Sender ID and Type
SMS_SENDER_ID = "CFAC"  # Customize as per your region's requirements
SMS_TYPE = "Transactional"  # or "Promotional"
DEFAULT_SENDER = (os.getenv('DEFAULT_SENDER_NAME'), os.getenv('DEFAULT_SENDER_EMAIL'))
SUPPORT_SENDER = (os.getenv('SUPPORT_SENDER_NAME'), os.getenv('SUPPORT_SENDER_EMAIL'))


# Session cookie settings for enhanced security
app.config['SESSION_COOKIE_SECURE'] = True          # Ensures cookies are sent over HTTPS only
app.config['SESSION_COOKIE_HTTPONLY'] = True        # Prevents JavaScript access to cookies
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'       # Mitigates CSRF attacks






# User Model FLASK-LOGIN
# User Model for Flask-Login
class User(UserMixin):
    def __init__(self, user_id, user_type):
        self.id = user_id  # String version of MongoDB's ObjectId
        self.user_type = user_type

# User Loader Callback
@login_manager.user_loader
def load_user(user_id):
    try:
        # Fetch the user by _id
        user_record = users_collection.find_one({"_id": ObjectId(user_id)})
        if user_record and user_record['user_type'] in ['customer', 'admin', 'tech', 'sales']:
            return User(str(user_record['_id']), user_record['user_type'])
    except (InvalidId, TypeError):
        return None

def create_unique_indexes():
    """
    Creates unique and sparse indexes on 'email' and 'phone_number' fields in the users_collection.
    """
    try:
        users_collection.create_index('email', unique=True, sparse=True)
        users_collection.create_index('phone_number', unique=True, sparse=True)
        app.logger.info("Unique indexes created on 'email' and 'phone_number'.")
    except Exception as e:
        app.logger.error(f"Error creating indexes: {e}")

# Call the function to create indexes
create_unique_indexes()



s = URLSafeTimedSerializer(app.secret_key)

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

#AMS Phones 
def is_valid_phone_number(phone_number):
    """
    Validates if the phone number is in E.164 format.
    """
    pattern = re.compile(r'^\+[1-9]\d{1,14}$')
    return bool(pattern.match(phone_number))

def format_phone_number(phone_number, default_region="US"):
    """
    Parses and formats the phone number to E.164 format.
    Assumes 'US' region if the country code is missing.
    
    Args:
        phone_number (str): The phone number input by the user.
        default_region (str): The default region to assume for parsing.
    
    Returns:
        str or None: The formatted phone number in E.164 format if valid, else None.
    """
    try:
        # Remove common formatting characters
        phone_number_clean = re.sub(r'[()\-\s]', '', phone_number)
        
        # Parse the phone number
        parsed_number = phonenumbers.parse(phone_number_clean, default_region)
        
        # Validate the phone number
        if phonenumbers.is_valid_number(parsed_number):
            # Format the number to E.164
            return phonenumbers.format_number(parsed_number, phonenumbers.PhoneNumberFormat.E164)
        else:
            return None
    except NumberParseException:
        return None

def send_sms(phone_number, message):
    """
    Sends an SMS message to the specified phone number using Amazon SNS.

    :param phone_number: Recipient's phone number in E.164 format (e.g., +15551234567)
    :param message: The message content to send
    :return: Message ID if successful, None otherwise
    """
    try:
        response = sns_client.publish(
            PhoneNumber=phone_number,
            Message=message
        )
        message_id = response.get('MessageId')
        app.logger.info(f"SMS sent successfully. Message ID: {message_id}")
        return message_id
    except Exception as e:
        app.logger.error(f"Failed to send SMS to {phone_number}: {e}")
        return None


def ordinal(n):
    """
    Returns the ordinal suffix for a given day.
    Example: 1 -> '1st', 2 -> '2nd', etc.
    """
    if 10 <= n % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f"{n}{suffix}"

def format_date_with_suffix(value):
    """
    Formats a datetime object into 'Month DaySuffix Year' format.
    Example: October 12th 2024
    """
    if isinstance(value, datetime):
        month = value.strftime('%B')      # Full month name, e.g., 'October'
        day = ordinal(value.day)          # Day with ordinal suffix, e.g., '12th'
        year = value.year                  # Year, e.g., '2024'
        return f"{month} {day} {year}"
    return value  # Return the original value if not a datetime object
# Register the date format filter
app.jinja_env.filters['format_date_with_suffix'] = format_date_with_suffix

#FORLOGINS
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in as an admin to access this page.', 'warning')
            return redirect(url_for('tech_admin_login', next=request.url))
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
            return redirect(url_for('tech_admin_login', next=request.url))
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
            return redirect(url_for('tech_admin_login', next=request.url))
        if current_user.user_type != 'sales':
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

def tech_or_sales_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.user_type not in ['tech', 'sales']:
            flash('Access denied: Techs and Sales personnel only.', 'danger')
            return redirect(url_for('index'))
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



def send_tech_notification_email(order, selected_products):
    """
    Sends a notification email to all technicians about a new order.

    :param order: The order document inserted into the database.
    :param selected_products: A list of product documents that were ordered.
    """
    logger = logging.getLogger(__name__)
    try:
        # Corrected Query: Fetch technicians with 'user_type' as 'tech'
        techs_cursor = users_collection.find({'user_type': 'tech'})
        techs = list(techs_cursor)  # Convert cursor to list for multiple iterations if needed
        num_techs = len(techs)
        logger.info(f"Number of technicians fetched: {num_techs}")

        if num_techs == 0:
            logger.warning("No technicians found with 'user_type': 'tech'. Ensure technicians are added to the database.")
            return

        tech_count = 0  # Counter for successful emails
        failed_techs = []

        for tech in techs:
            tech_email = tech.get('email')
            tech_name = tech.get('full_name', 'Technician')  # Assuming a 'full_name' field exists

            if not tech_email:
                logger.warning(f"Technician '{tech_name}' does not have an email and was skipped.")
                continue

            logger.info(f"Preparing to send email to Technician: {tech_email}")

            subject = "New Job Available"
            sender_email = os.getenv('POSTMARK_SENDER_EMAIL')  # Ensure this matches your verified sender

            # Render the email body using HTML and plain-text templates
            html_body = render_template(
                'emails/tech_order_notification.html',
                order=order,
                products=selected_products,
                tech_name=tech_name,
                current_year=datetime.utcnow().year
            )

            text_body = render_template(
                'emails/tech_order_notification.txt',
                order=order,
                products=selected_products,
                tech_name=tech_name
            )

            try:
                send_postmark_email(
                    subject=subject,
                    to_email=tech_email,
                    from_email=sender_email,
                    text_body=text_body,
                    html_body=html_body
                )
                logger.info(f"Notification email sent to technician: {tech_email}")
                tech_count += 1
            except Exception as e:
                logger.error(f"Failed to send email to {tech_email}: {e}")
                failed_techs.append({'email': tech_email, 'error': str(e)})

        logger.info(f"Total technician emails sent successfully: {tech_count}")
        if failed_techs:
            logger.warning(f"Failed to send emails to the following technicians: {failed_techs}")

    except Exception as e:
        logger.error(f"Error in send_tech_notification_email: {e}")



#FORCART
def calculate_cart_total(products):
    total = sum(product['price'] for product in products)
    return total

#For password reset
def notify_password_reset_required(user_email):
    try:
        reset_url = url_for('reset_password_request', _external=True)
        msg = Message('Password Reset Required',
                      recipients=[user_email])
        msg.body = f"""Dear user,

We have detected an issue with your account's password security. Please reset your password using the following link: {reset_url}

If you did not request this, please contact our support team immediately.

Best regards,
CFAC AutoCare Team"""
        mail.send(msg)
    except Exception as e:
        app.logger.error(f"Failed to send password reset notification to {user_email}: {e}")



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
    user_id = current_user.id  # This is the string version of ObjectId
    try:
        user = users_collection.find_one({'_id': ObjectId(user_id)})
    except (InvalidId, TypeError):
        user = None

    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('home'))  # Ensure 'home' route exists

    form = UpdateAccountForm()

    if request.method == 'POST':
        if form.validate_on_submit():
            # Extract form data
            name = form.name.data.strip()
            email = form.email.data.lower().strip() if form.email.data else user.get('email', None)
            phone_number = form.phone_number.data.strip()
            street_address = form.street_address.data.strip()
            city = form.city.data.strip()
            country = form.country.data.strip()
            zip_code = form.zip_code.data.strip()

            # Prepare update fields
            update_fields = {
                'name': name,
                'phone_number': phone_number,
                'address.street_address': street_address,
                'address.city': city,
                'address.country': country,
                'address.zip_code': zip_code
            }

            # Only update email if provided
            if form.email.data:
                update_fields['email'] = email

            try:
                users_collection.update_one(
                    {'_id': ObjectId(user_id)},
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
        form.email.data = user.get('email', '')
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
        filter_query = {'status': 'scheduled', 'added_to_scheduled_by': current_user.id}
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
                    'added_to_scheduled_by': current_user.id  # Assuming 'id' is username for techs
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
            tech_name = tech_user.get('full_name', 'Technician') if tech_user else 'Technician'
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

        # Render email templates
        html_body = render_template(
            'emails/order_scheduled_email.html',
            customer_name=customer_name,
            order=order,
            tech_name=tech_name,
            current_year=current_year
        )
        text_body = render_template(
            'emails/order_scheduled_email.txt',
            customer_name=customer_name,
            order=order,
            tech_name=tech_name
        )

        # Send the email using Postmark
        postmark_client.emails.send(
            From=os.getenv('POSTMARK_SENDER_EMAIL'),
            To=to_email,
            Subject='Your Order Has Been Scheduled!',
            HtmlBody=html_body,
            TextBody=text_body,
            MessageStream="outbound"
        )
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
            user_obj = User(str(user['_id']), user['user_type'])  # Corrected line
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


@app.route('/payments/tech_view_order/<order_id>', methods=['GET'])
@login_required
@tech_required
def tech_view_order(order_id):
    try:
        # Fetch the order by ID
        order = orders_collection.find_one({'_id': ObjectId(order_id)})

        if not order:
            flash('Order not found.', 'danger')
            return redirect(url_for('my_schedule'))

        # Check if the current technician is the one who scheduled the order
        if order.get('added_to_scheduled_by') != current_user.id:
            flash('You do not have permission to view this order.', 'danger')
            return redirect(url_for('my_schedule'))

        # Fetch product details
        product_ids = [ObjectId(pid) for pid in order.get('products', [])]
        products = list(products_collection.find({'_id': {'$in': product_ids}}))
        products_dict = {str(product['_id']): product for product in products}
    
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

         

        return render_template('payments/tech_view_order.html', order=order, products_dict=products_dict)
    except InvalidId:
        flash('Invalid Order ID.', 'danger')
        return redirect(url_for('collecting_payments'))
    except Exception as e:
        app.logger.error(f"Error accessing order {order_id}: {e}")
        flash('An error occurred while accessing the order.', 'danger')
        return redirect(url_for('collecting_payments'))

#Routes for Sales\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\



#Sales Main
@app.route('/sales/main')
@login_required
@sales_required  # Ensure this decorator checks for salesperson privileges
def sales_main():
    try:
        # 1) Pagination Parameters
        page = request.args.get('page', 1, type=int)  # Current page number
        per_page = 20  # Number of orders per page

        # 2) Search Parameter (Optional)
        search_query = request.args.get('search', '').strip()

        # 3) Build MongoDB Query
        query = {
            'salesperson': str(current_user.id)
        }

        if search_query:
            try:
                object_id = ObjectId(search_query)
                query['$or'] = [
                    {'_id': object_id},
                    {'guest_name': {'$regex': search_query, '$options': 'i'}},
                    {'user_email': {'$regex': search_query, '$options': 'i'}}
                ]
            except InvalidId:
                # If not a valid ObjectId, just do guest_name/user_email
                query['$or'] = [
                    {'guest_name': {'$regex': search_query, '$options': 'i'}},
                    {'user_email': {'$regex': search_query, '$options': 'i'}}
                ]

        # 4) Fetch Total Number of Orders Matching the Query
        total_orders = orders_collection.count_documents(query)
        total_pages = (total_orders + per_page - 1) // per_page  # ceiling division

        # 5) Fetch Orders for the Current Page
        orders = list(
            orders_collection.find(query)
            .sort('order_date', -1)         # Sort by order_date descending
            .skip((page - 1) * per_page)
            .limit(per_page)
        )

        # 6) Enrich Orders with Additional Details
        for order in orders:
            # Convert ObjectId fields to string
            order['_id'] = str(order['_id'])
            order['salesperson'] = str(order.get('salesperson'))

            # Determine order type
            is_guest = order.get('is_guest', False)
            order['order_type'] = 'Guest Order' if is_guest else 'Customer Order'

            # If it's a customer order, fetch user details
            if not is_guest:
                user = users_collection.find_one({'email': order.get('user')})
                if user:
                    order['user_name'] = user.get('name', 'N/A')
                    order['user_phone'] = user.get('phone_number', 'N/A')
                    order['user_address'] = user.get('address', {})
                else:
                    order['user_name'] = 'Unknown'
                    order['user_phone'] = 'Unknown'
                    order['user_address'] = {}

            # Handle 'scheduled_by' 
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
                        app.logger.error(
                            f"Invalid {date_field} format for order {order.get('_id')}: {order.get(date_field)}"
                        )
                        order[date_field] = None

            # We've removed product references, so no code for product_details here.

        # 7) Initialize Delete Form
        delete_form = DeleteOrderForm()

        # 8) Pass Variables to the Template
        return render_template(
            'sales/main.html',
            orders=orders,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
            search_query=search_query,
            delete_form=delete_form
        )
    except Exception as e:
        app.logger.error(f"Error in sales_main route: {e}")
        flash('An error occurred while fetching your scheduled sales.', 'danger')
        return redirect(url_for('home'))









# Schedule Guest Order Route
@app.route('/sales/schedule_guest_order', methods=['GET', 'POST'])
@login_required
@sales_required
def schedule_guest_order():
    current_app.logger.info("schedule_guest_order route called")
    form = GuestOrderForm()
    
    # Load active services from the DB
    all_services = list(services_collection.find({"active": True}))
    services_json = dumps(all_services)
    
    if form.validate_on_submit():
        try:
            # [Existing form data extraction and processing...]

            # Extract selected services
            selected_service_keys = request.form.getlist('services')
            current_app.logger.info(f"Selected Services: {selected_service_keys}")
            
            # Validate selected services
            selected_services = []
            base_total = 0.0  # Initialize base total
            for key in selected_service_keys:
                service = services_collection.find_one({"key": key, "active": True})
                if service:
                    service_price = service.get('price_by_vehicle_size', {}).get(vehicle_size, 0.0)
                    selected_services.append({
                        'key': service['key'],
                        'label': service['label'],
                        'price': service_price
                    })
                    base_total += service_price
                    current_app.logger.info(f"Added Service: {service['key']} - {service['label']} at ${service_price}")
                else:
                    current_app.logger.warning(f"Invalid or inactive service selected: {key}")

            # Handle service package if selected
            if service_package:
                package_price = packagePrices.get(service_package, 0.0)
                base_total = package_price
                selected_services = [{
                    'key': service_package,
                    'label': service_package.replace('_', ' ').title(),
                    'price': package_price
                }]
                current_app.logger.info(f"Selected Package: {service_package} at ${package_price}")

            if not selected_services and not service_package:
                flash('Please select at least one service or choose a package.', 'warning')
                return render_template(
                    'sales/schedule_guest_order.html',
                    form=form,
                    services=all_services,
                    services_json=services_json
                )
            
            # Calculate Unit Price
            unit_price = math.ceil(base_total / 0.55)
            fee = unit_price - base_total
            sales_cut = fee / 2
            minimum_price = unit_price - sales_cut

            current_app.logger.info(f"Base Total: {base_total}, Unit Price: {unit_price}, Fee: {fee}, Sales Cut: {sales_cut}, Minimum Price: {minimum_price}")

            # Initialize payment status
            payment_status = 'Unpaid'

            # Handle payment if 'pay_now' is selected
            if payment_time == 'pay_now':
                payment_method_id = request.form.get('payment_method_id')
                if not payment_method_id:
                    flash('Payment method is required for immediate payment.', 'danger')
                    return render_template(
                        'sales/schedule_guest_order.html',
                        form=form,
                        services=all_services,
                        services_json=services_json,
                        minimum_price=minimum_price  # Pass minimum_price to template
                    )
                
                # [Existing Stripe payment processing...]

            # Capture final price from form
            final_price_str = request.form.get('final_price', '0')
            try:
                final_price = float(final_price_str)
            except ValueError:
                final_price = 0.0

            # Enforce minimum price
            if final_price < minimum_price:
                flash(f"The total price cannot be less than ${minimum_price:.2f}.", 'danger')
                return render_template(
                    'sales/schedule_guest_order.html',
                    form=form,
                    services=all_services,
                    services_json=services_json,
                    minimum_price=minimum_price  # Pass minimum_price to template
                )

            # Create the order document
            order = {
                'user': None,  # No user associated since it's a guest order
                'is_guest': True,  # Mark as guest
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
                'payment_time': payment_time,
                'payment_status': payment_status,  # Updated based on payment
                'order_date': datetime.utcnow(),
                'service_date': service_datetime,
                'vehicle_size': vehicle_size,
                'service_package': service_package,
                'senior_rv_discount': senior_rv_discount,
                'services': selected_services,  # Add selected services here
                'status': 'ordered',
                'salesperson': str(current_user.id),
                'creation_date': datetime.utcnow(),
                'scheduled_by': str(current_user.id),
                'total': final_price
            }
            
            # Log the order
            current_app.logger.info(f"Inserting Order: {order}")
            
            # Insert the order
            inserted_order = orders_collection.insert_one(order)
            
            # [Existing notification sending...]

            # Flash success
            flash(f"Guest order scheduled successfully by {current_user.id}!", 'success')
            
            # Redirect based on payment_time
            if payment_time == 'pay_now':
                return redirect(url_for('collecting_payments'))
            else:
                return redirect(url_for('sales_main'))
        
        except Exception as e:
            current_app.logger.error(f"Error scheduling guest order: {e}")
            flash('An error occurred while scheduling the guest order. Please try again.', 'danger')
            return render_template(
                'sales/schedule_guest_order.html',
                form=form,
                services=all_services,
                services_json=services_json,
                minimum_price=minimum_price if 'minimum_price' in locals() else 0  # Pass minimum_price if available
            )
    
    # If GET or not valid on POST
    # Calculate minimum_price for GET requests
    if request.method == 'GET':
        minimum_price = 0.0  # Default or calculated based on initial form state
    return render_template(
        'sales/schedule_guest_order.html',
        form=form,
        services=all_services,
        services_json=services_json,
        minimum_price=minimum_price  # Pass minimum_price to template
    )





#Guest Order Email Route
def send_guest_order_confirmation_email(guest_email, guest_phone_number, order, selected_products):
    """
    Sends a confirmation email and/or SMS to the guest after scheduling an order.

    :param guest_email: The guest's email address.
    :param guest_phone_number: The guest's phone number in E.164 format.
    :param order: The order document inserted into the database.
    :param selected_products: A list of product documents that were ordered.
    """
    try:
        # Initialize flags
        email_sent = False
        sms_sent = False

        # Fetch Salesperson's Details
        salesperson_id = order.get('salesperson')
        if salesperson_id:
            try:
                salesperson = users_collection.find_one({'_id': ObjectId(salesperson_id)})
                if salesperson:
                    salesperson_name = salesperson.get('name', 'Salesperson')
                    salesperson_phone_number = salesperson.get('phone_number', '')
                else:
                    salesperson_name = 'Salesperson'
                    salesperson_phone_number = ''
            except Exception as e:
                current_app.logger.error(f"Error fetching salesperson details: {e}")
                salesperson_name = 'Salesperson'
                salesperson_phone_number = ''
        else:
            salesperson_name = 'Salesperson'
            salesperson_phone_number = ''

        # 1. Send Email if guest_email is provided
        if guest_email:
            try:
                # Render the email body using an HTML template
                html_body = render_template(
                    'emails/guest_order_confirmation.html',
                    order=order,
                    products=selected_products,
                    current_year=datetime.utcnow().year,
                    salesperson_name=salesperson_name,
                    salesperson_phone_number=salesperson_phone_number
                )

                # Optionally, render a plain-text version
                text_body = render_template(
                    'emails/guest_order_confirmation.txt',
                    order=order,
                    products=selected_products,
                    salesperson_name=salesperson_name,
                    salesperson_phone_number=salesperson_phone_number
                )

                # Send the email using Postmark
                postmark_client.emails.send(
                    From=os.getenv('POSTMARK_SENDER_EMAIL'),
                    To=guest_email,
                    Subject="Your Order Confirmation - CFAC",
                    HtmlBody=html_body,
                    TextBody=text_body,
                    MessageStream="outbound"  # Use "outbound" or your custom message stream
                )

                current_app.logger.info(f"Confirmation email sent to {guest_email}")
                email_sent = True
            except Exception as e:
                current_app.logger.error(f"Failed to send confirmation email to {guest_email}: {e}")

         # 2. Send SMS if guest_phone_number is provided
        if guest_phone_number:
            try:
                # Validate phone number format using regex
                if not re.match(r'^\+\d{10,15}$', guest_phone_number):
                    raise ValueError("Phone number is not in E.164 format.")

                # Compose the SMS message
                sms_message = render_template(
                    'sms/guest_order_confirmation.txt',
                    order=order,
                    products=selected_products,
                    current_year=datetime.utcnow().year,
                    salesperson_name=salesperson_name,
                    salesperson_phone_number=salesperson_phone_number
                )

                # Send the SMS via Twilio
                message = twilio_client.messages.create(
                    body=sms_message,
                    from_=TWILIO_PHONE_NUMBER,
                    to=guest_phone_number
                )

                current_app.logger.info(f"SMS sent successfully to {guest_phone_number}. Message SID: {message.sid}")
                sms_sent = True
            except Exception as e:
                current_app.logger.error(f"Failed to send SMS to {guest_phone_number}: {e}")


        # 3. Log the results
        if not email_sent and not sms_sent:
            current_app.logger.warning("No confirmation messages were sent to the guest.")

    except Exception as e:
        current_app.logger.error(f"Error in send_guest_order_confirmation_email: {e}")


@app.route('/sales/view_order/<order_id>')
@login_required
@sales_required  # Ensure only sales users can access
def sales_view_order(order_id):
    try:
        # **1. Validate the Order ID**
        if not ObjectId.is_valid(order_id):
            flash('Invalid order ID.', 'danger')
            return redirect(url_for('sales_main'))
        
        order_obj_id = ObjectId(order_id)
        
        # **2. Fetch the Order from the Database**
        order = orders_collection.find_one({'_id': order_obj_id})
        if not order:
            flash('Order not found.', 'danger')
            return redirect(url_for('sales_main'))
        
        # **3. Check if the Current Salesperson is Assigned to the Order**
        if str(order.get('salesperson')) != str(current_user.id):
            flash('You do not have permission to view this order.', 'danger')
            return redirect(url_for('sales_main'))
        
        # **4. Enrich the Order with Additional Details**
        # Convert ObjectId fields to string for easier handling in templates
        order['_id'] = str(order['_id'])
        order['salesperson'] = str(order.get('salesperson'))
    
        # Determine order type
        is_guest = order.get('is_guest', False)
        order['order_type'] = 'Guest Order' if is_guest else 'Customer Order'
    
        # Fetch user details if it's a customer order
        if not is_guest:
            user = users_collection.find_one({'email': order.get('user')})
            if user:
                order['user_name'] = user.get('name', 'N/A')
                order['user_phone'] = user.get('phone_number', 'N/A')
                order['user_address'] = user.get('address', {})
            else:
                order['user_name'] = 'Unknown'
                order['user_phone'] = 'Unknown'
                order['user_address'] = {}
    
        # Fetch the user who scheduled the order
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
    
        # Ensure dates are datetime objects (if stored as strings)
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
    
      
        # **5. Initialize Delete Form (Optional)**
        delete_form = DeleteOrderForm()
    
        # **6. Render the Template with Order Details**
        return render_template(
            'sales/view_order.html',
            order=order,
            delete_form=delete_form  # Pass delete_form if you plan to allow deletion
        )
    
    except Exception as e:
        app.logger.error(f"Error in sales_view_order route: {e}")
        flash('An error occurred while fetching the order details.', 'danger')
        return redirect(url_for('sales_main'))
#Sales profile route
@app.route('/sales/profile')
@login_required
@sales_required
def sales_profile():
    user_id = current_user.id  # Get the current user's ID

    # Fetch the salesperson's data from the database
    try:
        user = users_collection.find_one({'_id': ObjectId(user_id)})
    except (InvalidId, TypeError):
        user = None

    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('sales_main'))

    return render_template('sales/profile.html', user=user)

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
    user = users_collection.find_one({'_id': ObjectId(current_user.id)})
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

# Add to Cart Route
@app.route('/customer/add_to_cart/<product_id>', methods=['GET', 'POST'])
@customer_required
def add_to_cart(product_id):
    try:
        # Fetch the product from the database
        product = products_collection.find_one({'_id': ObjectId(product_id)})
        if not product:
            flash('Product not found.', 'danger')
            return redirect(url_for('home'))
        
        # Initialize the cart in session if it doesn't exist
        if 'cart' not in session:
            session['cart'] = []
        
        # Add the product ID to the cart if it's not already there
        if product_id not in session['cart']:
            session['cart'].append(product_id)
            flash(f"Added {product['name']} to your cart.", 'success')
        else:
            flash(f"{product['name']} is already in your cart.", 'info')
        
        return redirect(url_for('customer_home'))
    except InvalidId:
        flash('Invalid product ID.', 'danger')
        return redirect(url_for('home'))
    except Exception as e:
        app.logger.error(f"Error adding product to cart: {e}")
        flash('An error occurred while adding the product to your cart.', 'danger')
        return redirect(url_for('home'))


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
    user_id = current_user.id

    try:
        user = users_collection.find_one({'_id': ObjectId(user_id)})
    except (InvalidId, TypeError):
        user = None

    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('home'))

    if 'cart' not in session or not session['cart']:
        flash('Your cart is empty.', 'info')
        return redirect(url_for('customer_home'))

    product_ids = [ObjectId(id) for id in session['cart']]
    products_in_cart = list(products_collection.find({'_id': {'$in': product_ids}}))
    total = calculate_cart_total(products_in_cart)

    if request.method == 'POST':
        service_date_str = request.form.get('service_date')
        service_time_str = request.form.get('service_time')
        payment_method = request.form.get('payment_method')

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

        if not service_time_str:
            flash('Please select a service time.', 'warning')
            return redirect(url_for('checkout'))

        try:
            service_time = datetime.strptime(service_time_str, '%H:%M').time()
            min_time = datetime.strptime('06:00', '%H:%M').time()
            max_time = datetime.strptime('16:30', '%H:%M').time()
            if not (min_time <= service_time <= max_time):
                flash('Service time must be between 6:00 AM and 4:30 PM.', 'danger')
                return redirect(url_for('checkout'))
        except ValueError:
            flash('Invalid service time format.', 'danger')
            return redirect(url_for('checkout'))

        if payment_method == 'credit_card':
            try:
                # Create a Stripe PaymentIntent
                payment_intent = stripe.PaymentIntent.create(
                    amount=int(total * 100),  # Convert to cents
                    currency='usd',
                    payment_method=request.form['payment_method_id'],
                    confirm=True,
                )

                # Check if the payment was successful
                if payment_intent['status'] == 'succeeded':
                    # Process the order
                    initial_status = 'ordered'
                    service_datetime = datetime.combine(service_date, service_time)

                    order = {
                        'user': current_user.id,
                        'products': session['cart'],
                        'total': total,
                        'order_date': datetime.now(),
                        'service_date': service_datetime,
                        'service_time': service_time_str,
                        'payment_method': payment_method,
                        'status': initial_status,
                        'address': {
                            'street_address': user['address'].get('street_address', '') if user.get('address') else '',
                            'unit_apt': user['address'].get('unit_apt', '') if user.get('address') else '',
                            'city': user['address'].get('city', '') if user.get('address') else ''
                        },
                        'creation_date': datetime.utcnow()
                    }
                    orders_collection.insert_one(order)

                    flash('Your order has been placed successfully!', 'success')

                    # Clear the cart
                    session.pop('cart', None)

                    return redirect(url_for('customer_home'))
                else:
                    flash('Payment failed, please try again.', 'danger')
            except stripe.error.CardError as e:
                flash(f'Payment error: {e.error.message}', 'danger')
        else:
            flash('Please select a valid payment method.', 'warning')

    else:
        default_service_date = (datetime.today() + timedelta(days=1)).strftime('%Y-%m-%d')
        user_address = user.get('address', {})
        return render_template(
            'customer/checkout.html',
            products=products_in_cart,
            total=total,
            default_service_date=default_service_date,
            user_address=user_address
        )


# Customer Login Route

@app.route('/customer/login', methods=['GET', 'POST'])
def customer_login():
    form = CustomerLoginForm()
    if form.validate_on_submit():
        login_method = form.login_method.data
        password = form.password.data

        user = None

        if login_method == 'email':
            email = form.email.data.lower().strip()
            user = users_collection.find_one({'email': email, 'user_type': 'customer'})
        elif login_method == 'phone':
            phone_number = form.phone_number.data.strip()
            user = users_collection.find_one({'phone_number': phone_number, 'user_type': 'customer'})
        
        if user:
            try:
                if bcrypt.check_password_hash(user['password'], password):
                    user_obj = User(str(user['_id']), user['user_type'])  # Corrected line
                    login_user(user_obj)
                    flash('Logged in successfully as customer.', 'success')
                    next_page = request.args.get('next')
                    return redirect(next_page or url_for('customer_home'))
                else:
                    flash('Invalid credentials. Please try again.', 'danger')
            except ValueError:
                # Handle invalid hash format
                flash('Your account has an invalid password format. Please reset your password.', 'danger')
                return redirect(url_for('reset_password_request'))
        else:
            flash('Invalid credentials. Please try again.', 'danger')
    return render_template('customer/login.html', form=form)


#My Orders Page Routes 
@app.route('/customer/my_orders')
@customer_required
def my_orders():
    user_id = current_user.id
    user_type = current_user.user_type

    if user_type != 'customer':
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('customer_home'))
    
    user = users_collection.find_one({'_id': ObjectId(user_id)})
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('customer_home'))
    
    # Ensure the `user_id` is a string to match the `user` field in orders
    user_id_str = str(user_id)
    print(f"Querying for orders with user ID: {user_id_str}")
    user_orders = list(orders_collection.find({'user': user_id_str}).sort('order_date', -1))
    print(f"user_orders after query: {user_orders}")

    for order in user_orders:
        order['product_details'] = []
        for product_id in order.get('products', []):
            product = products_collection.find_one({'_id': ObjectId(product_id)})
            if product:
                order['product_details'].append(product)
        
        if order.get('status', '').lower() == 'scheduled' and order.get('scheduled_by'):
            tech_user = users_collection.find_one({'username': order['scheduled_by']})
            order['scheduled_by_name'] = tech_user.get('name', 'Technician') if tech_user else 'Technician'
        else:
            order['scheduled_by_name'] = 'Not scheduled yet'

    return render_template('customer/my_orders.html', orders=user_orders)

#Customer Register Route

# Registration Route
@app.route('/customer/register', methods=['GET', 'POST'])
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        # Extract form data
        name = form.name.data.strip()
        email = form.email.data.lower().strip() if form.email.data else None
        phone_number = form.phone_number.data.strip() if form.phone_number.data else None
        password = form.password.data
        unit_apt = form.unit_apt.data.strip() if form.unit_apt.data else ''
        city = form.city.data.strip()
        country = form.country.data.strip()
        zip_code = form.zip_code.data.strip()
        registration_method = form.registration_method.data
        sms_opt_in = form.sms_opt_in.data  # Boolean value: True or False

        # At this point, phone_number is already validated and formatted to E.164 if provided

        # Check if the email or phone number already exists
        if email:
            existing_email = users_collection.find_one({'email': email})
            if existing_email:
                flash('Email already registered. Please log in.', 'danger')
                return redirect(url_for('customer_login'))

        if phone_number:
            existing_phone = users_collection.find_one({'phone_number': phone_number})
            if existing_phone:
                flash('Phone number already registered. Please log in.', 'danger')
                return redirect(url_for('register'))

        # Hash the password using Flask-Bcrypt
        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')  # Decode to store as string

        # Create the user document
        user = {
            'name': name,
            'email': email,
            'phone_number': phone_number,
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
            'sms_opt_in': sms_opt_in  # Store the SMS opt-in preference
            # Add other necessary fields if required
        }

        try:
            users_collection.insert_one(user)
            flash('Account created successfully! Please log in.', 'success')
            return redirect(url_for('customer_login'))
        except DuplicateKeyError:
            flash('A user with the provided email or phone number already exists.', 'danger')
            return redirect(url_for('register'))
        except Exception as e:
            current_app.logger.error(f"Error creating user: {e}")
            flash('An error occurred while creating your account. Please try again.', 'danger')
            return redirect(url_for('register'))

    return render_template('customer/register.html', form=form)
          

#Reset password route request
@app.route('/customer/reset_password', methods=['GET', 'POST'])
def reset_password_request():
    form = PasswordResetRequestForm()
    if form.validate_on_submit():
        user = users_collection.find_one({'email': form.email.data, 'user_type': 'customer'})
        if user:
            token = s.dumps(user['email'], salt='password-reset-salt')
            reset_url = url_for('reset_password', token=token, _external=True)
            # Send email with reset_url
            msg = Message('Password Reset Request',
                          recipients=[user['email']])
            msg.body = f'Please click the link to reset your password: {reset_url}'
            mail.send(msg)
            flash('A password reset link has been sent to your email.', 'info')
            return redirect(url_for('customer_login'))
        else:
            flash('Email not found.', 'danger')
    return render_template('customer/reset_password_request.html', form=form)
#Reset password route 
@app.route('/customer/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = s.loads(token, salt='password-reset-salt', max_age=3600)  # Token valid for 1 hour
    except SignatureExpired:
        flash('The password reset link has expired.', 'danger')
        return redirect(url_for('reset_password_request'))
    
    form = PasswordResetForm()
    if form.validate_on_submit():
        user = users_collection.find_one({'email': email, 'user_type': 'customer'})
        if user:
            hashed_pw = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
            users_collection.update_one({'_id': user['_id']}, {'$set': {'password': hashed_pw}})
            flash('Your password has been updated!', 'success')
            return redirect(url_for('customer_login'))
        else:
            flash('User not found.', 'danger')
            return redirect(url_for('reset_password_request'))
    return render_template('customer/reset_password.html', form=form)



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
        orders_cursor = orders_collection.find().sort('order_date', -1).skip((page - 1) * per_page).limit(per_page)
        orders = list(orders_cursor)

        # **5. Enrich Orders with Additional Details**
        for order in orders:
            # Determine if the order is a guest order or a customer order
            is_guest = order.get('is_guest', False)
            order['order_type'] = 'Guest Order' if is_guest else 'Customer Order'

            # **5.1. Handle Payment Status**
            order['payment_status'] = order.get('payment_status', 'Unpaid')  # Default to 'Unpaid' if missing

            if is_guest:
                # For guest orders, fetch the salesperson's details using _id
                salesperson_id = order.get('salesperson')
                if salesperson_id:
                    try:
                        salesperson_obj_id = ObjectId(salesperson_id)
                        salesperson = users_collection.find_one({'_id': salesperson_obj_id, 'user_type': 'sales'})
                        order['salesperson_name'] = salesperson.get('full_name', 'Unknown') if salesperson else 'Unknown'
                    except InvalidId:
                        order['salesperson_name'] = 'Unknown'
                else:
                    order['salesperson_name'] = 'Not Assigned'
            else:
                # For customer orders, fetch the user's email
                user_email = order.get('user')
                if user_email:
                    user = users_collection.find_one({'email': user_email})
                    if user:
                        order['user_email'] = user.get('email', 'Unknown')
                    else:
                        order['user_email'] = 'Unknown'
                else:
                    order['user_email'] = 'Unknown'

            # **5.2. Convert Date Fields**
            for date_field in ['order_date', 'service_date']:
                date_value = order.get(date_field)
                if isinstance(date_value, str):
                    try:
                        if date_field == 'service_date':
                            order[date_field] = datetime.strptime(date_value, '%Y-%m-%d')
                        else:
                            order[date_field] = datetime.strptime(date_value, '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        app.logger.error(f"Invalid {date_field} format for order ID {order.get('_id')}: {date_value}")
                        order[date_field] = None  # Handle invalid date formats as needed

            # **5.3. Get Product Details**
            product_ids = [pid for pid in order.get('products', []) if ObjectId.is_valid(pid)]
            try:
                product_ids = [ObjectId(pid) for pid in product_ids]
                products = list(products_collection.find({'_id': {'$in': product_ids}}))
                order['product_details'] = products
            except Exception as e:
                app.logger.error(f"Error fetching products for order ID {order.get('_id')}: {e}")
                order['product_details'] = []

            # **5.4. Fetch Technician Details if Scheduled**
            scheduled_by = order.get('added_to_scheduled_by')
            if scheduled_by and ObjectId.is_valid(scheduled_by):
                tech = users_collection.find_one({'_id': ObjectId(scheduled_by)})
                order['tech_name'] = tech.get('name', 'Unknown Tech') if tech else 'Unknown Tech'
            else:
                order['tech_name'] = 'Not Scheduled Yet'

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
        app.logger.error(f"Error in admin_main route: {e}", exc_info=True)
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

        # Initialize delete form
        delete_form = DeleteOrderForm()
        
        # Determine if the order is a guest order or a customer order
        is_guest = order.get('is_guest', False)
        order['order_type'] = 'Guest Order' if is_guest else 'Customer Order'

        if is_guest:
            # For guest orders, fetch the salesperson's details using _id
            salesperson_id = order.get('salesperson')
            if salesperson_id:
                try:
                    salesperson_obj_id = ObjectId(salesperson_id)
                    salesperson = users_collection.find_one({'_id': salesperson_obj_id, 'user_type': 'sales'})
                    order['salesperson_name'] = salesperson.get('name', 'Unknown') if salesperson else 'Unknown'
                except InvalidId:
                    order['salesperson_name'] = 'Unknown'
            else:
                order['salesperson_name'] = 'Not Assigned'
        else:
            # For customer orders, fetch the user's details
            user = users_collection.find_one({'email': order.get('user')})
            order['user_email'] = user['email'] if user else 'Unknown'
            order['user_name'] = user.get('name', 'N/A') if user else 'N/A'
            order['user_phone'] = user.get('phone_number', 'N/A') if user else 'N/A'
            order['user_address'] = user.get('address', {})

          # Fetch the user who scheduled the order using _id
        scheduled_by_id = order.get('scheduled_by')
        if scheduled_by_id:
            try:
                scheduled_by_user = users_collection.find_one({'_id': ObjectId(scheduled_by_id)})
                if scheduled_by_user:
                    order['scheduled_by_name'] = scheduled_by_user.get('name', 'Unknown')
                    order['scheduled_by_email'] = scheduled_by_user.get('email', 'Unknown')
                else:
                    order['scheduled_by_name'] = 'Unknown'
                    order['scheduled_by_email'] = 'Unknown'
            except InvalidId:
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

        return render_template('admin/view_order.html', order=order, delete_form=delete_form)
    except Exception as e:
        app.logger.error(f"Error in view_order route: {e}")
        flash('An error occurred while fetching the order details.', 'danger')
        return redirect(url_for('admin_main'))



# Edit Order Route


  

@app.route('/admin/edit_order/<order_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_order(order_id):
    try:
        # **1. Validate and Convert Order ID**
        if not ObjectId.is_valid(order_id):
            flash('Invalid order ID.', 'danger')
            return redirect(url_for('admin_main'))

        order_obj_id = ObjectId(order_id)
        order = orders_collection.find_one({'_id': order_obj_id})
        if not order:
            flash('Order not found.', 'danger')
            return redirect(url_for('admin_main'))

        # **2. Initialize the Form**
        if request.method == 'POST':
            # **3. Handle Form Submission**
            form = EditOrderForm()
            if form.validate_on_submit():
                # **4. Handle Total Amount Conversion**
                try:
                    total_float = float(form.total_amount.data)
                except (ValueError, TypeError):
                    flash('Invalid total amount.', 'danger')
                    return redirect(url_for('edit_order', order_id=order_id))

                # **5. Handle Service Date Conversion**
                service_date = form.service_date.data  # This is a datetime.date object
                if isinstance(service_date, date) and not isinstance(service_date, datetime):
                    # Combine with a default time, e.g., midnight
                    service_datetime = datetime.combine(service_date, time.min)
                else:
                    service_datetime = service_date  # Already a datetime.datetime object

                # **6. Update the Order in MongoDB**
                update_result = orders_collection.update_one(
                    {'_id': order_obj_id},
                    {'$set': {
                        'status': form.status.data,
                        'payment_method': form.payment_method.data,
                        'total': total_float,
                        'service_date': service_datetime  # Now a datetime.datetime object
                    }}
                )

                if update_result.modified_count:
                    flash('Order updated successfully.', 'success')
                else:
                    flash('No changes made to the order.', 'info')

                return redirect(url_for('view_order', order_id=order_id))
            else:
                # **7. Log Validation Errors**
                current_app.logger.warning(f"Form validation failed: {form.errors}")
                flash('Please correct the errors in the form.', 'danger')
        else:
            # **8. Pre-populate Form Fields on GET Request**
            form = EditOrderForm()
            # Manually set form fields from order data
            form.status.data = order.get('status', '')
            form.payment_method.data = order.get('payment_method', '')
            form.total_amount.data = order.get('total', '')
            # Ensure the date is a date object
            service_date = order.get('service_date', None)
            if service_date:
                if isinstance(service_date, datetime):
                    form.service_date.data = service_date.date()
                elif isinstance(service_date, date):
                    form.service_date.data = service_date
                else:
                    form.service_date.data = None
            else:
                form.service_date.data = None

        # **9. Render the Edit Order Template**
        return render_template('admin/edit_order.html', form=form, order=order)

    except Exception as e:
        current_app.logger.error(f"Error in edit_order route: {e}", exc_info=True)
        flash('An error occurred while editing the order.', 'danger')
        return redirect(url_for('admin_main'))



@app.route('/admin/delete_order/<order_id>', methods=['POST'])
@login_required
@admin_required
def delete_order(order_id):
    form = DeleteOrderForm()
    if form.validate_on_submit():
        try:
            order_obj_id = ObjectId(order_id)
        except InvalidId:
            flash('Invalid order ID.', 'danger')
            current_app.logger.warning(f"Delete attempt with invalid order ID: {order_id}")
            return redirect(url_for('admin_main'))

        result = orders_collection.delete_one({'_id': order_obj_id})
        if result.deleted_count == 1:
            flash('Order deleted successfully.', 'success')
            current_app.logger.info(f"Order {order_id} deleted successfully.")
        else:
            flash('Order not found.', 'warning')
            current_app.logger.warning(f"Attempted to delete non-existent order: {order_id}")
    else:
        flash('Invalid CSRF token.', 'danger')
        current_app.logger.warning(f"Invalid CSRF token when attempting to delete order: {order_id}")
    
    return redirect(url_for('admin_main'))

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

#Manage Users Route
@app.route('/admin/manage_users')
@login_required
@admin_required
def manage_users():
    try:
        # Instantiate the delete form
        delete_form = DeleteOrderForm()

        # Pagination and search setup
        page = request.args.get('page', 1, type=int)
        per_page = 20
        search_query = request.args.get('search', '').strip()

        query = {}
        if search_query:
            try:
                query = {
                    '$or': [
                        {'email': {'$regex': search_query, '$options': 'i'}},
                        {'_id': ObjectId(search_query)}
                    ]
                }
            except InvalidId:
                query = {'email': {'$regex': search_query, '$options': 'i'}}

        total_users = users_collection.count_documents(query)
        total_pages = (total_users + per_page - 1) // per_page

        users = list(
            users_collection.find(query)
            .sort('creation_date', -1)
            .skip((page - 1) * per_page)
            .limit(per_page)
        )

        return render_template(
            'admin/manage_users.html',
            users=users,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
            delete_form=delete_form  # Pass delete form
        )
    except Exception as e:
        app.logger.error(f"Error in manage_users route: {e}")
        flash('An error occurred while fetching users.', 'danger')
        return redirect(url_for('admin_main'))



@app.route('/admin/view_user/<user_id>')
@login_required
@admin_required  # Ensure this decorator is defined to restrict access to admins
def view_user(user_id):
    try:
        user_obj_id = ObjectId(user_id)
    except InvalidId:
        flash('Invalid user ID.', 'danger')
        app.logger.warning(f"Invalid ObjectId for view_user: {user_id}")
        return redirect(url_for('manage_users'))

    user = users_collection.find_one({'_id': user_obj_id})
    if not user:
        flash('User not found.', 'danger')
        app.logger.warning(f"User not found: {user_id}")
        return redirect(url_for('manage_users'))

    # Ensure creation_date is a datetime object
    if 'creation_date' in user and isinstance(user['creation_date'], str):
        try:
            user['creation_date'] = datetime.strptime(user['creation_date'], '%Y-%m-%d %H:%M:%S')
        except ValueError:
            app.logger.error(f"Invalid creation_date format for user ID {user_id}: {user['creation_date']}")
            user['creation_date'] = None  # Handle invalid date formats as needed

    app.logger.info(f"Displaying user details for user ID: {user_id}")
    return render_template('admin/view_user.html', user=user)




# Compensation Route
@app.route('/admin/compensation')
@login_required
@admin_required
def compensation_page():
    try:
        # **1. Pagination Parameters**
        page = request.args.get('page', 1, type=int)  # Current page number
        per_page = 20  # Number of orders per page

        # **2. Fetch Total Number of Orders**
        total_orders = orders_collection.count_documents({})
        total_pages = (total_orders + per_page - 1) // per_page  # Ceiling division to get total pages

        # **3. Fetch Orders for the Current Page**
        orders_cursor = orders_collection.find().sort('service_date', -1).skip((page - 1) * per_page).limit(per_page)
        orders = list(orders_cursor)

        # **4. Enrich Orders with Technician and Salesperson Details**
        for order in orders:
            # **Convert ObjectId to string**
            order['_id'] = str(order['_id'])
            
            # Fetch Technician Details
            tech_id = order.get('technician_id')
            if tech_id and ObjectId.is_valid(str(tech_id)):
                technician = users_collection.find_one({'_id': ObjectId(tech_id)})
                order['technician_name'] = technician.get('name', 'Unknown') if technician else 'Unknown'
            else:
                order['technician_name'] = 'Not Assigned'

            # Fetch Salesperson Details
            salesperson_id = order.get('salesperson_id')
            if salesperson_id and ObjectId.is_valid(str(salesperson_id)):
                salesperson = users_collection.find_one({'_id': ObjectId(salesperson_id)})
                order['salesperson_name'] = salesperson.get('name', 'Unknown') if salesperson else 'Unknown'
            else:
                order['salesperson_name'] = 'Not Assigned'

            # Convert service_date to datetime object if it's a string
            service_date = order.get('service_date')
            if isinstance(service_date, str):
                try:
                    order['service_date'] = datetime.strptime(service_date, '%Y-%m-%d')
                except ValueError:
                    app.logger.error(f"Invalid service_date format for order ID {order.get('_id')}: {service_date}")
                    order['service_date'] = None  # Handle invalid date formats as needed

        # **5. Create Separate Form Instances for Each Order**
        forms = {order['_id']: UpdateCompensationStatusForm(prefix=order['_id']) for order in orders}

        # **6. Pass Variables to the Template**
        return render_template(
            'admin/compensation.html',
            orders=orders,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
            forms=forms  # Pass the forms dictionary to the template
        )
    except Exception as e:
        app.logger.error(f"Error in compensation_page route: {e}", exc_info=True)
        flash('An error occurred while fetching compensation data.', 'danger')
        return redirect(url_for('admin_main'))

# Update Compensation Status Route
@app.route('/admin/update_compensation', methods=['POST'])
@login_required
@admin_required
def update_compensation_status():
    form = UpdateCompensationStatusForm()

    if form.validate_on_submit():
        try:
            order_id = form.order_id.data
            employee_type = form.employee_type.data
            new_status = form.new_status.data

            # Validate employee type and status choices
            if employee_type not in ['tech', 'salesperson'] or new_status not in ['Paid', 'Failed']:
                flash('Invalid request parameters.', 'danger')
                return redirect(url_for('compensation_page'))

            # Set the field to update based on employee type
            update_field = 'tech_compensation_status' if employee_type == 'tech' else 'salesperson_compensation_status'

            # Update the order document in the database
            result = orders_collection.update_one(
                {'_id': ObjectId(order_id)},
                {'$set': {update_field: new_status}}
            )

            # Check if the document was modified
            if result.modified_count == 1:
                flash(f"Successfully updated {employee_type} compensation status to '{new_status}'.", 'success')
            else:
                flash('No changes were made. Please check the order ID.', 'warning')

            return redirect(url_for('compensation_page'))

        except Exception as e:
            app.logger.error(f"Error updating compensation status: {e}", exc_info=True)
            flash('An error occurred while updating compensation status.', 'danger')
            return redirect(url_for('compensation_page'))

    else:
        # Log form errors for debugging
        for field, errors in form.errors.items():
            for error in errors:
                app.logger.error(f"Error in {field}: {error}")
        flash('Invalid form submission.', 'danger')
        return redirect(url_for('compensation_page'))

#Collecting Payments\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\

@app.route('/payments/collecting_payments', methods=['GET', 'POST'])
@login_required
@tech_or_sales_required
def collecting_payments():
    # Get the current user's ID
    salesperson_id = str(current_user.id)
    
    if current_user.user_type == 'sales':
        # Salesperson sees only their unpaid orders
        unpaid_orders_cursor = orders_collection.find({
            'payment_status': 'Unpaid',
            'salesperson': salesperson_id
        })
    elif current_user.user_type == 'tech':
        # Technicians see all unpaid orders
        unpaid_orders_cursor = orders_collection.find({
            'payment_status': 'Unpaid'
        })
    else:
        # In case of an unexpected user_type, redirect
        flash('Access denied: Invalid user role.', 'danger')
        return redirect(url_for('index'))  # Replace 'index' with your actual home route
    
    # Convert the Cursor to a List
    unpaid_orders = list(unpaid_orders_cursor)
    
    return render_template('payments/collecting_payments.html', orders=unpaid_orders)

#Collect payment
@app.route('/collect_payment/<order_id>', methods=['GET', 'POST'])
@login_required
def collect_payment(order_id):
    form = CollectPaymentForm()
    try:
        order = orders_collection.find_one({'_id': ObjectId(order_id)})
    except InvalidId:
        flash('Invalid Order ID.', 'danger')
        return redirect(url_for('collecting_payments'))

    if not order:
        flash('Order not found.', 'danger')
        return redirect(url_for('collecting_payments'))

    if form.validate_on_submit():
        payment_method = form.payment_method.data
        payment_intent = None  # Initialize the variable

        if payment_method == 'card':
            payment_method_id = request.form.get('payment_method_id')
            if not payment_method_id:
                flash('Payment method ID not provided.', 'danger')
                return render_template(
                    'payments/collect_payment.html',
                    order=order,
                    form=form,
                    stripe_publishable_key=STRIPE_PUBLISHABLE_KEY
                )

            # Process the card payment using Stripe
            try:
                payment_intent = stripe.PaymentIntent.create(
                    amount=int(order['total'] * 100),  # Amount in cents
                    currency='usd',
                    payment_method=payment_method_id,
                    payment_method_types=['card'],  # Restrict to card payments
                    confirmation_method='automatic',  # Automatically confirm the PaymentIntent
                    confirm=True,
                    metadata={'order_id': str(order['_id'])}
                    # Removed 'automatic_payment_methods' to prevent conflicts
                )
                logger.info(f"PaymentIntent created: {payment_intent.id} with status {payment_intent.status}")

                if payment_intent.status == 'succeeded':
                    # Update the order in the database with payment details
                    update_fields = {
                        'payment_method': 'card',
                        'payment_status': 'Paid',
                        'stripe_payment_intent_id': payment_intent.id
                    }
                    orders_collection.update_one(
                        {'_id': ObjectId(order_id)},
                        {'$set': update_fields}
                    )

                    # Send notifications as configured
                    send_payment_collected_notifications(order, payment_method)

                    flash('Payment successful!', 'success')

                    # Redirect to the salesman's dashboard
                    return redirect(url_for('sales_main'))

                elif payment_intent.status == 'requires_action':
                    # Handle additional authentication if needed
                    # For simplicity, we'll notify the user and stay on the same page
                    orders_collection.update_one(
                        {'_id': ObjectId(order_id)},
                        {'$set': {'payment_method': 'card', 'payment_status': 'Requires Action'}}
                    )
                    flash('Additional authentication required. Please check your payment method.', 'info')
                    return render_template(
                        'payments/collect_payment.html',
                        order=order,
                        form=form,
                        stripe_publishable_key=STRIPE_PUBLISHABLE_KEY
                    )

                else:
                    # Payment is pending or failed, stay on the same page
                    orders_collection.update_one(
                        {'_id': ObjectId(order_id)},
                        {'$set': {'payment_method': 'card', 'payment_status': payment_intent.status.capitalize()}}
                    )
                    flash('Payment is being processed. Please wait.', 'info')
                    return render_template(
                        'payments/collect_payment.html',
                        order=order,
                        form=form,
                        stripe_publishable_key=STRIPE_PUBLISHABLE_KEY
                    )

            except stripe.error.CardError as e:
                # Handle card errors (e.g., declined cards)
                logger.error(f"Stripe CardError: {e.user_message}")
                flash(f"Card Error: {e.user_message}", 'danger')
                return render_template(
                    'payments/collect_payment.html',
                    order=order,
                    form=form,
                    stripe_publishable_key=STRIPE_PUBLISHABLE_KEY
                )
            except stripe.error.StripeError as e:
                # Handle other Stripe-related errors
                logger.error(f"StripeError: {e.user_message}")
                flash("Payment processing error. Please try again.", 'danger')
                return render_template(
                    'payments/collect_payment.html',
                    order=order,
                    form=form,
                    stripe_publishable_key=STRIPE_PUBLISHABLE_KEY
                )
            except Exception as e:
                # Handle unexpected errors
                logger.error(f"Unexpected error: {str(e)}")
                flash("An unexpected error occurred. Please try again.", 'danger')
                return render_template(
                    'payments/collect_payment.html',
                    order=order,
                    form=form,
                    stripe_publishable_key=STRIPE_PUBLISHABLE_KEY
                )

        elif payment_method == 'cash':
            # Handle cash payment
            update_fields = {
                'payment_method': 'cash',
                'payment_status': 'Paid'
            }
            orders_collection.update_one(
                {'_id': ObjectId(order_id)},
                {'$set': update_fields}
            )
            flash('Payment marked as paid (Cash).', 'success')

            # Send notifications as configured
            send_payment_collected_notifications(order, payment_method)

            # Redirect to the salesman's dashboard
            return redirect(url_for('sales_main'))  

    return render_template(
        'payments/collect_payment.html',
        order=order,
        form=form,
        stripe_publishable_key=STRIPE_PUBLISHABLE_KEY
    )


#Stripe webhook
@app.route('/stripe_webhook', methods=['POST'])
@csrf.exempt  # Exempt webhook route from CSRF protection
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        # Invalid payload
        return 'Invalid payload', 400
    except stripe.error.SignatureVerificationError:
        # Invalid signature
        return 'Invalid signature', 400

    # Handle the event
    if event['type'] == 'payment_intent.succeeded':
        payment_intent = event['data']['object']
        order_id = payment_intent.metadata.get('order_id')
        if order_id:
            orders_collection.update_one(
                {'_id': ObjectId(order_id)},
                {'$set': {'payment_status': 'Paid', 'stripe_payment_intent_id': payment_intent.id}}
            )
            logging.info(f"PaymentIntent {payment_intent.id} succeeded for Order {order_id}")
    elif event['type'] == 'payment_intent.payment_failed':
        payment_intent = event['data']['object']
        order_id = payment_intent.metadata.get('order_id')
        if order_id:
            orders_collection.update_one(
                {'_id': ObjectId(order_id)},
                {'$set': {'payment_status': 'Failed', 'stripe_payment_intent_id': payment_intent.id}}
            )
            logging.info(f"PaymentIntent {payment_intent.id} failed for Order {order_id}")
    # ... handle other event types as needed

    return '', 200





@app.route('/create_payment_intent', methods=['POST'])
@login_required
def create_payment_intent():
    data = request.get_json()
    order_id = data.get('order_id')
    
    try:
        order = orders_collection.find_one({'_id': ObjectId(order_id)})
    except InvalidId:
        return jsonify({'error': 'Invalid Order ID.'}), 400
    
    if not order:
        return jsonify({'error': 'Order not found.'}), 404
    
    if order['payment_status'] == 'Paid':
        return jsonify({'error': 'Order already paid.'}), 400
    
    # Create a PaymentIntent with payment_method_types=['card']
    payment_intent = stripe.PaymentIntent.create(
        amount=int(order['total'] * 100),  # Amount in cents
        currency='usd',
        payment_method_types=['card'],  # Apple Pay uses 'card' payment method
        description=f"Payment for Order {order_id}",
        metadata={'order_id': order_id},
    )
    
    logging.info(f"Created PaymentIntent {payment_intent.id} for Order {order_id}")
    
    return jsonify({'client_secret': payment_intent.client_secret})


@app.route('/update_order/<order_id>', methods=['POST'])
@login_required
def update_order(order_id):
    # Fetch the PaymentIntent status
    payment_intent_id = request.form.get('payment_intent_id')
    payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)
    
    if payment_intent.status == 'succeeded':
        orders_collection.update_one(
            {'_id': ObjectId(order_id)},
            {'$set': {'payment_status': 'Paid', 'payment_intent_id': payment_intent.id}}
        )
        flash('Payment collected successfully.', 'success')
    else:
        flash('Payment not successful.', 'danger')
    
    return redirect(url_for('collecting_payments'))

#Extra\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\




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
    




#Emails\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\
def send_email(to_email, subject, message):
    try:
        email = PMMail(api_key='POSTMARK_SERVER_TOKEN',
                       subject=subject,
                       sender='no-reply@cfautocare.biz',
                       to=to_email,
                       text_body=message)
        email.send()
        print("Email sent successfully.")
    except Exception as e:
        print(f"Error sending email: {e}")

#FOREMAILSENDING
def send_order_confirmation_email(user, order_details):
    if not user or not user.get('email'):
        logger.error("Attempted to send order confirmation email, but user has no email.")
        return

    try:
        subject = "Your Order Confirmation"
        sender_email = os.getenv('POSTMARK_SENDER_EMAIL')  # Ensure this matches your verified sender
        recipient_email = user['email']  # Define recipient_email from user data

        # Render the email templates
        html_body = render_template('emails/order_confirmation_email.html', user=user, order=order_details)
        text_body = render_template('emails/order_confirmation_email.txt', user=user, order=order_details)  # Optional

        # Send the email via Postmark
        send_postmark_email(
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            to_email=recipient_email,
            from_email=sender_email
        )
    except Exception as e:
        logger.error(f"Failed to send order confirmation email: {e}")


def send_admin_notification_email(salesperson_id, order, selected_products):
    """
    Sends a notification email to all admins when a guest order is scheduled by a salesperson.

    Args:
        salesperson_id (str): The ID of the salesperson who created the order.
        order (dict): The order document.
        selected_products (list): A list of product documents that were ordered.
    """
    try:
        # Fetch salesperson details
        salesperson = users_collection.find_one({'_id': ObjectId(salesperson_id)})
        if not salesperson:
            app.logger.error(f"Salesperson with ID {salesperson_id} not found.")
            salesperson_name = 'Unknown Salesperson'
        else:
            salesperson_name = salesperson.get('name', 'Unknown Salesperson')

        # Fetch all admin users
        admins = list(users_collection.find({'user_type': 'admin'}))
        admin_emails = [admin.get('email') for admin in admins if admin.get('email')]
        if not admin_emails:
            app.logger.error("No admin emails found to send notification.")
            return  # Or handle as appropriate

        subject = "New Guest Order"

        # Render email templates
        html_body = render_template(
            'emails/admin_guest_order_notification.html',
            order=order,
            products=selected_products,
            salesperson_name=salesperson_name,
            current_year=datetime.utcnow().year
        )
        text_body = render_template(
            'emails/admin_guest_order_notification.txt',
            order=order,
            products=selected_products,
            salesperson_name=salesperson_name
        )

        # Send email to each admin
        for admin_email in admin_emails:
            postmark_client.emails.send(
                From=os.getenv('POSTMARK_SENDER_EMAIL'),
                To=admin_email,
                Subject=subject,
                HtmlBody=html_body,
                TextBody=text_body,
                MessageStream="outbound"
            )
            app.logger.info(f"Admin notification email sent to {admin_email}")
    except Exception as e:
        app.logger.error(f"Failed to send admin notification email: {e}")




def send_payment_collected_notifications(order, payment_method):
    """
    Sends notifications to admins, the salesperson, and the customer when a payment is collected.

    Args:
        order (dict): The order document from the database.
        payment_method (str): The method of payment ('cash' or 'card').

    Returns:
        None
    """
    try:
        # 1. Fetch Customer Information
        if order.get('is_guest', False):
            customer_email = order.get('guest_email')
            customer_phone = order.get('guest_phone_number')
            customer_name = order.get('guest_name', 'Guest')
        else:
            user = users_collection.find_one({'_id': ObjectId(order.get('user'))})
            if user:
                customer_email = user.get('email')
                customer_phone = user.get('phone_number')
                customer_name = user.get('name', 'Valued Customer')
            else:
                customer_email = None
                customer_phone = None
                customer_name = 'Valued Customer'

        # 2. Fetch Salesperson Information
        salesperson_id = order.get('salesperson')  # Stored as string
        salesperson = users_collection.find_one({'_id': ObjectId(salesperson_id)}) if salesperson_id else None
        if salesperson:
            salesperson_email = salesperson.get('email')
            salesperson_phone = salesperson.get('phone_number')
            salesperson_name = salesperson.get('name', 'Salesperson')
        else:
            salesperson_email = None
            salesperson_phone = None
            salesperson_name = 'Salesperson'

        # 3. Fetch All Admin Users
        admins = list(users_collection.find({'user_type': 'admin'}))
        admin_emails = [admin.get('email') for admin in admins if admin.get('email')]
        admin_phones = [admin.get('phone_number') for admin in admins if admin.get('phone_number')]

        # 4. Prepare Notification Messages
        customer_subject = "Payment Confirmation - CFAC"
        salesperson_subject = "Payment Collected - CFAC"
        admin_subject = "Payment Collected - CFAC"

        # 5. Send Notifications to Customer
        if customer_email:
            html_body = render_template(
                'emails/customer_payment_confirmation.html',
                order=order,
                payment_method=payment_method,
                customer_name=customer_name
            )
            text_body = render_template(
                'emails/customer_payment_confirmation.txt',
                order=order,
                payment_method=payment_method,
                customer_name=customer_name
            )
            send_generic_email(
                recipient_email=customer_email,
                subject=customer_subject,
                html_body=html_body,
                text_body=text_body
            )

        # 6. Send Notifications to Salesperson
        if salesperson_email:
            html_body = render_template(
                'emails/salesperson_payment_collected.html',
                order=order,
                payment_method=payment_method,
                salesperson_name=salesperson_name
            )
            text_body = render_template(
                'emails/salesperson_payment_collected.txt',
                order=order,
                payment_method=payment_method,
                salesperson_name=salesperson_name
            )
            send_generic_email(
                recipient_email=salesperson_email,
                subject=salesperson_subject,
                html_body=html_body,
                text_body=text_body
            )

        # 7. Send Notifications to Admins
        for admin_email in admin_emails:
            html_body = render_template(
                'emails/admin_payment_collected.html',
                order=order,
                payment_method=payment_method,
                salesperson_name=salesperson_name
            )
            text_body = render_template(
                'emails/admin_payment_collected.txt',
                order=order,
                payment_method=payment_method,
                salesperson_name=salesperson_name
            )
            send_generic_email(
                recipient_email=admin_email,
                subject=admin_subject,
                html_body=html_body,
                text_body=text_body
            )

        # 8. Send SMS Notifications (If Applicable)
        # Assuming you want to continue using AWS SNS for SMS
        # Ensure phone numbers are in E.164 format
        if customer_phone:
            customer_message = f"Dear {customer_name}, your payment for Order {order.get('_id')} has been successfully received via {payment_method.capitalize()}."
            send_sms(customer_phone, customer_message)

        if salesperson_phone:
            salesperson_message = f"Dear {salesperson_name}, you have successfully collected a payment for Order {order.get('_id')} via {payment_method.capitalize()}."
            send_sms(salesperson_phone, salesperson_message)

        for admin_phone in admin_phones:
            admin_message = f"A payment for Order {order.get('_id')} has been collected via {payment_method.capitalize()} by Salesperson {salesperson_name}."
            send_sms(admin_phone, admin_message)

    except Exception as e:
        app.logger.error(f"Error sending payment collected notifications: {e}", exc_info=True)


def send_generic_email(recipient_email, subject, html_body, text_body=None):
    """
    Sends an email to the specified recipient with both HTML and plain-text content.

    Args:
        recipient_email (str): The recipient's email address.
        subject (str): The subject of the email.
        html_body (str): The HTML content of the email.
        text_body (str, optional): The plain-text content of the email.

    Returns:
        None
    """
    sender_email = os.getenv('POSTMARK_SENDER_EMAIL')  # Ensure this matches your verified sender

    try:
        postmark_client.emails.send(
            From=sender_email,
            To=recipient_email,
            Subject=subject,
            HtmlBody=html_body,
            TextBody=text_body,
            MessageStream="outbound"
        )
        app.logger.info(f"Email sent to {recipient_email} with subject '{subject}'.")
    except Exception as e:
        app.logger.error(f"Failed to send email to {recipient_email}: {e}")

#\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\
@app.route('/test_env')
def test_env():
    username = os.getenv('SES_SMTP_USERNAME')
    password = os.getenv('SES_SMTP_PASSWORD')
    return f"Username: {username}, Password Length: {len(password) if password else 'Not Set'}"






if __name__ == '__main__':
    app.run(debug=True)
 


