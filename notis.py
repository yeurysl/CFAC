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
    subject = "Thank You for Your Down Payment"
    text_body = (
        f"Hello {customer_name},\n\n"
        "Thank you for submitting your down payment. Please see your invoice details below."
    )
    
    # Build invoice details
    # Assume order.get("services") returns a list of service dictionaries with 'description' and 'price'
    services = order.get("services", [])
    travel_fee = order.get("travel_fee", 0)
    final_price = order.get("final_price", 0)
    
    # Build the rows for each service
    service_rows = ""
    for service in services:
        description = service.get("description", "Service")
        price = service.get("price", 0)
        service_rows += f"""
            <tr>
                <td style="padding: 8px; border: 1px solid #dddddd;">{description}</td>
                <td style="padding: 8px; border: 1px solid #dddddd; text-align: right;">${price:.2f}</td>
            </tr>
        """
    
    # Invoice table (down payment section)
    invoice_html = f"""
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
                <tr>
                    <td style="padding: 8px; border: 1px solid #dddddd;">Travel Fee</td>
                    <td style="padding: 8px; border: 1px solid #dddddd; text-align: right;">${travel_fee:.2f}</td>
                </tr>
                <tr style="font-weight: bold;">
                    <td style="padding: 8px; border: 1px solid #dddddd;">Total Amount</td>
                    <td style="padding: 8px; border: 1px solid #dddddd; text-align: right;">${final_price:.2f}</td>
                </tr>
                <tr style="font-weight: bold;">
                    <td style="padding: 8px; border: 1px solid #dddddd;">Down Payment (40%)</td>
                    <td style="padding: 8px; border: 1px solid #dddddd; text-align: right;">${final_price * 0.40:.2f}</td>
                </tr>
            </tbody>
        </table>
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
                        {invoice_html}
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
    subject = "Your Payment is Complete"
    text_body = (
        f"Hello {customer_name},\n\n"
        "Thank you for paying the remaining balance. Your order is now fully confirmed."
    )
    
    # Build invoice details (similar to above, but now include remaining balance info)
    services = order.get("services", [])
    travel_fee = order.get("travel_fee", 0)
    final_price = order.get("final_price", 0)
    
    service_rows = ""
    for service in services:
        description = service.get("description", "Service")
        price = service.get("price", 0)
        service_rows += f"""
            <tr>
                <td style="padding: 8px; border: 1px solid #dddddd;">{description}</td>
                <td style="padding: 8px; border: 1px solid #dddddd; text-align: right;">${price:.2f}</td>
            </tr>
        """
    
    invoice_html = f"""
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
                <tr>
                    <td style="padding: 8px; border: 1px solid #dddddd;">Travel Fee</td>
                    <td style="padding: 8px; border: 1px solid #dddddd; text-align: right;">${travel_fee:.2f}</td>
                </tr>
                <tr style="font-weight: bold;">
                    <td style="padding: 8px; border: 1px solid #dddddd;">Total Amount</td>
                    <td style="padding: 8px; border: 1px solid #dddddd; text-align: right;">${final_price:.2f}</td>
                </tr>
                <tr style="font-weight: bold;">
                    <td style="padding: 8px; border: 1px solid #dddddd;">Remaining Balance (60%)</td>
                    <td style="padding: 8px; border: 1px solid #dddddd; text-align: right;">${final_price * 0.60:.2f}</td>
                </tr>
            </tbody>
        </table>
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
                        {invoice_html}
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
