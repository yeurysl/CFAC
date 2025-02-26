import os
import base64
import tempfile
from apns2.client import APNsClient
from dotenv import load_dotenv

from apns2.payload import Payload
load_dotenv()

# Retrieve APNs certificate from environment variable
CERT_B64 = os.getenv("APNS_CERT_B64_SALESMAN")

if not CERT_B64:
    raise ValueError("❌ APNS_CERT_B64_SALESMAN environment variable is missing.")

# Decode and write the certificate to a temporary file
with tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as temp_cert:
    temp_cert.write(base64.b64decode(CERT_B64))
    temp_cert_path = temp_cert.name  # Store temp file path

print(f"✅ APNs certificate saved to temporary file: {temp_cert_path}")

# APNs details
DEVICE_TOKEN = "45a6c2383e933c7576819406eb785c16efb04f0950de3f7f52df7650a7e0296d"  # The test device token
APNS_TOPIC = "com.Centralfloridaautocare.cfacios"  # Your app's APNs topic

# Create the payload
payload = Payload(alert="🚀 Test Notification!", sound="default", badge=1)

# Initialize APNs client (use_sandbox=True if testing on a development build)
client = APNsClient(temp_cert_path, use_sandbox=False, use_alternative_port=False)

# Send the notification
try:
    response = client.send_notification(DEVICE_TOKEN, payload, topic=APNS_TOPIC)
    print(f"✅ Push Notification Sent! Response: {response}")
except Exception as e:
    print(f"❌ Failed to send push notification: {e}")

# Clean up the temporary certificate file
os.remove(temp_cert_path)
print("✅ Temporary certificate file removed.")
