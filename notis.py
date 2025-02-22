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





from flask import current_app

def send_postmark_email(subject, to_email, from_email, text_body, html_body=None):
    """
    Sends an email via Postmark.
    """
    # Log the email value using repr() to show any extra whitespace/characters.
    current_app.logger.info(f"send_postmark_email called with recipient: {repr(to_email)}")
    
    # Validate email addresses.
    if not is_valid_email(to_email):
        current_app.logger.error(f"Invalid recipient email address detected: {repr(to_email)}")
        raise ValueError("Invalid recipient email address")
    if not is_valid_email(from_email):
        current_app.logger.error(f"Invalid sender email address detected: {repr(from_email)}")
        raise ValueError("Invalid sender email address")
    
    try:
        response = postmark_client.emails.send(
            From=from_email,
            To=to_email,
            Subject=subject,
            TextBody=text_body,
            HtmlBody=html_body if html_body else text_body
        )
        current_app.logger.info(f"Email sent successfully with response: {response}")
        return response
    except Exception as e:
        current_app.logger.error(f"Error sending email via Postmark: {str(e)}")
        raise


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





from datetime import datetime
from flask import current_app

def send_downpayment_thankyou_email(order):
    guest_email = order.get("guest_email")
    if not guest_email:
        current_app.logger.error("No guest email found for downpayment notification.")
        return
    customer_name = order.get("customer_name", "Customer")
    # Get the order ID as a string (if available)
    order_id = str(order.get("_id", "N/A"))
    
    subject = "Thank You for Your Down Payment"
    text_body = (
        f"Hello {customer_name},\n\n"
        "Thank you for submitting your down payment. Please see your invoice details below."
    )
    
    # Retrieve order details
    services = order.get("services", [])
    fee = float(order.get("fee", 0))  # Combined fee from the document
    travel_fee = float(order.get("travel_fee", 0))
    final_price = float(order.get("final_price", 0))
    services_total = float(order.get("services_total", 0))
    
    # Build service rows (list of individual services)
    service_rows = ""
    for service in services:
        description = service.get("description", "Service")
        price = float(service.get("price", 0))
        service_rows += f"""
            <tr>
                <td style="padding: 8px; border: 1px solid #dddddd;">{description}</td>
                <td style="padding: 8px; border: 1px solid #dddddd; text-align: right;">${price:.2f}</td>
            </tr>
        """
    
    # Build the fee row (using the fee key from the document)
    fee_row = f"""
        <tr>
            <td style="padding: 8px; border: 1px solid #dddddd;">Licensing, insurance and handling fee</td>
            <td style="padding: 8px; border: 1px solid #dddddd; text-align: right;">${fee:.2f}</td>
        </tr>
    """
    
    # Build a row for services_total
    services_total_row = f"""
        <tr style="font-weight: bold;">
            <td style="padding: 8px; border: 1px solid #dddddd;">Services Total</td>
            <td style="padding: 8px; border: 1px solid #dddddd; text-align: right;">${services_total:.2f}</td>
        </tr>
    """
    
    # Build the invoice table for services, fee, services_total, travel fee, and total amount
    invoice_table = f"""
        <h2 style="color:#07173d;">Invoice / Receipt</h2>
        <table style="width:100%; border-collapse: collapse;">
            <thead>
                <tr style="background-color: #f8f8f8;">
                    <th style="padding: 8px; border: 1px solid #dddddd; text-align: left;">Description</th>
                    <th style="padding: 8px; border: 1px solid #dddddd; text-align: right;">Price</th>
                </tr>
            </thead>
            <tbody>
                {service_rows}
                {fee_row}
                {services_total_row}
                <tr>
                    <td style="padding: 8px; border: 1px solid #dddddd;">Travel Fee</td>
                    <td style="padding: 8px; border: 1px solid #dddddd; text-align: right;">${travel_fee:.2f}</td>
                </tr>
                <tr style="font-weight: bold;">
                    <td style="padding: 8px; border: 1px solid #dddddd;">Total Amount</td>
                    <td style="padding: 8px; border: 1px solid #dddddd; text-align: right;">${final_price:.2f}</td>
                </tr>
            </tbody>
        </table>
    """
    
    # Build the separate payment breakdown section
    down_payment = final_price * 0.40
    remaining_balance = final_price * 0.60
    payment_breakdown = f"""
        <div style="margin-top: 20px; padding: 15px; background-color: #f9f9f9; border: 1px solid #dddddd;">
            <p style="margin: 0; font-weight: bold;">Payment Breakdown</p>
            <p style="margin: 5px 0;">Down Payment (Paid Today): <strong>${down_payment:.2f}</strong></p>
            <p style="margin: 5px 0;">Remaining Balance (Due after Completion): <strong>${remaining_balance:.2f}</strong></p>
        </div>
    """
    
    # Build order information section (order id and link to My Orders)
    order_info = f"""
        <p style="margin-top: 20px;">Order ID: <strong>{order_id}</strong></p>
    """
    
    html_body = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Down Payment Received</title>
        <style>
            body {{
                margin: 0;
                padding: 0;
                background-color: #f4f4f4;
                font-family: Arial, sans-serif;
            }}
            .container {{
                width: 100%;
                background-color: #f4f4f4;
                padding: 20px 0;
            }}
            .email-wrapper {{
                width: 100%;
                max-width: 600px;
                margin: 0 auto;
                background-color: #ffffff;
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 2px 3px rgba(0,0,0,0.1);
            }}
            .header {{
                background-color: #07173d;
                padding: 20px;
                text-align: center;
                color: #ffffff;
            }}
            .content {{
                padding: 20px;
                color: #333333;
            }}
            .content a {{
                display: inline-block;
                margin-top: 10px;
                color: #07173d;
                text-decoration: none;
                font-weight: bold;
            }}
            .footer {{
                background-color: #f1f1f1;
                padding: 15px;
                text-align: center;
                font-size: 12px;
                color: #666666;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
            }}
            th, td {{
                padding: 8px;
                border: 1px solid #dddddd;
            }}
            th {{
                background-color: #f8f8f8;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <table class="email-wrapper" cellpadding="0" cellspacing="0">
                <tr>
                    <td class="header">
                        <h1>Down Payment Received</h1>
                    </td>
                </tr>
                <tr>
                    <td class="content">
                        <p>Hello {customer_name},</p>
                        <p>Thank you for submitting your down payment. Your order will be completed as scheduled.</p>
                        <a href="https://cfautocare.biz/customer/login" target="_blank">Click here to view your Order</a>
                        {order_info}
                        {invoice_table}
                        {payment_breakdown}
                    </td>
                </tr>
                <tr>
                    <td class="footer">
                        &copy; {datetime.now().year} Centralfloridaautocare LLC. All rights reserved.
                    </td>
                </tr>
            </table>
        </div>
    </body>
    </html>
    """
    sender_email = current_app.config.get("POSTMARK_SENDER_EMAIL")
    send_postmark_email(subject, guest_email, sender_email, text_body, html_body)


def send_remaining_payment_thankyou_email(order):
    guest_email = order.get("guest_email")
    if not guest_email:
        current_app.logger.error("No guest email found for remaining balance notification.")
        return
    customer_name = order.get("customer_name", "Customer")
    # Get the order ID as a string
    order_id = str(order.get("_id", "N/A"))
    
    subject = "Your Payment is Complete"
    text_body = (
        f"Hello {customer_name},\n\n"
        "Thank you for paying the remaining balance. Your order is now fully confirmed."
    )
    
    services = order.get("services", [])
    fee = float(order.get("fee", 0))
    travel_fee = float(order.get("travel_fee", 0))
    final_price = float(order.get("final_price", 0))
    services_total = float(order.get("services_total", 0))
    
    service_rows = ""
    for service in services:
        description = service.get("description", "Service")
        price = float(service.get("price", 0))
        service_rows += f"""
            <tr>
                <td style="padding: 8px; border: 1px solid #dddddd;">{description}</td>
                <td style="padding: 8px; border: 1px solid #dddddd; text-align: right;">${price:.2f}</td>
            </tr>
        """
    
    fee_row = f"""
        <tr>
            <td style="padding: 8px; border: 1px solid #dddddd;">Licensing, insurance and handling fee</td>
            <td style="padding: 8px; border: 1px solid #dddddd; text-align: right;">${fee:.2f}</td>
        </tr>
    """
    
    services_total_row = f"""
        <tr style="font-weight: bold;">
            <td style="padding: 8px; border: 1px solid #dddddd;">Services Total</td>
            <td style="padding: 8px; border: 1px solid #dddddd; text-align: right;">${services_total:.2f}</td>
        </tr>
    """
    
    invoice_table = f"""
        <h2 style="color:#07173d;">Invoice / Receipt</h2>
        <table style="width:100%; border-collapse: collapse;">
            <thead>
                <tr style="background-color: #f8f8f8;">
                    <th style="padding: 8px; border: 1px solid #dddddd; text-align: left;">Description</th>
                    <th style="padding: 8px; border: 1px solid #dddddd; text-align: right;">Price</th>
                </tr>
            </thead>
            <tbody>
                {service_rows}
                {fee_row}
                {services_total_row}
                <tr>
                    <td style="padding: 8px; border: 1px solid #dddddd;">Travel Fee</td>
                    <td style="padding: 8px; border: 1px solid #dddddd; text-align: right;">${travel_fee:.2f}</td>
                </tr>
                <tr style="font-weight: bold;">
                    <td style="padding: 8px; border: 1px solid #dddddd;">Total Amount</td>
                    <td style="padding: 8px; border: 1px solid #dddddd; text-align: right;">${final_price:.2f}</td>
                </tr>
            </tbody>
        </table>
    """
    
    down_payment = final_price * 0.40
    remaining_balance = final_price * 0.60
    payment_breakdown = f"""
        <div style="margin-top: 20px; padding: 15px; background-color: #f9f9f9; border: 1px solid #dddddd;">
            <p style="margin: 0; font-weight: bold;">Payment Breakdown</p>
            <p style="margin: 5px 0;">Down Payment (Paid Today): <strong>${down_payment:.2f}</strong></p>
            <p style="margin: 5px 0;">Remaining Balance (Due after Completion): <strong>${remaining_balance:.2f}</strong></p>
        </div>
    """
    
    # Build order information section (order id and My Orders link)
    order_info = f"""
        <p style="margin-top: 20px;">Order ID: <strong>{order_id}</strong></p>
        <p><a href="https://cfautocare.biz/customer/login" target="_blank" style="color: #07173d; font-weight: bold;">View My Orders</a></p>
    """
    
    html_body = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Payment Complete</title>
        <style>
            body {{
                margin: 0;
                padding: 0;
                background-color: #f4f4f4;
                font-family: Arial, sans-serif;
            }}
            .container {{
                width: 100%;
                background-color: #f4f4f4;
                padding: 20px 0;
            }}
            .email-wrapper {{
                width: 100%;
                max-width: 600px;
                margin: 0 auto;
                background-color: #ffffff;
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 2px 3px rgba(0,0,0,0.1);
            }}
            .header {{
                background-color: #07173d;
                padding: 20px;
                text-align: center;
                color: #ffffff;
            }}
            .content {{
                padding: 20px;
                color: #333333;
            }}
            .content h2 {{
                color: #07173d;
            }}
            .footer {{
                background-color: #f1f1f1;
                padding: 15px;
                text-align: center;
                font-size: 12px;
                color: #666666;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
            }}
            th, td {{
                padding: 8px;
                border: 1px solid #dddddd;
            }}
            th {{
                background-color: #f8f8f8;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <table class="email-wrapper" cellpadding="0" cellspacing="0">
                <tr>
                    <td class="header">
                        <h1>Payment Complete</h1>
                    </td>
                </tr>
                <tr>
                    <td class="content">
                        <p>Hello {customer_name},</p>
                        <p>Thank you for paying the remaining balance. Your order is now fully confirmed.</p>
                        {order_info}
                        {invoice_table}
                        {payment_breakdown}
                    </td>
                </tr>
                <tr>
                    <td class="footer">
                        &copy; {datetime.now().year} Centralfloridaautocare LLC. All rights reserved.
                    </td>
                </tr>
            </table>
        </div>
    </body>
    </html>
    """
    sender_email = current_app.config.get("POSTMARK_SENDER_EMAIL")
    send_postmark_email(subject, guest_email, sender_email, text_body, html_body)



def notify_techs_new_order(order):
    """
    Notify all tech users that a new order is available.
    - If a tech has a registered device token, send an iOS push notification.
    - Otherwise, send a fallback email.
    """
    users_collection = current_app.config.get('USERS_COLLECTION')
    device_tokens_collection = current_app.config.get('DEVICE_TOKENS_COLLECTION')
    
    if not users_collection or not device_tokens_collection:
        current_app.logger.error("Users or Device Tokens collection not configured.")
        return

    # Query for all tech users.
    tech_cursor = users_collection.find({"user_type": "tech"})
    for tech in tech_cursor:
        tech_id = str(tech.get("_id"))
        tech_email = tech.get("email")
        token_record = device_tokens_collection.find_one({"user_id": tech_id})
        
        message = "A new order is available in your job list."
        
        if token_record and token_record.get("device_token"):
            # If the tech has a device token, send a push notification.
            device_token = token_record["device_token"]
            # Call your push notification function (adjust parameters as needed).
            push_response = send_notification_to_tech(
                tech_id=tech_id,
                order_id=str(order.get("_id")),
                threshold=None,
                device_token=device_token,
                custom_message=message
            )
            current_app.logger.info(f"Push notification sent to tech {tech_id}: {push_response}")
        else:
            # Otherwise, send a fallback email.
            subject = "New Order Available"
            text_body = (
                f"Hello {tech.get('first_name', 'Tech')},\n\n"
                "A new order is available in your job list. Please log in to review it."
            )
            html_body = f"""
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <title>New Order Available</title>
                <style>
                    body {{
                        font-family: Arial, sans-serif;
                        background-color: #f4f4f4;
                        padding: 20px;
                    }}
                    .container {{
                        background-color: #ffffff;
                        padding: 20px;
                        border-radius: 8px;
                        box-shadow: 0 2px 3px rgba(0,0,0,0.1);
                    }}
                    .header {{
                        background-color: #07173d;
                        color: #ffffff;
                        text-align: center;
                        padding: 10px 0;
                    }}
                    .content {{
                        margin-top: 20px;
                    }}
                    .footer {{
                        margin-top: 20px;
                        font-size: 12px;
                        color: #666666;
                        text-align: center;
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>New Order Available</h1>
                    </div>
                    <div class="content">
                        <p>Hello {tech.get('first_name', 'Tech')},</p>
                        <p>A new order is available in your job list. Please log in to review the order details.</p>
                    </div>
                    <div class="footer">
                        &copy; {datetime.now().year} Centralfloridaautocare LLC. All rights reserved.
                    </div>
                </div>
            </body>
            </html>
            """
            sender_email = current_app.config.get("POSTMARK_SENDER_EMAIL")
            try:
                send_postmark_email(subject, tech_email, sender_email, text_body, html_body)
                current_app.logger.info(f"Fallback email sent to tech {tech_id}")
            except Exception as e:
                current_app.logger.error(f"Failed to send fallback email to tech {tech_id}: {e}")


def notify_techs_new_order(order):
    """
    Notify all tech users that a new order is available.
    - If a tech has a registered device token, send an iOS push notification using a custom message.
    - Otherwise, send a fallback email notifying them that a new order is available.
    """
    users_collection = current_app.config.get('USERS_COLLECTION')
    device_tokens_collection = current_app.config.get('DEVICE_TOKENS_COLLECTION')
    
    if not users_collection or not device_tokens_collection:
        current_app.logger.error("Users or Device Tokens collection not configured.")
        return

    # Query for all tech users.
    tech_cursor = users_collection.find({"user_type": "tech"})
    for tech in tech_cursor:
        tech_id = str(tech.get("_id"))
        tech_email = tech.get("email")
        token_record = device_tokens_collection.find_one({"user_id": tech_id})
        
        # Custom message for new orders
        custom_push_message = "A new order has been added to your job list. Please check your app for details."
        
        if token_record and token_record.get("device_token"):
            # If the tech has a device token, send an iOS push notification.
            device_token = token_record["device_token"]
            # Call a new function to send iOS push notifications with a custom message.
            push_response = send_ios_push_notification(
                tech_id=tech_id,
                order_id=str(order.get("_id")),
                device_token=device_token,
                message=custom_push_message
            )
            current_app.logger.info(f"Push notification sent to tech {tech_id}: {push_response}")
        else:
            # Otherwise, send a fallback email.
            subject = "New Order Available"
            text_body = (
                f"Hello {tech.get('first_name', 'Tech')},\n\n"
                "A new order is available in your job list. Please log in to review it."
            )
            html_body = f"""
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <title>New Order Available</title>
                <style>
                    body {{
                        font-family: Arial, sans-serif;
                        background-color: #f4f4f4;
                        padding: 20px;
                    }}
                    .container {{
                        background-color: #ffffff;
                        padding: 20px;
                        border-radius: 8px;
                        box-shadow: 0 2px 3px rgba(0,0,0,0.1);
                    }}
                    .header {{
                        background-color: #07173d;
                        color: #ffffff;
                        text-align: center;
                        padding: 10px 0;
                    }}
                    .content {{
                        margin-top: 20px;
                    }}
                    .footer {{
                        margin-top: 20px;
                        font-size: 12px;
                        color: #666666;
                        text-align: center;
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>New Order Available</h1>
                    </div>
                    <div class="content">
                        <p>Hello {tech.get('first_name', 'Tech')},</p>
                        <p>A new order is available in your job list. Please log in to review the order details.</p>
                    </div>
                    <div class="footer">
                        &copy; {datetime.now().year} Centralfloridaautocare LLC. All rights reserved.
                    </div>
                </div>
            </body>
            </html>
            """
            sender_email = current_app.config.get("POSTMARK_SENDER_EMAIL")
            try:
                send_postmark_email(subject, tech_email, sender_email, text_body, html_body)
                current_app.logger.info(f"Fallback email sent to tech {tech_id}")
            except Exception as e:
                current_app.logger.error(f"Failed to send fallback email to tech {tech_id}: {e}")


import os
import base64
import tempfile
from apns2.client import APNsClient
from apns2.payload import Payload
from flask import current_app

def send_ios_push_notification(tech_id, order_id, device_token, message):
    """
    Sends an iOS push notification via APNs with a custom message.
    """
    # Retrieve the base64-encoded APNs certificate from environment variables.
    cert_b64 = os.environ.get("APNS_CERT_B64")
    if not cert_b64:
        current_app.logger.error("APNS certificate not configured in environment.")
        return {"error": "APNS certificate not configured"}

    try:
        # Decode and write the certificate to a temporary file.
        cert_content = base64.b64decode(cert_b64)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as temp_cert:
            temp_cert.write(cert_content)
            temp_cert_path = temp_cert.name

        # Create the payload with a title and message.
        payload = Payload(alert={"title": "New Order Available", "body": message}, sound="default", badge=1)
        
        # Create an APNs client. Adjust use_sandbox as necessary.
        client = APNsClient(temp_cert_path, use_sandbox=True, use_alternative_port=False)
        # The topic should be your app's bundle identifier.
        response = client.send_notification(device_token, payload, topic="com.Centralfloridaautocare.cfacios")

        # Clean up the temporary certificate file.
        os.remove(temp_cert_path)
        current_app.logger.info(f"Push notification response for tech {tech_id}: {response}")
        return response
    except Exception as e:
        current_app.logger.error(f"Error sending iOS push notification: {str(e)}")
        return {"error": str(e)}
