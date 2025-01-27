# utility.py

import os
import re
import logging
import traceback
from flask import current_app
from postmarker.core import PostmarkClient
from datetime import datetime

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(ch)

POSTMARK_SERVER_TOKEN = os.getenv('POSTMARK_SERVER_TOKEN')
if not POSTMARK_SERVER_TOKEN:
    logger.error("POSTMARK_SERVER_TOKEN environment variable not set.")
    raise EnvironmentError("POSTMARK_SERVER_TOKEN environment variable not set.")

postmark_client = PostmarkClient(server_token=POSTMARK_SERVER_TOKEN)

EMAIL_REGEX = re.compile(r"[^@]+@[^@]+\.[^@]+")

def is_valid_email(email):
    """Validate the email format."""
    return EMAIL_REGEX.match(email) is not None

def format_us_phone_number(phone_number):
    """Formats a US phone number to E.164 format (assumes 10 digits)."""
    digits = re.sub(r'\D', '', phone_number)
    if len(digits) != 10:
        logger.error(f"Invalid US phone number: {phone_number}")
        raise ValueError("US phone number must contain exactly 10 digits.")
    return f"+1{digits}"
def format_time(time_str):
    """
    Converts a time string from 'HH:MM' format to 'h:MM AM/PM' format.

    Args:
        time_str (str): Time in 'HH:MM' 24-hour format.

    Returns:
        str: Time in 'h:MM AM/PM' format.
    """
    try:
        # Parse the time string to a datetime object
        time_obj = datetime.strptime(time_str, '%H:%M')
        # Format the time to 'h:MM AM/PM', removing any leading zero
        return time_obj.strftime('%I:%M %p').lstrip('0')
    except ValueError:
        # If parsing fails, log the error and return the original string
        current_app.logger.error(f"Invalid time format for format_time filter: {time_str}")
        return time_str

def currency_format(value):
    try:
        value = float(value)
        return "${:,.2f}".format(value)  # Example formatting for USD
    except (ValueError, TypeError):
        return "N/A"  # Fallback value if conversion fails

def format_date_with_suffix(value):
    """
    Converts a datetime (or date) into 'Month DaySuffix, Year'.
    Example: datetime(2025,1,13) -> 'January 13th, 2025'
    """
    if not value:
        return ""
    if isinstance(value, str):
        # Attempt to parse if it's a string
        from dateutil.parser import parse
        value = parse(value)

    # If it's not a datetime, bail
    if not isinstance(value, (datetime,)):
        return str(value)

    day_num = value.day
    # Ordinal suffix logic
    if 10 <= day_num % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(day_num % 10, 'th')

    # Format: January 13th, 2025
    return value.strftime(f"%B {day_num}{suffix}, %Y")

def calculate_cart_total(services):
    """
    Calculate the total cost of the cart.
    """
    return sum(service.get('price', 0) for service in services)

def is_valid_phone_number(phone_number):
    """Validates if the phone number is in E.164 format."""
    pattern = re.compile(r'^\+[1-9]\d{1,14}$')
    return bool(pattern.match(phone_number))

def format_phone_number(phone_number, default_region="US"):
    """Parses and formats the phone number to E.164 format."""
    # from phonenumbers import parse, format_number, PhoneNumberFormat, NumberParseException
    # Additional logic if needed
    return None  # or the actual logic

def register_filters():
    """
    Call this function while in an app context to add custom filters to Jinja.
    E.g., in app.py:
    
    with app.app_context():
        register_filters()
    """
    current_app.jinja_env.filters['format_time'] = format_time  

    current_app.jinja_env.filters['format_date_with_suffix'] = format_date_with_suffix
    current_app.jinja_env.filters['currency'] = currency_format
