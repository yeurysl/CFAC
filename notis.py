#notis.py
import os
import logging
import traceback
from flask import current_app, render_template, url_for
from postmarker.core import PostmarkClient
from datetime import datetime
from flask import Flask
from bson.objectid import ObjectId
from postmark_client import postmark_client, is_valid_email


logger = logging.getLogger(__name__)


def send_tech_notification_email(order, selected_services):
    """
    Sends a notification email to all technicians about a new order.

    :param order: The order document inserted into the database.
    """
    try:
        # Corrected Query: Fetch technicians with 'user_type' as 'tech'
        techs_cursor = users_collection.find({'user_type': 'tech'})
        techs = list(techs_cursor)  # Convert cursor to list for multiple iterations if needed
        num_techs = len(techs)
        logger.info(f"Number of technicians fetched: {num_techs}")

        if num_techs == 0:
            logger.warning("No technicians found with 'user_type': 'tech'. Ensure technicians are added to the database.")
            return

        tech_count = 0  # Counter for successful emails
        failed_techs = []

        for tech in techs:
            tech_email = tech.get('email')
            tech_name = tech.get('full_name', 'Technician')  # Assuming a 'full_name' field exists

            if not tech_email:
                logger.warning(f"Technician '{tech_name}' does not have an email and was skipped.")
                continue

            logger.info(f"Preparing to send email to Technician: {tech_email}")

            subject = "Tech Notif: New Job Available"
            sender_email = os.getenv('POSTMARK_SENDER_EMAIL')  # Ensure this matches your verified sender

            # Render the email body using HTML and plain-text templates
            html_body = render_template(
                'emails/tech_order_notification.html',
                order=order,
                selected_services=selected_services,
                tech_name=tech_name,
                current_year=datetime.utcnow().year
            )

            text_body = render_template(
                'emails/tech_order_notification.txt',
                order=order,
                selected_services=selected_services,
                tech_name=tech_name
            )

            try:
                send_postmark_email(
                    subject=subject,
                    to_email=tech_email,
                    from_email=sender_email,
                    text_body=text_body,
                    html_body=html_body
                )
                logger.info(f"Notification email sent to technician: {tech_email}")
                tech_count += 1
            except Exception as e:
                logger.error(f"Failed to send email to {tech_email}: {e}")
                failed_techs.append({'email': tech_email, 'error': str(e)})

        logger.info(f"Total technician emails sent successfully: {tech_count}")
        if failed_techs:
            logger.warning(f"Failed to send emails to the following technicians: {failed_techs}")

    except Exception as e:
        logger.error(f"Error in send_tech_notification_email: {e}")





def send_postmark_email(subject, to_email, from_email, text_body, html_body=None):
    """
    Sends an email via Postmark.
    
    :param subject: Subject line of the email.
    :param to_email: Recipient's email address.
    :param from_email: Sender's email address.
    :param text_body: Plain-text body of the email.
    :param html_body: (Optional) HTML body of the email.
    :return: The response from Postmark.
    """
    # Validate email addresses.
    if not is_valid_email(to_email):
        raise ValueError("Invalid recipient email address")
    if not is_valid_email(from_email):
        raise ValueError("Invalid sender email address")
    
    # Use the Postmark client to send the email.
    response = postmark_client.emails.send(
        From=from_email,
        To=to_email,
        Subject=subject,
        TextBody=text_body,
        HtmlBody=html_body if html_body else text_body
    )
    
    return response




#FOREMAILSENDING
def send_order_confirmation_email(user, order_details):
    if not user or not user.get('email'):
        logger.error("Attempted to send order confirmation email, but user has no email.")
        return

    try:
        subject = "Your Order Confirmation"
        sender_email = os.getenv('POSTMARK_SENDER_EMAIL')  # Ensure this matches your verified sender
        recipient_email = user['email']  # Define recipient_email from user data

        # Render the email templates
        html_body = render_template('emails/order_confirmation_email.html', user=user, order=order_details)
        text_body = render_template('emails/order_confirmation_email.txt', user=user, order=order_details)  # Optional

        # Send the email via Postmark
        send_postmark_email(
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            to_email=recipient_email,
            from_email=sender_email
        )
    except Exception as e:
        logger.error(f"Failed to send order confirmation email: {e}")


