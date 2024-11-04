def format_us_phone_number(phone_number):
    """
    Formats a US phone number to E.164 format.
    Assumes phone_number contains exactly 10 digits.
    """
    return f"+1{phone_number}"
