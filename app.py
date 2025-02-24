# app.py
import monkey_patch

from collections import MutableMapping
from apscheduler.schedulers.background import BackgroundScheduler
from api_tech import start_scheduler  
import os
import decimal
import logging
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv
from pymongo import MongoClient
from config import Config
from postmark_client import postmark_client, is_valid_email

# Import extensions
from extensions import bcrypt, login_manager, csrf, create_unique_indexes
from db import init_db
from utility import register_filters

# API imports
from api_auth import api_bp
from api_account import api_account_bp
from api_sales import api_sales_bp
from api_tech import api_tech_bp
from api_contract import contract_bp

# Import blueprints
from blueprints.customer import customer_bp
from blueprints.admin import admin_bp
from blueprints.core import core_bp
from flask import render_template
from error_handlers import register_error_handlers

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
    bcrypt.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    # Flask-Login settings
    login_manager.login_view = 'employee_login'
    login_manager.login_message_category = 'info'

    # Logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    # MongoDB
    mongodb_uri = app.config['MONGODB_URI']
    client = MongoClient(mongodb_uri, tls=True, tlsAllowInvalidCertificates=True)
    db = client["cfacdb"]
    app.config["MONGO_CLIENT"] = db  
    init_db(app)

    # Register Blueprints
    app.register_blueprint(customer_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(core_bp)


    # Register custom error pages
    register_error_handlers(app)

    # Register APIs
    app.register_blueprint(api_bp)
    app.register_blueprint(api_tech_bp)
    app.register_blueprint(api_sales_bp)
    app.register_blueprint(api_account_bp)
    app.register_blueprint(contract_bp)

    # Register custom error pages
    register_error_handlers(app)
    
    # Exempt API routes from CSRF protection
    csrf.exempt(api_sales_bp)
    csrf.exempt(api_tech_bp)
    csrf.exempt(contract_bp)

    with app.app_context():
        create_unique_indexes()
        register_filters()

    return app

if __name__ == '__main__':
    app = create_app()
    start_scheduler(app)  # Start the scheduler
    app.run(debug=True)
else:
    app = create_app()
    start_scheduler(app)  # Optionally start scheduler even in production
