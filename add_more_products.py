# add_product.py

import os
from pymongo import MongoClient
from dotenv import load_dotenv
# MongoDB connection string


load_dotenv()

MONGODB_URI = os.getenv('MONGODB_URI')

# MongoDB connection string
client = MongoClient(MONGODB_URI, tls=True, tlsAllowInvalidCertificates=True)
db = client["cfacdb"]
products_collection = db["products"]
def add_products():
    # Define a list of products to add
    products = [
        {
            "name": "Coupe Complete Detailing",
            "description": "A comprehensive detailing service for sedans, including interior and exterior cleaning.",
            "price": 120.00,
            "category": "Detailing Services",
            "image_url": "/static/creatives/coupe.webp"  # Ensure this image exists in the specified path
        },
        {
            "name": "SUV Complete Detailing",
            "description": "A comprehensive detailing service for SUVs, including interior and exterior cleaning.",
            "price": 150.00,
            "category": "Detailing Services",
            "image_url": "/static/creatives/suv.webp"  # Ensure this image exists in the specified path
        },
      
    ]

    # Insert multiple products at once
    try:
        result = products_collection.insert_many(products)
        print(f"Successfully added {len(result.inserted_ids)} products!")
    except Exception as e:
        print(f"An error occurred while adding products: {e}")


if __name__ == "__main__":
    add_products()