def send_admin_notification_email(salesperson_id, order, selected_services):
    """
    Sends a notification email to all admins when a guest order is scheduled by a salesperson.

    Args:
        salesperson_id (str): The ID of the salesperson who created the order.
        order (dict): The order document.
        selected_services (list): A list of product documents that were ordered.
    """
    try:
        # Fetch salesperson details
        salesperson = users_collection.find_one({'_id': ObjectId(salesperson_id)})
        if not salesperson:
            app.logger.error(f"Salesperson with ID {salesperson_id} not found.")
            salesperson_name = 'Unknown Salesperson'
        else:
            salesperson_name = salesperson.get('name', 'Unknown Salesperson')

        # Fetch all admin users
        admins = list(users_collection.find({'user_type': 'admin'}))
        admin_emails = [admin.get('email') for admin in admins if admin.get('email')]
        if not admin_emails:
            app.logger.error("No admin emails found to send notification.")
            return  # Or handle as appropriate

        subject = "Admin Notif: New Guest Order"

        # Render email templates
        html_body = render_template(
            'emails/admin_guest_order_notification.html',
            order=order,
            selected_services=selected_services,
            salesperson_name=salesperson_name,
            current_year=datetime.utcnow().year
        )
        text_body = render_template(
            'emails/admin_guest_order_notification.txt',
            order=order,
            selected_services=selected_services,
            salesperson_name=salesperson_name
        )

        # Send email to each admin
        for admin_email in admin_emails:
            postmark_client.emails.send(
                From=os.getenv('POSTMARK_SENDER_EMAIL'),
                To=admin_email,
                Subject=subject,
                HtmlBody=html_body,
                TextBody=text_body,
                MessageStream="outbound"
            )
            app.logger.info(f"Admin notification email sent to {admin_email}")
    except Exception as e:
        app.logger.error(f"Failed to send admin notification email: {e}")




