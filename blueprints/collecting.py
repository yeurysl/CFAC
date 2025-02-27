# blueprints/collecting.py

from flask import (
    Blueprint, render_template, request, flash, redirect,
    url_for, current_app, jsonify
)
from flask_login import login_required, current_user
from datetime import datetime
from bson.objectid import ObjectId
import stripe
import logging
import os

# If you have a custom decorator for roles:
from decorators import tech_or_sales_required

# Forms
from forms import CollectPaymentForm

# Configuration variables
STRIPE_PUBLISHABLE_KEY = os.getenv('STRIPE_PUBLISHABLE_KEY')
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')

# Create the blueprint with the URL prefix '/payments'
collecting_bp = Blueprint('collecting', __name__, url_prefix='/payments')


@collecting_bp.route('/collecting_payments', methods=['GET', 'POST'])
@login_required
@tech_or_sales_required
def collecting_payments():
    """
    Display unpaid orders.
    - Sales users see only their own unpaid orders.
    - Tech users see all unpaid orders.
    """
    orders_collection = current_app.config['ORDERS_COLLECTION']
    salesperson_id = str(current_user.id)

    if current_user.user_type == 'sales':
        # Salesperson sees only their unpaid orders
        unpaid_orders_cursor = orders_collection.find({
            'payment_status': 'Unpaid',
            'salesperson': salesperson_id
        })
    elif current_user.user_type == 'tech':
        # Technicians see all unpaid orders
        unpaid_orders_cursor = orders_collection.find({
            'payment_status': 'Unpaid'
        })
    else:
        flash('Access denied: Invalid user role.', 'danger')
        return redirect(url_for('index'))  # Replace 'index' with your actual home route

    unpaid_orders = list(unpaid_orders_cursor)
    return render_template('payments/collecting_payments.html', orders=unpaid_orders)


@collecting_bp.route('/collect_payment/<order_id>', methods=['GET', 'POST'])
@login_required
def collect_payment(order_id):
    """
    Process a payment for the given order.
    """
    orders_collection = current_app.config['ORDERS_COLLECTION']
    form = CollectPaymentForm()

    # Attempt to fetch the order by ID
    try:
        order = orders_collection.find_one({'_id': ObjectId(order_id)})
    except Exception:
        flash('Invalid Order ID.', 'danger')
        return redirect(url_for('collecting.collecting_payments'))

    if not order:
        flash('Order not found.', 'danger')
        return redirect(url_for('collecting.collecting_payments'))

    if form.validate_on_submit():
        payment_method = form.payment_method.data
        payment_intent = None  # Initialize variable

        if payment_method == 'card':
            payment_method_id = request.form.get('payment_method_id')
            if not payment_method_id:
                flash('Payment method ID not provided.', 'danger')
                return render_template(
                    'payments/collect_payment.html',
                    order=order,
                    form=form,
                    stripe_publishable_key=STRIPE_PUBLISHABLE_KEY
                )

            try:
                # Create a PaymentIntent with Stripe
                payment_intent = stripe.PaymentIntent.create(
                    amount=int(order['total'] * 100),  # Convert dollars to cents
                    currency='usd',
                    payment_method=payment_method_id,
                    payment_method_types=['card'],
                    confirmation_method='automatic',
                    confirm=True,
                    metadata={'order_id': str(order['_id'])}
                )
                current_app.logger.info(
                    f"PaymentIntent created: {payment_intent.id} with status {payment_intent.status}"
                )

                if payment_intent.status == 'succeeded':
                    update_fields = {
                        'payment_method': 'card',
                        'payment_status': 'downpaymentcollected',
                        'stripe_payment_intent_id': payment_intent.id
                    }
                    orders_collection.update_one(
                        {'_id': ObjectId(order_id)},
                        {'$set': update_fields}
                    )

                    # Import and send payment notifications
                    from notis import send_postmark_email, send_notification_to_tech, get_device_token_for_tech

                    send_payment_collected_notifications(order, payment_method)

                    # NEW: Notify the technician
                    technician_id = order.get("technician")
                    if technician_id:
                        # Fetch Technician Email
                        tech_email = current_app.config['USERS_COLLECTION'].find_one({"_id": ObjectId(technician_id)}).get("email")
                        if tech_email:
                            subject = "Order now available"
                            text_body = f"Check out this order in your dashboard."
                            html_body = f"""
                            <html>
                                <body>
                                    <p>Dear Technician,</p>
                                    <p>This order is now available Order ID: <strong>{order_id}</strong>.</p>
                                    <p>Check out this order in your dashboard.</p>
                                </body>
                            </html>
                            """
                            send_postmark_email(tech_email, subject, text_body, html_body)

                        # Fetch and Send APN Notification
                        device_token = get_device_token_for_tech(technician_id)
                        if device_token:
                            message = f"Downpayment received for order {order_id}. Get ready!"
                            send_notification_to_tech(technician_id, order_id, threshold=None, device_token=device_token, custom_message=message)

                    flash('Payment successful!', 'success')
                    return redirect(url_for('sales.sales_main'))

                elif payment_intent.status == 'requires_action':
                    orders_collection.update_one(
                        {'_id': ObjectId(order_id)},
                        {'$set': {
                            'payment_method': 'card',
                            'payment_status': 'Requires Action'
                        }}
                    )
                    flash('Additional authentication required. Please check your payment method.', 'info')
                    return render_template(
                        'payments/collect_payment.html',
                        order=order,
                        form=form,
                        stripe_publishable_key=STRIPE_PUBLISHABLE_KEY
                    )
                else:
                    # Payment is pending or failed
                    orders_collection.update_one(
                        {'_id': ObjectId(order_id)},
                        {'$set': {
                            'payment_method': 'card',
                            'payment_status': payment_intent.status.capitalize()
                        }}
                    )
                    flash('Payment is being processed. Please wait.', 'info')
                    return render_template(
                        'payments/collect_payment.html',
                        order=order,
                        form=form,
                        stripe_publishable_key=STRIPE_PUBLISHABLE_KEY
                    )

            except stripe.error.CardError as e:
                current_app.logger.error(f"Stripe CardError: {e.user_message}")
                flash(f"Card Error: {e.user_message}", 'danger')
                return render_template(
                    'payments/collect_payment.html',
                    order=order,
                    form=form,
                    stripe_publishable_key=STRIPE_PUBLISHABLE_KEY
                )
            except stripe.error.StripeError as e:
                current_app.logger.error(f"StripeError: {e.user_message}")
                flash("Payment processing error. Please try again.", 'danger')
                return render_template(
                    'payments/collect_payment.html',
                    order=order,
                    form=form,
                    stripe_publishable_key=STRIPE_PUBLISHABLE_KEY
                )
            except Exception as e:
                current_app.logger.error(f"Unexpected error: {str(e)}")
                flash("An unexpected error occurred. Please try again.", 'danger')
                return render_template(
                    'payments/collect_payment.html',
                    order=order,
                    form=form,
                    stripe_publishable_key=STRIPE_PUBLISHABLE_KEY
                )

        elif payment_method == 'cash':
            update_fields = {
                'payment_method': 'cash',
                'payment_status': 'Paid'
            }
            orders_collection.update_one(
                {'_id': ObjectId(order_id)},
                {'$set': update_fields}
            )
            flash('Payment marked as paid (Cash).', 'success')

            from utils import send_payment_collected_notifications
            send_payment_collected_notifications(order, payment_method)

            return redirect(url_for('sales.sales_main'))

    # If GET request or form not validated, render the template
    return render_template(
        'payments/collect_payment.html',
        order=order,
        form=form,
        stripe_publishable_key=STRIPE_PUBLISHABLE_KEY
    )


