#db.py
from pymongo import MongoClient
import os

def init_db(app):
    mongodb_uri = app.config['MONGODB_URI']
    client = MongoClient(mongodb_uri, tls=True, tlsAllowInvalidCertificates=True)
    db = client["cfacdb"]
    # Store collections on the app configuration for global access
    app.config['USERS_COLLECTION'] = db["users"]
    app.config['ORDERS_COLLECTION'] = db["orders"]
    app.config['ESTIMATE_REQUESTS_COLLECTION'] = db["estimaterequests"]
    app.config['SERVICES_COLLECTION'] = db["services"]
