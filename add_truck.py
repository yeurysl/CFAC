
from pymongo import MongoClient
import os


from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
# MongoDB connection string
MONGODB_URI = os.getenv('MONGODB_URI')

# MongoDB connection string
client = MongoClient(MONGODB_URI, tls=True, tlsAllowInvalidCertificates=True)

if not MONGODB_URI:
    raise ValueError("MONGODB_URI environment variable is not set.")

db = client["cfacdb"]
products_collection = db["products"]

def add_product():
    product = {
        "name": "Truck Complete Detailing",
        "description": "A comprehensive detailing service for trucks, including interior and exterior cleaning.",
        "price": 160.00,
        "category": "Detailing Services",
        "image_url": "/static/images/truck.png"  # Update with actual image path
    }

    products_collection.insert_one(product)
    print("Product added successfully!")

if __name__ == "__main__":
    add_product()
