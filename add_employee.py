# add_employee.py

from pymongo import MongoClient
from dotenv import load_dotenv
from flask_bcrypt import Bcrypt
import getpass  # For secure password input
import os
import re  # For email validation

# Load environment variables from .env file
load_dotenv()

# Initialize Bcrypt
bcrypt = Bcrypt()

# Get MongoDB connection string from environment variables
MONGODB_URI = os.getenv('MONGODB_URI')

if not MONGODB_URI:
    raise ValueError("No MongoDB URI provided. Set the MONGODB_URI environment variable.")

# MongoDB connection
client = MongoClient(MONGODB_URI, tls=True, tlsAllowInvalidCertificates=True)

# Connect to your database and collection
db = client["cfacdb"]
users_collection = db["users"]

def is_valid_email(email):
    # Simple regex for email validation
    regex = r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'
    return re.match(regex, email)

def add_user():
    email = input("Enter new employee's email: ").strip().lower()
    if not email:
        print("Email cannot be empty.")
        return

    if not is_valid_email(email):
        print("Invalid email format.")
        return

    # Securely get the password without echoing
    password = getpass.getpass("Enter new employee's password: ").strip()
    confirm_password = getpass.getpass("Confirm password: ").strip()

    if not password:
        print("Password cannot be empty.")
        return

    if password != confirm_password:
        print("Passwords do not match.")
        return

    # Enforce password complexity (optional)
    if len(password) < 8:
        print("Password must be at least 8 characters long.")
        return

    # Prompt for user type
    user_type = input("Enter user type (admin/employee): ").strip().lower()
    if user_type not in ['admin', 'employee']:
        print("Invalid user type. Must be 'admin' or 'employee'.")
        return

    # Check if the email already exists
    if users_collection.find_one({'email': email}):
        print(f"An account with email '{email}' already exists.")
        return

    # Hash the password
    hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')

    # Create a new user document
    user = {
        'email': email,
        'password': hashed_password,
        'user_type': user_type  # Add user type to the document
    }

    # Insert the user into the collection
    try:
        users_collection.insert_one(user)
        print(f"Employee '{email}' added successfully as a '{user_type}'!")
    except Exception as e:
        print("An error occurred while adding the user:", e)

if __name__ == '__main__':
    add_user()
