# config.py

import os
from dotenv import load_dotenv

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY')
    WTF_CSRF_TIME_LIMIT = 3600
    MONGODB_URI = os.getenv('MONGODB_URI')
    STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')
    STRIPE_PUBLISHABLE_KEY = os.getenv('STRIPE_PUBLISHABLE_KEY')
    STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

    TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
    TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
    TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')
    POSTMARK_SERVER_TOKEN = os.getenv('POSTMARK_SERVER_TOKEN')
    POSTMARK_SENDER_EMAIL = os.getenv("POSTMARK_SENDER_EMAIL")

    ENV = os.getenv('ENV', 'development')
    JWT_SECRET = os.getenv('JWT_SECRET')  

    CHECKOUT_SUCCESS_URL = os.getenv('CHECKOUT_SUCCESS_URL')
    CHECKOUT_CANCEL_URL = os.getenv('CHECKOUT_CANCEL_URL')
