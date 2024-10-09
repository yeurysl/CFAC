# add_employee.py

from pymongo import MongoClient
from flask_bcrypt import Bcrypt
import getpass  # For secure password input

# Initialize Bcrypt
bcrypt = Bcrypt()

# MongoDB connection string
client = MongoClient("mongodb+srv://yeurys:ZvTt25OmDOp24yCW@cfac.8ba8p.mongodb.net/cfacdb?retryWrites=true&w=majority&appName=cfac", tls=True, tlsAllowInvalidCertificates=True)

# Connect to your database and collection
db = client["cfacdb"]
users_collection = db["users"]

# add_employee.py

from pymongo import MongoClient
from flask_bcrypt import Bcrypt
import getpass  # For secure password input

# Initialize Bcrypt
bcrypt = Bcrypt()

# MongoDB connection string (use the same one from your app.py)
client = MongoClient("mongodb+srv://yeurys:ZvTt25OmDOp24yCW@cfac.8ba8p.mongodb.net/cfacdb?retryWrites=true&w=majority&appName=cfac", tls=True, tlsAllowInvalidCertificates=True)

# Connect to your database and collection
db = client["cfacdb"]
users_collection = db["users"]

def add_user():
    username = input("Enter new employee's username: ").strip()
    if not username:
        print("Username cannot be empty.")
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

    # Prompt for user type
    user_type = input("Enter user type (admin/employee): ").strip().lower()
    if user_type not in ['admin', 'employee']:
        print("Invalid user type. Must be 'admin' or 'employee'.")
        return

    # Check if the username already exists
    if users_collection.find_one({'username': username}):
        print(f"Username '{username}' already exists.")
        return

    # Hash the password
    hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')

    # Create a new user document
    user = {
        'username': username,
        'password': hashed_password,
        'user_type': user_type  # Add user type to the document
    }

    # Insert the user into the collection
    try:
        users_collection.insert_one(user)
        print(f"Employee '{username}' added successfully as a '{user_type}'!")
    except Exception as e:
        print("An error occurred while adding the user:", e)


if __name__ == '__main__':
    add_user()