@collecting_bp.route('/stripe_webhook', methods=['POST'])
def stripe_webhook():
    """
    Endpoint to handle Stripe webhook events.
    """
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except ValueError:
        return 'Invalid payload', 400
    except stripe.error.SignatureVerificationError:
        return 'Invalid signature', 400

    orders_collection = current_app.config['ORDERS_COLLECTION']
    event_type = event.get('type', '')

    if event_type == 'payment_intent.succeeded':
        payment_intent = event['data']['object']
        order_id = payment_intent['metadata'].get('order_id')
        if order_id:
            orders_collection.update_one(
                {'_id': ObjectId(order_id)},
                {'$set': {
                    'payment_status': 'Paid',
                    'stripe_payment_intent_id': payment_intent['id']
                }}
            )
            current_app.logger.info(
                f"PaymentIntent {payment_intent['id']} succeeded for Order {order_id}"
            )
    elif event_type == 'payment_intent.payment_failed':
        payment_intent = event['data']['object']
        order_id = payment_intent['metadata'].get('order_id')
        if order_id:
            orders_collection.update_one(
                {'_id': ObjectId(order_id)},
                {'$set': {
                    'payment_status': 'Failed',
                    'stripe_payment_intent_id': payment_intent['id']
                }}
            )
            current_app.logger.info(
                f"PaymentIntent {payment_intent['id']} failed for Order {order_id}"
            )
    # ... handle other event types as needed

    return '', 200


@collecting_bp.route('/create_payment_intent', methods=['POST'])
@login_required
def create_payment_intent():
    """
    Creates a PaymentIntent with Stripe for a given order.
    """
    data = request.get_json()
    order_id = data.get('order_id')
    orders_collection = current_app.config['ORDERS_COLLECTION']

    try:
        order = orders_collection.find_one({'_id': ObjectId(order_id)})
    except Exception:
        return jsonify({'error': 'Invalid Order ID.'}), 400

    if not order:
        return jsonify({'error': 'Order not found.'}), 404

    if order.get('payment_status') == 'Paid':
        return jsonify({'error': 'Order already paid.'}), 400

    payment_intent = stripe.PaymentIntent.create(
        amount=int(order['total'] * 100),
        currency='usd',
        payment_method_types=['card'],
        description=f"Payment for Order {order_id}",
        metadata={'order_id': order_id},
    )

    current_app.logger.info(
        f"Created PaymentIntent {payment_intent.id} for Order {order_id}"
    )

    return jsonify({'client_secret': payment_intent.client_secret})


@collecting_bp.route('/update_order/<order_id>', methods=['POST'])
@login_required
def update_order(order_id):
    """
    Updates an order's payment status based on PaymentIntent.
    """
    payment_intent_id = request.form.get('payment_intent_id')
    orders_collection = current_app.config['ORDERS_COLLECTION']

    try:
        payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)
    except Exception as e:
        current_app.logger.error(f"Error retrieving PaymentIntent: {e}")
        flash("Error retrieving payment information.", 'danger')
        return redirect(url_for('collecting.collecting_payments'))

    if payment_intent.status == 'succeeded':
        orders_collection.update_one(
            {'_id': ObjectId(order_id)},
            {'$set': {
                'payment_status': 'Paid',
                'payment_intent_id': payment_intent.id
            }}
        )
        flash('Payment collected successfully.', 'success')
    else:
        flash('Payment not successful.', 'danger')

    return redirect(url_for('collecting.collecting_payments'))
