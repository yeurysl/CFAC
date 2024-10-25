
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField, HiddenField, SelectMultipleField, DateField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Regexp, Optional




class RegistrationForm(FlaskForm):
    name = StringField('Full Name', validators=[
        DataRequired(message="Full Name is required."),
        Length(min=2, max=100, message="Full Name must be between 2 and 100 characters.")
    ])
    email = StringField('Email Address', validators=[
        DataRequired(message="Email Address is required."),
        Email(message="Invalid email address.")
    ])
    phone_number = StringField('Phone Number', validators=[
        Optional(),
        Regexp(r'^\+?1?\d{9,15}$', message="Phone number must be entered in the format: '+999999999'. Up to 15 digits allowed.")
    ])
    street_address = StringField('Street Address', validators=[
        DataRequired(message="Street Address is required."),
        Length(min=5, max=200, message="Street Address must be between 5 and 200 characters.")
    ])
    city = StringField('City', validators=[
        DataRequired(message="City is required."),
        Length(min=2, max=100, message="City must be between 2 and 100 characters.")
    ])
    country = SelectField('Country', choices=[
        ('', 'Select your country'),
        ('United States', 'United States'),
      
    ], validators=[DataRequired(message="Country is required.")])
    zip_code = StringField('Zip Code', validators=[
        DataRequired(message="Zip Code is required."),
        Regexp(r'^\d{5}(-\d{4})?$', message="Zip code must be in the format 12345 or 12345-6789.")
    ])
    password = PasswordField('Password', validators=[
        DataRequired(message="Password is required."),
        Length(min=6, message="Password must be at least 6 characters long.")
    ])
    confirm_password = PasswordField('Confirm Password', validators=[
        DataRequired(message="Please confirm your password."),
        EqualTo('password', message="Passwords must match.")
    ])
    unit_apt = StringField('Unit/Apt', validators=[
        Optional(),
        Length(max=20, message="Unit/Apt must be less than 20 characters.")
    ])
    submit = SubmitField('Register')



class RemoveFromCartForm(FlaskForm):
    product_id = HiddenField('Product ID', validators=[DataRequired()])
    submit = SubmitField('Remove')



class CustomerLoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email(message="Invalid email.")])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')



class EmployeeLoginForm(FlaskForm):
    username = StringField('Username', validators=[
        DataRequired(message="Username is required.")
    ])
    password = PasswordField('Password', validators=[
        DataRequired(message="Password is required.")
    ])
    submit = SubmitField('Login')



class UpdateAccountForm(FlaskForm):
    name = StringField('Full Name', validators=[
        DataRequired(message="Full Name is required."),
        Length(min=2, max=100, message="Full Name must be between 2 and 100 characters.")
    ])
    phone_number = StringField('Phone Number', validators=[
        DataRequired(message="Phone Number is required."),
        Regexp(r'^\+?1?\d{9,15}$', message="Invalid phone number format.")
    ])
    street_address = StringField('Street Address', validators=[
        DataRequired(message="Street Address is required."),
        Length(min=5, max=200, message="Street Address must be between 5 and 200 characters.")
    ])
    city = StringField('City', validators=[
        DataRequired(message="City is required."),
        Length(min=2, max=100, message="City must be between 2 and 100 characters.")
    ])
    country = SelectField('Country', choices=[
        ('', 'Select your country'),
        ('United States', 'United States'),
        # Add more countries as needed
    ], validators=[DataRequired(message="Country is required.")])
    zip_code = StringField('Zip Code', validators=[
        DataRequired(message="Zip Code is required."),
        Regexp(r'^\d{5}(-\d{4})?$', message="Zip code must be in the format 12345 or 12345-6789.")
    ])
    submit = SubmitField('Update')


class GuestOrderForm(FlaskForm):
    # Guest Information
    guest_name = StringField('Guest Name', validators=[
        DataRequired(message="Guest Name is required."),
        Length(min=2, max=100, message="Guest Name must be between 2 and 100 characters.")
    ])
    guest_email = StringField('Guest Email', validators=[
        Optional(),
        Email(message="Invalid email address."),
        Length(max=100, message="Guest Email must be less than 100 characters.")
    ])
    guest_phone_number = StringField('Guest Phone Number', validators=[
        Optional(),
        Regexp(r'^\+?1?\d{9,15}$', message="Phone number must be entered in the format: '+999999999'. Up to 15 digits allowed."),
        Length(max=20, message="Guest Phone Number must be less than 20 characters.")
    ])
    
    # Guest Address
    street_address = StringField('Street Address', validators=[
        DataRequired(message="Street Address is required."),
        Length(min=5, max=200, message="Street Address must be between 5 and 200 characters.")
    ])
    unit_apt = StringField('Unit/Apt (Optional)', validators=[
        Optional(),
        Length(max=50, message="Unit/Apt must be less than 50 characters.")
    ])
    city = StringField('City', validators=[
        DataRequired(message="City is required."),
        Length(min=2, max=100, message="City must be between 2 and 100 characters.")
    ])
    country = SelectField('Country', choices=[
        ('', 'Select your country'),
        ('United States', 'United States'),
        ('Canada', 'Canada'),
        ('United Kingdom', 'United Kingdom'),
        ('Australia', 'Australia'),
        # Add more countries as needed
    ], validators=[DataRequired(message="Country is required.")])
    zip_code = StringField('Zip Code', validators=[
        DataRequired(message="Zip Code is required."),
        Regexp(r'^\d{5}(-\d{4})?$', message="Zip code must be in the format 12345 or 12345-6789."),
        Length(max=20, message="Zip Code must be less than 20 characters.")
    ])
    
    # Order Information
    service_date = DateField('Service Date', validators=[
        DataRequired(message="Service Date is required.")
    ], format='%Y-%m-%d')
    products = SelectMultipleField('Select Products', validators=[
        DataRequired(message="At least one product must be selected.")
    ], coerce=str)
    
    submit = SubmitField('Schedule Guest Order')
    
    def validate(self, *args, **kwargs):
        """Override the default validate method to add custom validation."""
        # First, run the default validators with all arguments
        if not super(GuestOrderForm, self).validate(*args, **kwargs):
            return False
        
        # Custom Validation: Ensure at least one contact method is provided
        if not self.guest_email.data and not self.guest_phone_number.data:
            error_message = 'Please provide at least an email or a phone number for the guest.'
            self.guest_email.errors.append(error_message)
            self.guest_phone_number.errors.append(error_message)
            return False
        
        return True