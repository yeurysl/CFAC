from flask import Flask, render_template
from pymongo import MongoClient
import bcrypt

app = Flask(__name__)

client = MongoClient("mongodb+srv://yeurys:ZvTt25OmDOp24yCW@cfac.8ba8p.mongodb.net/cfacdb?retryWrites=true&w=majority&appName=cfac", tls=True, tlsAllowInvalidCertificates=True)

db = client["cfacdb"]
users_collection = db["users"]  # Updated collection to "users"

@app.route('/base')
def base():
    return render_template('/base.html')

@app.route('/')
def home():
    return render_template('/home.html')

@app.route('/aboutus')
def about():
    return render_template('/aboutus.html')
@app.route('/careers')
def career():
    return render_template('/careers.html')

@app.route('/header')
def header():
    return render_template('/header.html')

def add_user(username, password):  # Updated function to add a user
    # Hash the password
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    
    # Create a new user document
    user = {
        'username': username,
        'password': hashed_password
    }
    
    # Insert the user into the collection
    users_collection.insert_one(user)
    print(f'User {username} added successfully!')

# Use this function to add new users
if __name__ == '__main__':
    username = input("Enter username: ")
    password = input("Enter password: ")
    add_user(username, password)  # Updated to add user instead of employee

if __name__ == '__main__':
    app.run(debug=True)
