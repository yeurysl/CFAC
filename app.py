from flask import Flask, render_template, request, redirect, url_for, session
from pymongo import MongoClient
from flask_bcrypt import Bcrypt
from functools import wraps
import os



app = Flask(__name__)
app.secret_key = os.urandom(24)

bcrypt = Bcrypt(app)

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

@app.route('/employeepage')
def employeepage():
    return render_template('/employeepage.html')

@app.route('/header')
def header():
    return render_template('/header.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password'].encode('utf-8')
        user = users_collection.find_one({'username': username})
        
        if user and bcrypt.check_password_hash(user['password'], password):
            session['username'] = username
            return redirect(url_for('employeepage'))  # Ensure 'home' route exists
        else:
            return 'Invalid username or password'
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('home'))

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/protected')
@login_required
def protected():
    return "This is a protected page!"

def add_user(username, password):  # Updated function to add a user
    # Hash the password
    hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
    
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
