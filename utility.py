# utility.py

import os
import re
from postmarker.core import PostmarkClient
from flask import current_app
import logging
import traceback

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)  # Set desired logging level

# Create console handler and set level to info
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)

# Create formatter and add it to the handler
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)

# Add handler to the logger if not already present
if not logger.handlers:
    logger.addHandler(ch)

# Initialize PostmarkClient once to reuse it across function calls
POSTMARK_SERVER_TOKEN = os.getenv('POSTMARK_SERVER_TOKEN')

if not POSTMARK_SERVER_TOKEN:
    logger.error("POSTMARK_SERVER_TOKEN environment variable not set.")
    raise EnvironmentError("POSTMARK_SERVER_TOKEN environment variable not set.")

postmark_client = PostmarkClient(server_token=POSTMARK_SERVER_TOKEN)

# Email validation regex
EMAIL_REGEX = re.compile(r"[^@]+@[^@]+\.[^@]+")

def is_valid_email(email):
    """Validate the email format."""
    return EMAIL_REGEX.match(email) is not None

def send_postmark_email(subject, to_email, from_email, text_body=None, html_body=None):
    """
    Sends an email using Postmark.

    Args:
        subject (str): Subject of the email.
        to_email (str): Recipient's email address.
        from_email (str): Sender's email address (must be verified in Postmark).
        text_body (str, optional): Plain-text version of the email.
        html_body (str, optional): HTML version of the email.

    Returns:
        dict: Response from Postmark API.
    """
    if not text_body and not html_body:
        logger.error("Both text_body and html_body are missing.")
        raise ValueError("At least one of text_body or html_body must be provided.")
    
    if not is_valid_email(to_email):
        logger.error(f"Invalid recipient email address: {to_email}")
        raise ValueError(f"Invalid recipient email address: {to_email}")
    
    if not is_valid_email(from_email):
        logger.error(f"Invalid sender email address: {from_email}")
        raise ValueError(f"Invalid sender email address: {from_email}")

    try:
        email_payload = {
            "From": from_email,
            "To": to_email,
            "Subject": subject,
            "MessageStream": "outbound"  # Adjust if you have multiple message streams
        }
        if text_body:
            email_payload["TextBody"] = text_body
        if html_body:
            email_payload["HtmlBody"] = html_body

        response = postmark_client.emails.send(**email_payload)
        logger.info(f"Email sent to {to_email} with subject '{subject}'.")
        return response
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        logger.error(traceback.format_exc())
        raise e  # Re-raise the exception to allow the calling function to handle it

def format_us_phone_number(phone_number):
    """
    Formats a US phone number to E.164 format.
    Assumes phone_number contains exactly 10 digits.
    
    Args:
        phone_number (str): The phone number to format.
    
    Returns:
        str: The formatted phone number in E.164 format.
    
    Raises:
        ValueError: If phone_number is not exactly 10 digits.
    """
    digits = re.sub(r'\D', '', phone_number)  # Remove non-digit characters
    if len(digits) != 10:
        logger.error(f"Invalid US phone number: {phone_number}")
        raise ValueError("US phone number must contain exactly 10 digits.")
    return f"+1{digits}"
