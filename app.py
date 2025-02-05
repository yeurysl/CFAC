# app.py

import os
import decimal
import logging
from notis import api_sales_bp 
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv
from pymongo import MongoClient
from config import Config


# Import extensions
from extensions import bcrypt, login_manager, csrf, create_unique_indexes
from db import init_db
from utility import register_filters

# API imports
from api_auth import api_bp
from api_account import api_account_bp
from api_sales import api_sales_bp
# Import blueprints
from blueprints.customer import customer_bp
from blueprints.admin import admin_bp
from blueprints.core import core_bp

load_dotenv()

def create_app():
    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    # Basic config
    app.secret_key = os.getenv('SECRET_KEY')
    JWT_SECRET = os.getenv('JWT_SECRET', 'default-jwt-secret')
    app.config['MONGODB_URI'] = os.getenv('MONGODB_URI')
    app.config['WTF_CSRF_TIME_LIMIT'] = None
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

 

    # Load configuration from Config class
    app.config.from_object(Config)
    

    # Decimal precision
    decimal.getcontext().prec = 28

    # Initialize Flask extensions
    bcrypt.init_app(app)         # Initialize bcrypt
    login_manager.init_app(app)  # Initialize login_manager
    csrf.init_app(app)           # Initialize csrf

    # Flask-Login settings
    login_manager.login_view = 'tech_admin_login'
    login_manager.login_message_category = 'info'

    # Logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    # MongoDB
    mongodb_uri = app.config['MONGODB_URI']
    client = MongoClient(mongodb_uri, tls=True, tlsAllowInvalidCertificates=True)
    db = client["cfacdb"]
    app.config["MONGO_CLIENT"] = db  
    init_db(app)  # Sets up app.config['USERS_COLLECTION'], etc.

    # Register Blueprints
    app.register_blueprint(customer_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(core_bp)

    # Register APIs
    app.register_blueprint(api_bp)
    app.register_blueprint(api_sales_bp)
    app.register_blueprint(api_account_bp)

    # Exempt API routes from CSRF protection
    csrf.exempt(api_sales_bp)

    # Now in an app context, call create_unique_indexes() + register_filters()
    with app.app_context():
        create_unique_indexes()
        register_filters()  # So Jinja can see 'format_date_with_suffix' & 'currency'

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)
else:
    # Ensure a WSGI callable is available when running via Gunicorn.
    app = create_app()
