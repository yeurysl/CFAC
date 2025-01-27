# blueprints/tech.py

from flask import (
    Blueprint, render_template, request, flash,
    redirect, url_for, current_app
)
from flask_login import login_required, current_user
from bson.objectid import ObjectId
from datetime import datetime
import logging
import math

from decorators import tech_required
from forms import EmployeeLoginForm

tech_bp = Blueprint('tech', __name__, url_prefix='/tech')


@tech_bp.route('/main')
@login_required
@tech_required
def tech_main():
    """
    Displays all 'ordered' orders for a technician.
    """
    try:
        orders_collection = current_app.config['ORDERS_COLLECTION']
        users_collection = current_app.config['USERS_COLLECTION']
        products_collection = current_app.config['PRODUCTS_COLLECTION']

        # 1) Define the filter for orders with status 'ordered'
        filter_query = {'status': 'ordered'}

        # 2) Fetch all 'ordered' orders, sorted by order_date descending
        orders = list(orders_collection.find(filter_query).sort('order_date', -1))

        # 3) Enrich each order
        for order in orders:
            # Who placed the order? If user = 'some_email', display that email; otherwise 'Guest'
            if order.get('user'):
                user_record = users_collection.find_one({'email': order['user']})
                order['user_display'] = user_record['email'] if user_record else 'Unknown'
            else:
                order['user_display'] = 'Guest'

            # Convert date strings to datetime objects
            if isinstance(order.get('order_date'), str):
                order['order_date'] = datetime.strptime(order['order_date'], '%Y-%m-%d %H:%M:%S')
            if isinstance(order.get('service_date'), str):
                order['service_date'] = datetime.strptime(order['service_date'], '%Y-%m-%d')

            # Fetch product details
            try:
                product_ids = []
                for pid in order.get('products', []):
                    try:
                        product_ids.append(ObjectId(pid))
                    except Exception as e:
                        current_app.logger.error(
                            f"Invalid product ID {pid} in order {order.get('_id')}: {e}"
                        )

                if product_ids:
                    products = list(products_collection.find({'_id': {'$in': product_ids}}))
                else:
                    products = []

                order['product_details'] = products
            except Exception as e:
                current_app.logger.error(
                    f"Error fetching products for order {order.get('_id')}: {e}",
                    exc_info=True
                )
                order['product_details'] = []

        return render_template('tech/main.html', orders=orders)
    except Exception as e:
        current_app.logger.error(f"Error fetching orders in tech_main: {e}", exc_info=True)
        flash('An error occurred while fetching orders.', 'danger')
        # If your "home" route is in 'core' blueprint with function 'home':
        return redirect(url_for('core.home'))


@tech_bp.route('/my_schedule')
@login_required
@tech_required
def my_schedule():
    """
    Displays orders that have been assigned (scheduled) to the current tech.
    """
    try:
        orders_collection = current_app.config['ORDERS_COLLECTION']
        products_collection = current_app.config['PRODUCTS_COLLECTION']
        users_collection = current_app.config['USERS_COLLECTION']

        # 1) Fetch scheduled orders assigned to the current tech
        filter_query = {
            'status': 'scheduled',
            'added_to_scheduled_by': current_user.id
        }
        orders = list(orders_collection.find(filter_query).sort('service_date', 1))

        # 2) Enrich each order
        for order in orders:
            # Fetch product details
            try:
                product_ids = [ObjectId(pid) for pid in order.get('products', [])]
                products = list(products_collection.find({'_id': {'$in': product_ids}}))
                order['product_details'] = products
            except Exception as e:
                current_app.logger.error(
                    f"Error fetching products for order {order.get('_id')}: {e}",
                    exc_info=True
                )
                order['product_details'] = []

            # Convert date strings
            if isinstance(order.get('order_date'), str):
                order['order_date'] = datetime.strptime(order['order_date'], '%Y-%m-%d %H:%M:%S')
            if isinstance(order.get('service_date'), str):
                order['service_date'] = datetime.strptime(order['service_date'], '%Y-%m-%d')

            # Include address details
            if order.get('guest_address'):
                order['address'] = order['guest_address']
            elif order.get('user'):
                user_record = users_collection.find_one({'email': order['user']})
                if user_record and 'address' in user_record:
                    order['address'] = user_record['address']
                else:
                    order['address'] = None
            else:
                order['address'] = None

            # Construct a full address string
            if order.get('address'):
                address_components = [
                    order['address'].get('street_address'),
                    order['address'].get('unit_apt'),
                    order['address'].get('city'),
                    order['address'].get('country'),
                    order['address'].get('zip_code')
                ]
                # Filter out empty components
                full_address = ', '.join(filter(None, address_components))
                order['full_address'] = full_address
            else:
                order['full_address'] = None

        return render_template('tech/my_schedule.html', orders=orders)
    except Exception as e:
        current_app.logger.error(f"Error fetching schedule: {e}", exc_info=True)
        flash('An error occurred while fetching your schedule.', 'danger')
        return redirect(url_for('core.home'))


