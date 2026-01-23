
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField, HiddenField, SelectMultipleField, DateField, RadioField, BooleanField, DecimalField, TimeField, ValidationError
from wtforms.validators import DataRequired, Email, EqualTo, Length, Regexp, Optional, NumberRange
from wtforms.widgets import ListWidget, CheckboxInput
from utility import format_us_phone_number
import phonenumbers




def validate_us_phone(form, field):
    """
    Custom validator to ensure phone numbers are 10 digits.
    """
    phone = field.data
    if phone:
        # Remove any non-digit characters
        digits = ''.join(filter(str.isdigit, phone))
        if len(digits) != 10:
            raise ValidationError('Phone number must contain exactly 10 digits.')
        # Optionally, you can store the digits without formatting or with formatting as needed
        field.data = digits  # Store as digits for backend processing


class RegistrationForm(FlaskForm):
    name = StringField('Full Name', validators=[DataRequired(), Length(min=2, max=100)])
    
    # Remove registration_method if it's no longer needed
    # registration_method = RadioField('Register With', choices=[('email', 'Email'), ('phone', 'Phone'), ('both', 'Both')], default='email')
    
    email = StringField('Email Address', validators=[DataRequired(), Email(), Length(max=120)])
    phone_number = StringField('Phone Number', validators=[
        Optional(),
        Regexp(r'^\d{10}$', message="Enter a valid 10-digit US phone number.")
    ])
    sms_opt_in = BooleanField('Opt-in for SMS Notifications')
    
    street_address = StringField('Street Address', validators=[DataRequired(), Length(max=200)])
    unit_apt = StringField('Unit/Apt (Optional)', validators=[Optional(), Length(max=50)])
    city = StringField('City', validators=[DataRequired(), Length(max=100)])
    country = StringField('Country', validators=[DataRequired(), Length(max=100)])
    zip_code = StringField('Zip Code', validators=[DataRequired(), Length(min=5, max=10)])
    
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    
    submit = SubmitField('Register')





class RemoveFromCartForm(FlaskForm):
    service_id = HiddenField('Service ID')  # Add this field
    submit = SubmitField('Remove')



class CustomerLoginForm(FlaskForm):
    login_method = RadioField(
        'Login With:',
        choices=[('email', 'Email'), ('phone', 'Phone Number')],
        default='email',
        validators=[DataRequired(message="Please select a login method.")]
    )
    email = StringField(
        'Email Address', 
        validators=[Optional(), Email(message="Invalid email address.")]
    )
    phone_number = StringField(
        'Phone Number', 
        validators=[Optional()]
    )
    password = PasswordField(
        'Password', 
        validators=[DataRequired(message="Password is required.")]
    )
    submit = SubmitField('Login')

    def validate(self, *args, **kwargs):
        """
        Custom validation to ensure that based on the login method, the appropriate fields are provided,
        and to validate the phone number if provided.
        """
        # Call the base class's validate method first
        rv = super(CustomerLoginForm, self).validate(*args, **kwargs)
        if not rv:
            return False

        # Retrieve the selected login method
        login_method = self.login_method.data

        # Validate based on login method
        if login_method == 'email':
            if not self.email.data:
                self.email.errors.append('Email is required for email login.')
                return False
        elif login_method == 'phone':
            if not self.phone_number.data:
                self.phone_number.errors.append('Phone number is required for phone login.')
                return False

        # If phone_number is provided, validate its format
        if self.phone_number.data:
            try:
                # Parse the phone number with 'US' as the default region
                input_number = phonenumbers.parse(self.phone_number.data, 'US')
                if not phonenumbers.is_valid_number(input_number):
                    self.phone_number.errors.append('Invalid phone number.')
                    return False
                # Format the phone number to E.164 and update the field
                self.phone_number.data = phonenumbers.format_number(
                    input_number, 
                    phonenumbers.PhoneNumberFormat.E164
                )
            except phonenumbers.NumberParseException:
                self.phone_number.errors.append('Invalid phone number format.')
                return False

        return True


class EmployeeLoginForm(FlaskForm):
    username = StringField('Username', validators=[
        DataRequired(message="Username is required.")
    ])
    password = PasswordField('Password', validators=[
        DataRequired(message="Password is required.")
    ])
    submit = SubmitField('Login')







