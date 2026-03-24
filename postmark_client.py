# postmark_client.py
import os
from postmarker.core import PostmarkClient

# Initialize the Postmark client using the server token from your environment variables.
postmark_client = PostmarkClient(server_token=os.getenv("POSTMARK_SERVER_TOKEN"))

# Optionally, add a helper function to validate emails if you haven’t done so already.
import re
def is_valid_email(email):
    regex = r'^\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    return re.match(regex, email) is not None
