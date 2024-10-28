import boto3
from botocore.exceptions import ClientError
import os
from dotenv import load_dotenv

load_dotenv()


# Initialize SNS client
sns_client = boto3.client(
    'sns',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_DEFAULT_REGION')
)

def send_test_sms(phone_number, message):
    try:
        response = sns_client.publish(
            PhoneNumber=phone_number,
            Message=message
        )
        print(f"SMS sent successfully. Message ID: {response.get('MessageId')}")
    except ClientError as e:
        print(f"Failed to send SMS: {e}")

if __name__ == "__main__":
    test_phone_number = '+18138609587'  # Replace with your phone number in E.164 format
    test_message = "This is a test SMS from AWS SNS."
    send_test_sms(test_phone_number, test_message)
