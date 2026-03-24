#test.py

import jwt
import os
from dotenv import load_dotenv
load_dotenv()
JWT_SECRET = os.getenv('JWT_SECRET', 'default-jwt-secret')


token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI2NzFmMGM5OWMxZmU5YjA2OWYzYzUwZWUiLCJpYXQiOjE3Mzg1NDg1NTIsImV4cCI6MTczODU2Mjk1Mn0.elKrx5W9hG2Tqd5EC94AP0fiMTrwbIRLyEmJSz9GgqI"
secret_key = JWT_SECRET

try:
    payload = jwt.decode(token, secret_key, algorithms=["HS256"])
    print("Decoded payload:", payload)
except Exception as e:
    print("Error decoding token:", e)
