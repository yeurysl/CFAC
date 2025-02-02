import jwt

token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI2NzFmMGM5OWMxZmU5YjA2OWYzYzUwZWUiLCJpYXQiOjE3Mzg0OTM3NjEsImV4cCI6MTczODUwODE2MX0.ynVA41T7ymUhf_mwHlA_7sH5CPzPlR6qWBfQ9h5yAvs"
secret = "JWT_SECRET" # Make sure this matches the secret used when the token was signed

try:
    # Decode the token. This will also verify the signature.
    payload = jwt.decode(token, secret, algorithms=['HS256'])
    print("Decoded payload:", payload)
except jwt.ExpiredSignatureError:
    print("Token has expired.")
except jwt.InvalidTokenError as e:
    print("Invalid token:", e)
