# core.py
from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app, jsonify
from flask_login import login_required, logout_user, current_user, login_user
from bson.objectid import ObjectId, InvalidId
from datetime import datetime
import re
import json
from forms import EmployeeLoginForm, UpdateAccountForm
from extensions import User 
from utility import register_filters



core_bp = Blueprint('core', __name__)

@core_bp.route('/base')
def base():
    """
    Render a base template or partial layout.
    """
    return render_template('base.html')







@core_bp.route('/')
def home():
    # Hardcoded vehicle sizes
    vehicle_sizes  = [
        {"display": "Coup 2 Seater", "value": "coupe_2_seater"},
        {"display": "Truck 2 Seater", "value": "truck_2_seater"},
        {"display": "Truck 4 Seater", "value": "truck_4_seater"},
        {"display": "Hatchback 2 Door", "value": "hatchback_2_door"},
        {"display": "Hatchback 4 Door", "value": "hatchback_4_door"},
        {"display": "Sedan 2 Door", "value": "sedan_2_door"},
        {"display": "Sedan 4 Door", "value": "sedan_4_door"},
        {"display": "SUV 4 Seater", "value": "suv_4_seater"},
        {"display": "SUV 6 Seater", "value": "suv_6_seater"},
        {"display": "Minivan 6 Seater", "value": "minivan_6_seater"}
    ]

    # Fetch services from the database
    services_collection = current_app.config['SERVICES_COLLECTION']
    services = list(services_collection.find({'active': True}))
    for service in services:
        service['_id'] = str(service['_id'])  # Convert ObjectId to string

    # Default image
    default_image = url_for('static', filename='default_service.jpg')

    return render_template('home.html', vehicle_sizes=vehicle_sizes , services=services, default_image=default_image)


@core_bp.route('/aboutus')
def about():
    """
    About Us Page Route
    """
    return render_template('aboutus.html')


@core_bp.route('/careers')
def careers():
    """
    Careers Page Route
    """
    return render_template('careers.html')


@core_bp.route('/header')
def header():
    """
    Render a header snippet or partial.
    """
    return render_template('header.html')


@core_bp.route('/logout')
@login_required
def logout():
    """
    Logout Route
    Logs out the current user, flashes a success message, and redirects to home.
    """
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('core.home'))


@core_bp.route('/account_settings', methods=['GET', 'POST'])
@login_required
def account_settings():
    """
    Account Settings Route
    Allows a logged-in user to update their name, email, phone number, and address.
    """
    users_collection = current_app.config['USERS_COLLECTION']
    user_id = current_user.id  # This is the string version of ObjectId

    try:
        user = users_collection.find_one({'_id': ObjectId(user_id)})
    except (InvalidId, TypeError):
        user = None

    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('core.home'))

    form = UpdateAccountForm()

    if request.method == 'POST':
        if form.validate_on_submit():
            # Extract form data
            name = form.name.data.strip()
            email = (form.email.data.lower().strip() 
                     if form.email.data else user.get('email', None))
            phone_number = form.phone_number.data.strip()
            street_address = form.street_address.data.strip()
            city = form.city.data.strip()
            country = form.country.data.strip()
            zip_code = form.zip_code.data.strip()

            # Prepare fields to update
            update_fields = {
                'name': name,
                'phone_number': phone_number,
                'address.street_address': street_address,
                'address.city': city,
                'address.country': country,
                'address.zip_code': zip_code
            }

            # Only update email if provided in the form
            if form.email.data:
                update_fields['email'] = email

            try:
                users_collection.update_one(
                    {'_id': ObjectId(user_id)},
                    {'$set': update_fields}
                )
                flash('Account settings updated successfully.', 'success')
                return redirect(url_for('core.account_settings'))
            except Exception as e:
                current_app.logger.error(f"Error updating user: {e}")
                flash('An error occurred while updating your account settings. Please try again.', 'danger')
                return redirect(url_for('core.account_settings'))
        else:
            flash('Please correct the errors in the form.', 'danger')
    else:
        # Pre-populate form with existing user data
        form.name.data = user.get('name', '')
        form.email.data = user.get('email', '')
        form.phone_number.data = user.get('phone_number', '')
        user_address = user.get('address', {})
        form.street_address.data = user_address.get('street_address', '')
        form.city.data = user_address.get('city', '')
        form.country.data = user_address.get('country', '')
        form.zip_code.data = user_address.get('zip_code', '')

    return render_template('account_settings.html', form=form, user=user)
@core_bp.route('/employee_login', methods=['GET', 'POST'])
def employee_login():
    """
    Employee Login Route (for admin/tech/sales).
    """
    form = EmployeeLoginForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        password = form.password.data

        # Example of how you might fetch user from the database
        # Adjust to match your DB logic
        users_collection = current_app.config['USERS_COLLECTION']
        user_record = users_collection.find_one({
            'username': username,
            'user_type': {'$in': ['admin', 'tech', 'sales']}
        })

        if not user_record:
            flash('Invalid username or user type.', 'danger')
            return render_template('employee_login.html', form=form)

        # Check the password against the stored hash
        from flask_bcrypt import check_password_hash
        if check_password_hash(user_record['password'], password):
            # Build a User object for Flask-Login
            user_obj = User(str(user_record['_id']), user_record['user_type'])
            login_user(user_obj)
            flash(f'Logged in successfully as {user_record["user_type"]}.', 'success')
            return redirect(url_for('core.home'))
        else:
            flash('Invalid password.', 'danger')

    return render_template('employee_login.html', form=form)

@core_bp.route('/privacy_policy')
def privacy_policy():
    """
    Render the Privacy Policy page.
    """
    return render_template('privacy_policy.html')
@core_bp.route('/refund_policy')
def refund_policy():
    """
    Render the Refund and Service Issue Policy page.
    """
    return render_template('refund_policy.html')