class UpdateAccountForm(FlaskForm):
    name = StringField('Full Name', validators=[DataRequired(message="Full name is required.")])
    email = StringField('Email Address', validators=[Optional(), Email(message="Invalid email address.")])
    phone_number = StringField('Phone Number', validators=[DataRequired(message="Phone number is required.")])
    street_address = StringField('Street Address', validators=[DataRequired(message="Street address is required.")])
    city = StringField('City', validators=[DataRequired(message="City is required.")])
    country = StringField('Country', validators=[DataRequired(message="Country is required.")])
    zip_code = StringField('Zip Code', validators=[DataRequired(message="Zip code is required.")])
    submit = SubmitField('Update')
    
    def validate_email(self, field):
        if field.data:
            # Ensure email is not already taken by another user
            from app import users_collection  # Import here to avoid circular imports
            existing_user = users_collection.find_one({'email': field.data.lower()})
            if existing_user and str(existing_user['_id']) != str(current_user.id):
                raise ValidationError('This email is already registered with another account.')
    
    def validate_phone_number(self, field):
        phone_number = field.data.strip()
        try:
            input_number = phonenumbers.parse(phone_number, 'US')
            if not phonenumbers.is_valid_number(input_number):
                raise ValidationError('Invalid phone number.')
            # Format to E.164
            field.data = phonenumbers.format_number(input_number, phonenumbers.PhoneNumberFormat.E164)
        except phonenumbers.NumberParseException:
            raise ValidationError('Invalid phone number format.')


class DeleteUserForm(FlaskForm):
    submit = SubmitField('Delete')

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
    guest_phone_number = StringField(
        'Phone Number',
        validators=[
            Optional(),
            Regexp(
                regex=r'^\+?1?\d{10}$',
                message='Phone number must be a 10-digit US number, optionally prefixed with +1.'
            ),
            validate_us_phone
        ]
    )
    
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
        # Add more countries as needed
    ], validators=[DataRequired(message="Country is required.")], coerce=str)
    zip_code = StringField('Zip Code', validators=[
        DataRequired(message="Zip Code is required."),
        Regexp(r'^\d{5}(-\d{4})?$', message="Zip code must be in the format 12345 or 12345-6789."),
        Length(max=20, message="Zip Code must be less than 20 characters.")
    ])
    
    # Order Information
    service_date = DateField('Service Date', validators=[
        DataRequired(message="Service Date is required.")
    ], format='%Y-%m-%d')

     #  Time Field
    service_time = TimeField('Service Time', format='%H:%M', validators=[
        DataRequired()]) 

    senior_rv_discount = BooleanField(
        'Senior & RV Discount',
        default=False,
        validators=[Optional()]
    )
    vehicle_size = SelectField(
        'Vehicle Size',
        choices=[
            ('', '-- Select Vehicle Size --'),
            ('coupe_2', 'Coupe 2 Seater'),
            ('hatch_2_door', 'Hatchback 2 Door'),
            ('hatch_4_door', 'Hatchback 4 Door'),
            ('truck_2_seater', 'Truck 2 Seater'),
            ('truck_4_seater', 'Truck 4 Seater'),
            ('sedan_2_door', 'Sedan 2 Door'),
            ('sedan_4_door', 'Sedan 4 Door'),
            ('suv_4_seater', 'SUV 4 Seater'),
            ('suv_6_seater', 'SUV 6 Seater'),
            ('minivan_6_seater', 'Minivan 6 Seater'),
        ],
        validators=[DataRequired()] 
    )
    
    service_package = StringField('Service Package', validators=[Optional()])

    payment_time = RadioField(
        'Payment Time',
        choices=[
            ('pay_now', 'Pay now (full)'),
            ('pay_after_completion', 'Pay deposit now')
        ],
        default='pay_now',
        validators=[DataRequired(message="Please select a payment option.")]
    )
    service_ids  = HiddenField()
    vehicle_size = HiddenField()
    appointment  = HiddenField()

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


class PasswordResetRequestForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Request Password Reset')

