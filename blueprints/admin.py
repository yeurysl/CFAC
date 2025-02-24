# blueprints/admin.py

from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from bson.objectid import ObjectId
from datetime import datetime
import math
from zoneinfo import ZoneInfo
import logging

# Import your custom decorator for admin access
from decorators import admin_required

# Import your forms
from forms import DeleteOrderForm, EditOrderForm, UpdateCompensationStatusForm

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')




@admin_bp.route('/main')
@login_required
@admin_required
def admin_main():
    """
    Main admin dashboard route adapted for orders that use services.
    """
    try:
        # Access collections via current_app.config
        orders_collection = current_app.config['ORDERS_COLLECTION']
        users_collection = current_app.config['USERS_COLLECTION']
        estimaterequests_collection = current_app.config['ESTIMATE_REQUESTS_COLLECTION']
        services_collection = current_app.config['SERVICES_COLLECTION']  # New collection for services

        # 1. Fetch All Estimate Requests
        estimates = list(estimaterequests_collection.find())

        # 2. Pagination Parameters
        page = request.args.get('page', 1, type=int)
        per_page = 20


        # 3. Fetch Total Number of Orders
        total_orders = orders_collection.count_documents({})


    # 2. Guest Orders: orders where the field "is_guest" is True
        guest_orders = orders_collection.count_documents({'is_guest': True})
        
        # 3. Checkout Orders (customer orders): you can compute this as all orders minus guest orders
        checkout_orders = total_orders - guest_orders

        # Calculate percentages (guarding against division by zero)
        guest_percentage = (guest_orders / total_orders * 100) if total_orders > 0 else 0
        checkout_percentage = (checkout_orders / total_orders * 100) if total_orders > 0 else 0

        # Total pages for pagination
        total_pages = (total_orders + per_page - 1) // per_page


        total_pages = (total_orders + per_page - 1) // per_page

        # 4. Fetch Orders for the Current Page
        orders_cursor = orders_collection.find().sort('creation_date', -1).skip((page - 1) * per_page).limit(per_page)
        orders = list(orders_cursor)

        # 5. Enrich Orders with Additional Details
        for order in orders:
            is_guest = order.get('is_guest', False)
            order['order_type'] = 'Guest Order' if is_guest else 'Customer Order'

            # 5.1 Handle Payment Status
            order['payment_status'] = order.get('payment_status', 'Unpaid')

            if is_guest:
                # For guest orders, fetch salesperson details
                salesperson_id = order.get('salesperson')
                if salesperson_id:
                    try:
                        salesperson_obj_id = ObjectId(salesperson_id)
                        salesperson = users_collection.find_one({'_id': salesperson_obj_id, 'user_type': 'sales'})
                        order['salesperson_name'] = (
                            salesperson.get('full_name', 'Unknown') if salesperson else 'Unknown'
                        )
                    except Exception:
                        order['salesperson_name'] = 'Unknown'
                else:
                    order['salesperson_name'] = 'Not Assigned'
            else:
                # For customer orders, use guest_email (or user) field as needed
                email = order.get('guest_email') or order.get('user')
                if email:
                    user = users_collection.find_one({'email': email})
                    order['user_email'] = user.get('email', 'Unknown') if user else 'Unknown'
                else:
                    order['user_email'] = 'Unknown'

            # 5.2 Convert Date Fields (now expecting ISO-8601 format)
            for date_field in [ 'service_date', 'creation_date']:
                date_value = order.get(date_field)
                if isinstance(date_value, str):
                        try:
                            # Parse the date string, ensuring that UTC times are correctly recognized.
                            if date_value.endswith('Z'):
                                dt = datetime.fromisoformat(date_value.replace("Z", "+00:00"))
                            else:
                                dt = datetime.fromisoformat(date_value)
                            # Convert to Eastern Time (handles both EST and EDT automatically)
                            dt_est = dt.astimezone(ZoneInfo("America/New_York"))
                            order[date_field] = dt_est
                        except ValueError:
                            current_app.logger.error(
                                f"Invalid {date_field} format for order {order.get('_id')}: {date_value}"
                            )
                            order[date_field] = None


            # 5.3 Get Service Details instead of product details
            service_codes = order.get('selectedServices', [])
            if service_codes:
                # Assuming each service document has a 'service_code' field to match against
                services = list(services_collection.find({'service_code': {'$in': service_codes}}))
                order['service_details'] = services
            else:
                order['service_details'] = []

            # Optionally, set a total field from your service data (if applicable)
            order['total'] = order.get('final_price') or order.get('services_total')

            # 5.4 Fetch Technician Details if Scheduled
            technician = order.get('technician')
            if technician and ObjectId.is_valid(technician):
                tech = users_collection.find_one({'_id': ObjectId(technician)})
                order['tech_name'] = tech.get('name', 'Unknown Tech') if tech else 'Unknown Tech'
            else:
                order['tech_name'] = 'Not Scheduled Yet'

   # *** New code: Count users by type ***
        tech_count = users_collection.count_documents({'user_type': 'tech'})
        customer_count = users_collection.count_documents({'user_type': 'customer'})
        admin_count = users_collection.count_documents({'user_type': 'admin'})
        sales_count = users_collection.count_documents({'user_type': 'sales'})

        # 6. Pass Variables to the Template
        return render_template(
            'admin/main.html',
            requests=estimates,
            orders=orders,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
            tech_count=tech_count,
            customer_count=customer_count,
            admin_count=admin_count,
            sales_count=sales_count,
            total_orders=total_orders,
            guest_orders=guest_orders,
            checkout_orders=checkout_orders,
            guest_percentage=guest_percentage,
            checkout_percentage=checkout_percentage
        )
    except Exception as e:
        current_app.logger.error(f"Error in admin_main route: {e}", exc_info=True)
        flash('An error occurred while fetching orders.', 'danger')
        return redirect(url_for('core.home'))






