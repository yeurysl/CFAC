
# utility.py

import os
from postmark import PMMail
from flask import current_app

def send_postmark_email(to_email, subject, html_body, text_body=None, sender=None):
    """
    Sends an email using Postmark's API.

    Args:
        to_email (str): Recipient's email address.
        subject (str): Subject of the email.
        html_body (str): HTML content of the email.
        text_body (str, optional): Plain-text content of the email. Defaults to None.
        sender (str, optional): Sender's email address. Defaults to None.

    Returns:
        None
    """
    try:
        email = PMMail(
            api_key=os.getenv('POSTMARK_API_TOKEN'),
            subject=subject,
            sender=sender or os.getenv('POSTMARK_SENDER_EMAIL'),
            to=to_email,
            html_body=html_body,
            text_body=text_body
        )
        email.send()
        current_app.logger.info(f"Email sent to {to_email} with subject '{subject}'.")
    except Exception as e:
        current_app.logger.error(f"Error sending email to {to_email}: {e}")


def format_us_phone_number(phone_number):
    """
    Formats a US phone number to E.164 format.
    Assumes phone_number contains exactly 10 digits.
    """
    return f"+1{phone_number}"