class PasswordResetForm(FlaskForm):
    password = PasswordField('New Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm New Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Reset Password')




class EditOrderForm(FlaskForm):
    status = SelectField(
        'Status',
        choices=[
            ('Ordered', 'Ordered'),
            ('Scheduled', 'Scheduled'),
            ('Completed', 'Completed'),
            ('Cancelled', 'Cancelled')
        ],
        validators=[DataRequired()]
    )
    
    payment_method = SelectField(
        'Payment Method',
        choices=[
            ('Cash', 'Cash'),
            ('Card', 'Card'),
            ('Zelle', 'Zelle')
        ],
        validators=[DataRequired()]
    )
    
    total_amount = DecimalField(
        'Total Amount',
        validators=[
            DataRequired(),
            NumberRange(min=0, message="Total amount must be positive.")
        ]
    )
    
    service_date = DateField(
        'Schedule Date',
        format='%Y-%m-%d',
        validators=[DataRequired()]
    )
    
    submit = SubmitField('Save Changes')



class DeleteOrderForm(FlaskForm):
    submit = SubmitField('Delete')


class SalesProfileForm(FlaskForm):
    full_name = StringField('Full Name', validators=[DataRequired(), Length(min=2, max=50)])
    email = StringField('Email Address', validators=[DataRequired(), Email()])
    phone_number = StringField('Phone Number', validators=[DataRequired(), Length(min=10, max=15)])
    # Add other fields as needed

    submit = SubmitField('Update Profile')



class CollectPaymentForm(FlaskForm):
    payment_method = RadioField('Payment Method', choices=[
        ('cash', 'Cash'),
        ('card', 'Manual Card Payment')
    ], default='cash', validators=[DataRequired()])

    submit = SubmitField('Submit Payment')
    
class UpdateCompensationStatusForm(FlaskForm):
    order_id = HiddenField(validators=[DataRequired()])
    employee_type = HiddenField(validators=[DataRequired()])
    new_status = HiddenField(validators=[DataRequired()])
    submit = SubmitField('Update Status')






class AddUserForm(FlaskForm):
    full_name = StringField("Full Name", validators=[DataRequired()])
    username = StringField("Username", validators=[DataRequired()])
    email = StringField("Email", validators=[Optional(), Email()])
    phone = StringField("Phone", validators=[Optional()])
    user_type = SelectField(
        "User Type",
        choices=[("customer", "Customer"), ("sales", "Sales"), ("tech", "Tech"), ("admin", "Admin")],
        validators=[DataRequired()]
    )
    submit = SubmitField("Add User")

    # Custom validation: must provide either email OR phone
    def validate(self, extra_validators=None):
        if not super().validate(extra_validators):
            return False
        if not self.email.data and not self.phone.data:
            msg = "You must provide either an email or a phone number."
            self.email.errors.append(msg)
            self.phone.errors.append(msg)
            return False
        return True





class AddCustomerForm(FlaskForm):
    full_name = StringField("Full Name", validators=[DataRequired()])
    email = StringField("Email", validators=[DataRequired(), Email()])
    phone = StringField("Phone", validators=[Optional()])

    # Address fields
    street_address = StringField("Street Address", validators=[Optional()])
    city = StringField("City", validators=[Optional()])
    zip_code = StringField("Zip Code", validators=[Optional()])
    country = StringField("Country", validators=[Optional()])

    car_size = SelectField(
        "Vehicle Size",
        choices=[
            ("coupe_2_seater", "Coupe (2 Seater)"),
            ("hatch_2_door", "Hatchback (2 Door)"),
            ("hatch_4_door", "Hatchback (4 Door)"),
            ("sedan_2_door", "Sedan (2 Door)"),
            ("sedan_4_door", "Sedan (4 Door)"),
            ("truck_2_seater", "Truck (2 Seater)"),
            ("truck_4_seater", "Truck (4 Seater)"),
            ("suv_4_seater", "SUV (4 Seater)"),
            ("suv_6_seater", "SUV (6 Seater)"),
            ("minivan_6_seater", "Minivan (6 Seater)")
        ],
        validators=[DataRequired()]
    )

    submit = SubmitField("Add Customer")