@admin_bp.route('/view_order/<order_id>')
@login_required
@admin_required
def view_order(order_id):
    """
    View a single order in detail.
    """
    try:
        orders_collection = current_app.config['ORDERS_COLLECTION']
        users_collection = current_app.config['USERS_COLLECTION']

        try:
            order_obj_id = ObjectId(order_id)
        except Exception:
            flash('Invalid order ID.', 'danger')
            return redirect(url_for('admin.admin_main'))

        order = orders_collection.find_one({'_id': order_obj_id})
        if not order:
            flash('Order not found.', 'danger')
            return redirect(url_for('admin.admin_main'))

        delete_form = DeleteOrderForm()

        is_guest = order.get('is_guest', False)
        order['order_type'] = 'Guest Order' if is_guest else 'Customer Order'

        if is_guest:
            salesperson_id = order.get('salesperson')
            if salesperson_id:
                try:
                    salesperson_obj_id = ObjectId(salesperson_id)
                    salesperson = users_collection.find_one(
                        {'_id': salesperson_obj_id, 'user_type': 'sales'}
                    )
                    order['salesperson_name'] = (
                        salesperson.get('name', 'Unknown') if salesperson else 'Unknown'
                    )
                except Exception:
                    order['salesperson_name'] = 'Unknown'
            else:
                order['salesperson_name'] = 'Not Assigned'
        else:
            # For customer orders
            user_record = users_collection.find_one({'email': order.get('user')})
            order['user_email'] = user_record.get('email', 'Unknown') if user_record else 'Unknown'
            order['user_name'] = user_record.get('name', 'N/A') if user_record else 'N/A'
            order['user_phone'] = user_record.get('phone_number', 'N/A') if user_record else 'N/A'
            order['user_address'] = user_record.get('address', {}) if user_record else {}

        technician_id = order.get('technician')
        if technician_id:
            try:
                technician_user = users_collection.find_one({'_id': ObjectId(technician_id)})
                if technician_user:
                    order['technician_name'] = technician_user.get('name', 'Unknown')
                    order['technician_email'] = technician_user.get('email', 'Unknown')
                else:
                    order['technician_name'] = 'Unknown'
                    order['technician_name'] = 'Unknown'
            except Exception:
                order['technician_name'] = 'Unknown'
                order['technician_name'] = 'Unknown'
        else:
            order['technician_name'] = 'Not Scheduled'
            order['technician_name'] = ''

        for date_field in ['creation_date', 'service_date']:
            if isinstance(order.get(date_field), str):
                try:
                    if order[date_field].endswith('Z'):
                        order[date_field] = datetime.fromisoformat(order[date_field].replace("Z", "+00:00"))
                    else:
                        order[date_field] = datetime.fromisoformat(order[date_field])
                except ValueError:
                    current_app.logger.error(
                        f"Invalid {date_field} format for order {order.get('_id')}: {order.get(date_field)}"
                    )
                    order[date_field] = None


        return render_template('admin/view_order.html', order=order, delete_form=delete_form)
    except Exception as e:
        current_app.logger.error(f"Error in view_order route: {e}", exc_info=True)
        flash('An error occurred while fetching the order details.', 'danger')
        return redirect(url_for('admin.admin_main'))