def send_payment_collected_notifications(order, payment_method):
    """
    Sends notifications to admins, the salesperson, and the customer when a payment is collected.

    Args:
        order (dict): The order document from the database.
        payment_method (str): The method of payment ('cash' or 'card').

    Returns:
        None
    """
    try:
        # 1. Fetch Customer Information
        if order.get('is_guest', False):
            customer_email = order.get('guest_email')
            customer_phone = order.get('guest_phone_number')
            customer_name = order.get('guest_name', 'Guest')
        else:
            user = users_collection.find_one({'_id': ObjectId(order.get('user'))})
            if user:
                customer_email = user.get('email')
                customer_phone = user.get('phone_number')
                customer_name = user.get('name', 'Valued Customer')
            else:
                customer_email = None
                customer_phone = None
                customer_name = 'Valued Customer'

        # 2. Fetch Salesperson Information
        salesperson_id = order.get('salesperson')  # Stored as string
        salesperson = users_collection.find_one({'_id': ObjectId(salesperson_id)}) if salesperson_id else None
        if salesperson:
            salesperson_email = salesperson.get('email')
            salesperson_phone = salesperson.get('phone_number')
            salesperson_name = salesperson.get('name', 'Salesperson')
        else:
            salesperson_email = None
            salesperson_phone = None
            salesperson_name = 'Salesperson'

        # 3. Fetch All Admin Users
        admins = list(users_collection.find({'user_type': 'admin'}))
        admin_emails = [admin.get('email') for admin in admins if admin.get('email')]
        admin_phones = [admin.get('phone_number') for admin in admins if admin.get('phone_number')]

        # 4. Prepare Notification Messages
        customer_subject = "Payment Confirmation - CFAC"
        salesperson_subject = "Payment Collected - CFAC"
        admin_subject = "Payment Collected - CFAC"

        # 5. Send Notifications to Customer
        if customer_email:
            html_body = render_template(
                'emails/customer_payment_confirmation.html',
                order=order,
                payment_method=payment_method,
                customer_name=customer_name
            )
            text_body = render_template(
                'emails/customer_payment_confirmation.txt',
                order=order,
                payment_method=payment_method,
                customer_name=customer_name
            )
            send_generic_email(
                recipient_email=customer_email,
                subject=customer_subject,
                html_body=html_body,
                text_body=text_body
            )

        # 6. Send Notifications to Salesperson
        if salesperson_email:
            html_body = render_template(
                'emails/salesperson_payment_collected.html',
                order=order,
                payment_method=payment_method,
                salesperson_name=salesperson_name
            )
            text_body = render_template(
                'emails/salesperson_payment_collected.txt',
                order=order,
                payment_method=payment_method,
                salesperson_name=salesperson_name
            )
            send_generic_email(
                recipient_email=salesperson_email,
                subject=salesperson_subject,
                html_body=html_body,
                text_body=text_body
            )

        # 7. Send Notifications to Admins
        for admin_email in admin_emails:
            html_body = render_template(
                'emails/admin_payment_collected.html',
                order=order,
                payment_method=payment_method,
                salesperson_name=salesperson_name
            )
            text_body = render_template(
                'emails/admin_payment_collected.txt',
                order=order,
                payment_method=payment_method,
                salesperson_name=salesperson_name
            )
            send_generic_email(
                recipient_email=admin_email,
                subject=admin_subject,
                html_body=html_body,
                text_body=text_body
            )

        # 8. Send SMS Notifications (If Applicable)
        # Assuming you want to continue using AWS SNS for SMS
        # Ensure phone numbers are in E.164 format
        if customer_phone:
            customer_message = f"Dear {customer_name}, your payment for Order {order.get('_id')} has been successfully received via {payment_method.capitalize()}."
            send_sms(customer_phone, customer_message)

        if salesperson_phone:
            salesperson_message = f"Dear {salesperson_name}, you have successfully collected a payment for Order {order.get('_id')} via {payment_method.capitalize()}."
            send_sms(salesperson_phone, salesperson_message)

        for admin_phone in admin_phones:
            admin_message = f"A payment for Order {order.get('_id')} has been collected via {payment_method.capitalize()} by Salesperson {salesperson_name}."
            send_sms(admin_phone, admin_message)

    except Exception as e:
        app.logger.error(f"Error sending payment collected notifications: {e}", exc_info=True)



















def send_payment_links(order_id):
    try:
        # Fetch the order from the database
        orders_collection = current_app.config.get('ORDERS_COLLECTION')
        order = orders_collection.find_one({"_id": ObjectId(order_id)})

        if not order:
            return {"error": "Order not found"}, 404

        # Retrieve the downpayment and remaining balance checkout URLs from the order
        downpayment_checkout_url = order.get("downpayment_checkout_url")
        remaining_balance_checkout_url = order.get("remaining_balance_checkout_url")

        if not downpayment_checkout_url or not remaining_balance_checkout_url:
            return {"error": "Payment links are not yet generated"}, 400

        # Prepare email content (HTML and Text)
        html_body = render_template(
            'emails/payment_links_email.html',  # Path to the HTML template
            customer_name=order.get("guest_name", "Customer"),
            order_id=order_id,
            downpayment_checkout_url=downpayment_checkout_url,
            remaining_balance_checkout_url=remaining_balance_checkout_url,
            current_year=datetime.utcnow().year
        )

        text_body = f"""
        Dear {order.get("guest_name", "Customer")},

        Thank you for your order! Below are the payment links for your order #{order_id}:

        1. Down Payment: {downpayment_checkout_url}
        2. Remaining Balance: {remaining_balance_checkout_url}

        If you have any questions or need assistance, feel free to reach out to our support team.

        Thank you for choosing us!
        """

        # Send email with payment links
        send_postmark_email(
            subject="Your Payment Links for Order",
            to_email=order["guest_email"],
            from_email=current_app.config.get("POSTMARK_SENDER_EMAIL"),
            text_body=text_body,
            html_body=html_body
        )

        return {"message": "Payment links sent successfully!"}, 200

    except Exception as e:
        current_app.logger.error(f"Error sending payment links: {e}", exc_info=True)
        return {"error": str(e)}, 500