@tech_bp.route('/order/<order_id>/schedule', methods=['POST'])
@login_required
@tech_required
def schedule_order(order_id):
    """
    Allows the tech to move an 'ordered' order into 'scheduled' status.
    """
    try:
        orders_collection = current_app.config['ORDERS_COLLECTION']
        users_collection = current_app.config['USERS_COLLECTION']

        order = orders_collection.find_one({'_id': ObjectId(order_id)})
        if not order:
            flash('Order not found.', 'danger')
            return redirect(url_for('tech.tech_main'))

        if order.get('status', '').lower() != 'ordered':
            flash('Only orders with status "ordered" can be scheduled.', 'warning')
            return redirect(url_for('tech.tech_main'))

        # Mark it as scheduled and note who scheduled it
        orders_collection.update_one(
            {'_id': ObjectId(order_id)},
            {
                '$set': {
                    'status': 'scheduled',
                    'added_to_scheduled_by': current_user.id
                }
            }
        )

        updated_order = orders_collection.find_one({'_id': ObjectId(order_id)})

        # Determine customer details for notification
        if updated_order.get('is_guest'):
            customer_email = updated_order.get('guest_email')
            customer_name = updated_order.get('guest_name', 'Guest')
        else:
            customer_email = updated_order.get('user')
            user_record = users_collection.find_one({'email': customer_email})
            customer_name = user_record.get('name', 'Valued Customer') if user_record else 'Valued Customer'

        # Tech name
        scheduled_by_username = updated_order.get('scheduled_by')
        if scheduled_by_username:
            tech_user = users_collection.find_one({'username': scheduled_by_username})
            tech_name = tech_user.get('full_name', 'Technician') if tech_user else 'Technician'
        else:
            tech_name = 'Technician'

        # Send an email if we have a valid customer_email
        if customer_email:
            try:
                send_order_scheduled_email(customer_email, customer_name, updated_order, tech_name)
                flash(
                    f'Order {order_id} has been scheduled successfully and notification sent to the customer.',
                    'success'
                )
            except Exception as e:
                current_app.logger.error(f"Failed to send notification email for order {order_id}: {e}", exc_info=True)
                flash(f'Order {order_id} has been scheduled, but failed to send notification email.', 'warning')
        else:
            flash(f'Order {order_id} has been scheduled successfully.', 'success')

        return redirect(url_for('tech.tech_main'))
    except Exception as e:
        current_app.logger.error(f"Error scheduling order {order_id}: {e}", exc_info=True)
        flash('An error occurred while scheduling the order.', 'danger')
        return redirect(url_for('tech.tech_main'))


def send_order_scheduled_email(to_email, customer_name, order, tech_name):
    """
    Sends an email notification to the customer when their order is scheduled.
    """
    try:
        # For example, you might do:
        postmark_token = current_app.config.get('POSTMARK_SERVER_TOKEN')
        # or twilio_client = current_app.config.get('TWILIO_CLIENT'), etc.

        current_year = datetime.utcnow().year
        html_body = render_template(
            'emails/order_scheduled_email.html',
            customer_name=customer_name,
            order=order,
            tech_name=tech_name,
            current_year=current_year
        )
        text_body = render_template(
            'emails/order_scheduled_email.txt',
            customer_name=customer_name,
            order=order,
            tech_name=tech_name
        )

        # Example with Postmark:
        postmark_client = current_app.config.get('POSTMARK_CLIENT')  # Or however you store it
        if not postmark_client:
            current_app.logger.warning("No Postmark client found in config.")
            return

        postmark_client.emails.send(
            From=os.getenv('POSTMARK_SENDER_EMAIL'),
            To=to_email,
            Subject='Your Order Has Been Scheduled!',
            HtmlBody=html_body,
            TextBody=text_body,
            MessageStream="outbound"
        )
    except Exception as e:
        current_app.logger.error(f"Error sending email to {to_email}: {e}", exc_info=True)
        raise e


@tech_bp.route('/view_order/<order_id>', methods=['GET'])
@login_required
@tech_required
def tech_view_order(order_id):
    """
    Displays order details to the tech who scheduled it.
    """
    try:
        orders_collection = current_app.config['ORDERS_COLLECTION']
        products_collection = current_app.config['PRODUCTS_COLLECTION']
        users_collection = current_app.config['USERS_COLLECTION']

        order = orders_collection.find_one({'_id': ObjectId(order_id)})
        if not order:
            flash('Order not found.', 'danger')
            return redirect(url_for('tech.my_schedule'))

        # Check if the current tech is the one who scheduled the order
        if order.get('added_to_scheduled_by') != current_user.id:
            flash('You do not have permission to view this order.', 'danger')
            return redirect(url_for('tech.my_schedule'))

        product_ids = [ObjectId(pid) for pid in order.get('products', [])]
        products = list(products_collection.find({'_id': {'$in': product_ids}}))
        products_dict = {str(p['_id']): p for p in products}

        # Convert date strings
        if isinstance(order.get('order_date'), str):
            order['order_date'] = datetime.strptime(order['order_date'], '%Y-%m-%d %H:%M:%S')
        if isinstance(order.get('service_date'), str):
            order['service_date'] = datetime.strptime(order['service_date'], '%Y-%m-%d')

        # Build address
        if order.get('guest_address'):
            order['address'] = order['guest_address']
        elif order.get('user'):
            user_record = users_collection.find_one({'email': order['user']})
            order['address'] = user_record.get('address') if user_record and 'address' in user_record else None
        else:
            order['address'] = None

        if order.get('address'):
            address_components = [
                order['address'].get('street_address'),
                order['address'].get('unit_apt'),
                order['address'].get('city'),
                order['address'].get('country'),
                order['address'].get('zip_code')
            ]
            order['full_address'] = ', '.join(filter(None, address_components))
        else:
            order['full_address'] = None

        return render_template('payments/tech_view_order.html', order=order, products_dict=products_dict)
    except Exception as e:
        current_app.logger.error(f"Error accessing order {order_id}: {e}", exc_info=True)
        flash('An error occurred while accessing the order.', 'danger')
        return redirect(url_for('tech.my_schedule'))