@admin_bp.route('/edit_order/<order_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_order(order_id):
    """
    Edit an existing order's status, total, or service date.
    """
    try:
        orders_collection = current_app.config['ORDERS_COLLECTION']
        if not ObjectId.is_valid(order_id):
            flash('Invalid order ID.', 'danger')
            return redirect(url_for('admin.admin_main'))

        order_obj_id = ObjectId(order_id)
        order = orders_collection.find_one({'_id': order_obj_id})
        if not order:
            flash('Order not found.', 'danger')
            return redirect(url_for('admin.admin_main'))

        if request.method == 'POST':
            form = EditOrderForm()
            if form.validate_on_submit():
                try:
                    total_float = float(form.total_amount.data)
                except (ValueError, TypeError):
                    flash('Invalid total amount.', 'danger')
                    return redirect(url_for('admin.edit_order', order_id=order_id))

                service_date = form.service_date.data
                if service_date and not isinstance(service_date, datetime):
                    from datetime import time
                    service_datetime = datetime.combine(service_date, time.min)
                else:
                    service_datetime = service_date

                update_result = orders_collection.update_one(
                    {'_id': order_obj_id},
                    {
                        '$set': {
                            'status': form.status.data,
                            'payment_method': form.payment_method.data,
                            'total': total_float,
                            'service_date': service_datetime
                        }
                    }
                )
                if update_result.modified_count:
                    flash('Order updated successfully.', 'success')
                else:
                    flash('No changes made to the order.', 'info')
                return redirect(url_for('admin.view_order', order_id=order_id))
            else:
                current_app.logger.warning(f"Form validation failed: {form.errors}")
                flash('Please correct the errors in the form.', 'danger')
        else:
            form = EditOrderForm()
            form.status.data = order.get('status', '')
            form.payment_method.data = order.get('payment_method', '')
            form.total_amount.data = order.get('total', '')

            service_date = order.get('service_date')
            if service_date:
                if isinstance(service_date, datetime):
                    form.service_date.data = service_date.date()
                else:
                    form.service_date.data = service_date
            else:
                form.service_date.data = None

        return render_template('admin/edit_order.html', form=form, order=order)
    except Exception as e:
        current_app.logger.error(f"Error in edit_order route: {e}", exc_info=True)
        flash('An error occurred while editing the order.', 'danger')
        return redirect(url_for('admin.admin_main'))


@admin_bp.route('/delete_order/<order_id>', methods=['POST'])
@login_required
@admin_required
def delete_order(order_id):
    """
    Delete an order from the database.
    """
    orders_collection = current_app.config['ORDERS_COLLECTION']
    form = DeleteOrderForm()
    if form.validate_on_submit():
        try:
            order_obj_id = ObjectId(order_id)
        except Exception:
            flash('Invalid order ID.', 'danger')
            current_app.logger.warning(f"Delete attempt with invalid order ID: {order_id}")
            return redirect(url_for('admin.admin_main'))

        result = orders_collection.delete_one({'_id': order_obj_id})
        if result.deleted_count == 1:
            flash('Order deleted successfully.', 'success')
            current_app.logger.info(f"Order {order_id} deleted successfully.")
        else:
            flash('Order not found.', 'warning')
            current_app.logger.warning(f"Attempted to delete non-existent order: {order_id}")
    else:
        flash('Invalid CSRF token.', 'danger')
        current_app.logger.warning(f"Invalid CSRF token when attempting to delete order: {order_id}")

    return redirect(url_for('admin.admin_main'))


@admin_bp.route('/delete/<user_id>', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    """
    Delete a user from the database (except yourself).
    """
    users_collection = current_app.config['USERS_COLLECTION']

    if user_id == str(current_user.id):
        flash('You cannot delete your own account.', 'danger')
        return redirect(url_for('admin.manage_users'))

    users_collection.delete_one({'_id': ObjectId(user_id)})
    flash('User deleted successfully.', 'success')
    return redirect(url_for('admin.manage_users'))


@admin_bp.route('/manage_users')
@login_required
@admin_required
def manage_users():
    """
    Displays and manages all users in the database.
    """
    try:
        users_collection = current_app.config['USERS_COLLECTION']
        delete_form = DeleteOrderForm()

        page = request.args.get('page', 1, type=int)
        per_page = 20
        search_query = request.args.get('search', '').strip()
        user_type = request.args.get('user_type', '')
        sort_by = request.args.get('sort_by', 'creation_date')
        sort_order = request.args.get('sort_order', 'asc')

        query = {}
        if search_query:
            from bson.errors import InvalidId
            try:
                query = {
                    '$or': [
                        {'email': {'$regex': search_query, '$options': 'i'}},
                        {'_id': ObjectId(search_query)}
                    ]
                }
            except InvalidId:
                query = {
                    'email': {'$regex': search_query, '$options': 'i'}
                }

        if user_type:
            query['user_type'] = user_type

        sort_direction = 1 if sort_order == 'asc' else -1
        if sort_by == 'creation_date':
            sort_field = 'creation_date'
        else:
            sort_field = 'email'

        total_users = users_collection.count_documents(query)
        total_pages = (total_users + per_page - 1) // per_page

        users = list(users_collection.find(query)
                     .sort(sort_field, sort_direction)
                     .skip((page - 1) * per_page)
                     .limit(per_page))

        return render_template(
            'admin/manage_users.html',
            users=users,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
            delete_form=delete_form,
            search_query=search_query,
            user_type=user_type,
            sort_by=sort_by,
            sort_order=sort_order
        )
    except Exception as e:
        current_app.logger.error(f"Error in manage_users route: {e}", exc_info=True)
        flash('An error occurred while fetching users.', 'danger')
        return redirect(url_for('admin.admin_main'))


@admin_bp.route('/view_user/<user_id>')
@login_required
@admin_required
def view_user(user_id):
    """
    Displays a single user's details.
    """
    try:
        users_collection = current_app.config['USERS_COLLECTION']
        user_obj_id = ObjectId(user_id)
    except Exception:
        flash('Invalid user ID.', 'danger')
        current_app.logger.warning(f"Invalid ObjectId for view_user: {user_id}")
        return redirect(url_for('admin.manage_users'))

    user = users_collection.find_one({'_id': user_obj_id})
    if not user:
        flash('User not found.', 'danger')
        current_app.logger.warning(f"User not found: {user_id}")
        return redirect(url_for('admin.manage_users'))

    # Convert creation_date to datetime if it's a string
    if 'creation_date' in user and isinstance(user['creation_date'], str):
        try:
            user['creation_date'] = datetime.strptime(user['creation_date'], '%Y-%m-%d %H:%M:%S')
        except ValueError:
            current_app.logger.error(
                f"Invalid creation_date format for user ID {user_id}: {user['creation_date']}"
            )
            user['creation_date'] = None

    current_app.logger.info(f"Displaying user details for user ID: {user_id}")
    return render_template('admin/view_user.html', user=user)


@admin_bp.route('/compensation')
@login_required
@admin_required
def compensation_page():
    """
    Displays a page for handling compensation for techs and sales.
    """
    try:
        orders_collection = current_app.config['ORDERS_COLLECTION']
        users_collection = current_app.config['USERS_COLLECTION']

        page = request.args.get('page', 1, type=int)
        per_page = 20
        total_orders = orders_collection.count_documents({})
        total_pages = (total_orders + per_page - 1) // per_page

        orders_cursor = orders_collection.find().sort('service_date', -1)\
                                             .skip((page - 1) * per_page)\
                                             .limit(per_page)
        orders = list(orders_cursor)

        for order in orders:
            # Ensure _id is a string for URL purposes
            order['_id'] = str(order['_id'])
            
            # Retrieve technician using either key: 'technician' or 'technician_id'
            tech_id = order.get('technician') or order.get('technician_id')
            if tech_id and ObjectId.is_valid(str(tech_id)):
                technician = users_collection.find_one({'_id': ObjectId(tech_id)})
                order['technician_name'] = technician.get('name', 'Unknown') if technician else 'Unknown'
            else:
                order['technician_name'] = 'Not Assigned'

            # Retrieve salesperson using either key: 'salesperson' or 'salesperson_id'
            salesperson_id = order.get('salesperson') or order.get('salesperson_id')
            if salesperson_id and ObjectId.is_valid(str(salesperson_id)):
                salesperson = users_collection.find_one({'_id': ObjectId(salesperson_id)})
                order['salesperson_name'] = salesperson.get('name', 'Unknown') if salesperson else 'Unknown'
            else:
                order['salesperson_name'] = 'Not Assigned'

       # Convert service_date to a datetime object.
            service_date = order.get('service_date')
            if isinstance(service_date, str):
                try:
                    if 'T' in service_date:
                        # Handle ISO 8601 format.
                        if service_date.endswith('Z'):
                            order['service_date'] = datetime.strptime(service_date, '%Y-%m-%dT%H:%M:%SZ')
                        else:
                            order['service_date'] = datetime.fromisoformat(service_date)
                    else:
                        # Fallback to the simpler date format.
                        order['service_date'] = datetime.strptime(service_date, '%Y-%m-%d')
                except ValueError:
                    current_app.logger.error(
                        f"Invalid service_date format for order ID {order.get('_id')}: {service_date}"
                    )
                    order['service_date'] = None

        # Optionally, if you still need the update forms (for example, if you want to retain update functionality)
        forms = {order['_id']: UpdateCompensationStatusForm(prefix=order['_id']) for order in orders}

        return render_template(
            'admin/compensation.html',
            orders=orders,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
            forms=forms  # Remove this if your new template no longer uses the forms.
        )
    except Exception as e:
        current_app.logger.error(f"Error in compensation_page route: {e}", exc_info=True)
        flash('An error occurred while fetching compensation data.', 'danger')
        return redirect(url_for('admin.admin_main'))



@admin_bp.route('/create_compensation', methods=['POST'])
@login_required
@admin_required
def create_compensation():
    """
    Creates the technician or salesperson compensation field on an order and sets it to 'Paid'.
    """
    try:
        orders_collection = current_app.config['ORDERS_COLLECTION']
        # Get parameters from the form submission.
        order_id = request.form.get('order_id')
        employee_type = request.form.get('employee_type')

        # Validate required parameters.
        if not order_id or employee_type not in ['tech', 'salesperson']:
            flash('Invalid request parameters.', 'danger')
            return redirect(url_for('admin.compensation_page'))

        # Determine which field to update.
        update_field = 'tech_compensation_status' if employee_type == 'tech' else 'salesperson_compensation_status'

        # Always set the field to 'Paid' (this will create the field if it does not exist)
        result = orders_collection.update_one(
            {'_id': ObjectId(order_id)},
            {'$set': {update_field: 'Paid'}}
        )

        if result.modified_count == 1:
            flash(f"Successfully created {employee_type} compensation field as 'Paid'.", 'success')
        else:
            flash('No changes were made. Please check the order ID.', 'warning')
        return redirect(url_for('admin.compensation_page'))
    except Exception as e:
        current_app.logger.error(f"Error creating compensation field: {e}", exc_info=True)
        flash('An error occurred while updating compensation status.', 'danger')
        return redirect(url_for('admin.compensation_page'))



@admin_bp.route('/pending_users', methods=['GET'])
@login_required
@admin_required
def view_pending_users():
    """
    Admin route to display users in the 'users_to_approve' collection
    who are pending approval.
    """
    try:
        db = current_app.config["MONGO_CLIENT"]
        users_to_approve_coll = db.users_to_approve
        
        # Fetch all pending user documents
        pending_users = list(users_to_approve_coll.find())
        
        # Convert ObjectIds to strings for template usage
        for user_doc in pending_users:
            user_doc['_id'] = str(user_doc['_id'])
        
        return render_template('admin/pending_users.html', pending_users=pending_users)
    except Exception as e:
        current_app.logger.error(f"Error in view_pending_users route: {e}", exc_info=True)
        flash('An error occurred while fetching pending users.', 'danger')
        return redirect(url_for('admin.admin_main'))