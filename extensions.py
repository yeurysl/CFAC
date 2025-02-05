# extensions.py

from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin
from flask_wtf import CSRFProtect
from flask import current_app
from bson.objectid import ObjectId
import logging
from flask_mail import Mail


# Initialize extensions
bcrypt = Bcrypt()
login_manager = LoginManager()
csrf = CSRFProtect()

class User(UserMixin):
    def __init__(self, user_id, user_type):
        self.id = user_id  # String version of MongoDB's ObjectId
        self.user_type = user_type

@login_manager.user_loader
def load_user(user_id):
    """
    Flask-Login calls this to load a user from user_id in the session.
    """
    try:
        # Access Mongo via current_app
        users_collection = current_app.config['USERS_COLLECTION']
        user_record = users_collection.find_one({"_id": ObjectId(user_id)})
        if user_record and user_record.get('user_type') in ['customer', 'admin', 'tech', 'sales']:
            return User(str(user_record['_id']), user_record['user_type'])
    except Exception as e:
        current_app.logger.error(f"Error loading user {user_id}: {e}")
        return None
    return None

def create_unique_indexes():
    """
    Creates unique and sparse indexes on 'email' and 'phone_number'
    fields in the users_collection, using current_app context.
    """
    try:
        users_collection = current_app.config['USERS_COLLECTION']
        users_collection.create_index('email', unique=True, sparse=True)
        users_collection.create_index('phone_number', unique=True, sparse=True)
        current_app.logger.info("Unique indexes created on 'email' and 'phone_number'.")
    except Exception as e:
        current_app.logger.error(f"Error creating indexes: {e}")
