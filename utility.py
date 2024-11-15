
# utility.py

import os
from postmarker.core import PostmarkClient
from flask import current_app

def send_postmark_email(subject, text_body, html_body, to_email, from_email):
    client = PostmarkClient(server_token=os.getenv('POSTMARK_SERVER_TOKEN'))
    response = client.emails.send(
        From=from_email,
        To=to_email,
        Subject=subject,
        TextBody=text_body,
        HtmlBody=html_body
    )
    return response

def format_us_phone_number(phone_number):
    """
    Formats a US phone number to E.164 format.
    Assumes phone_number contains exactly 10 digits.
    """
    return f"+1{phone_number}"