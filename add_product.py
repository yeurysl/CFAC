# add_product.py

from pymongo import MongoClient

# MongoDB connection string
client = MongoClient("mongodb+srv://yeurys:ZvTt25OmDOp24yCW@cfac.8ba8p.mongodb.net/cfacdb?retryWrites=true&w=majority&appName=cfac", tls=True, tlsAllowInvalidCertificates=True)
db = client["cfacdb"]
products_collection = db["products"]

def add_product():
    product = {
        "name": "Sedan Complete Detailing",
        "description": "A comprehensive detailing service for sedans, including interior and exterior cleaning.",
        "price": 130.00,
        "category": "Detailing Services",
        "image_url": "/static/images/sedan_detailing.jpg"  # Update with actual image path
    }

    products_collection.insert_one(product)
    print("Product added successfully!")

if __name__ == "__main__":
    add_product()
