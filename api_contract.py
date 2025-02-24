from flask import Blueprint, request, jsonify, current_app
from datetime import datetime

# Create a blueprint for contract-related endpoints
contract_bp = Blueprint('contract', __name__, url_prefix='/api/contract')

@contract_bp.route('/save', methods=['POST'])
def save_contract():
    """
    Endpoint to save contract data received from the iOS app.
    Expects a JSON payload with keys such as:
      - user_name (string)
      - email (string)
      - registration_date (ISO formatted string; optional, defaults to current time)
      - signature_data (string; e.g., base64 encoded image data; optional)
      - accepted_terms (boolean; must be True)
      - contract_version (string; optional)
    """

    print("====== [save_contract] Endpoint called ======")

    # 1. Get JSON data
    data = request.get_json()
    print(f"[save_contract] Raw JSON payload: {data}")

    # 2. Validate required fields
    user_name = data.get("user_name")
    email = data.get("email")
    accepted_terms = data.get("accepted_terms")
    print(f"[save_contract] user_name: {user_name}")
    print(f"[save_contract] email: {email}")
    print(f"[save_contract] accepted_terms: {accepted_terms}")

    if not user_name or not email:
        print("[save_contract] Missing user_name or email -> 400")
        return jsonify({"error": "user_name and email are required"}), 400
    
    if accepted_terms is not True:
        print("[save_contract] accepted_terms is not True -> 400")
        return jsonify({"error": "Contract must be accepted"}), 400

    # 3. Determine registration_date
    registration_date = data.get("registration_date", datetime.utcnow().isoformat())
    print(f"[save_contract] registration_date: {registration_date}")

    # 4. Build the contract document
    contract_data = {
        "user_name": user_name,
        "email": email,
        "registration_date": registration_date,
        "signature_data": data.get("signature_data", ""),  # Optional
        "accepted_terms": accepted_terms,
        "contract_version": data.get("contract_version", "v1.0"),
        "saved_at": datetime.utcnow()
    }
    print(f"[save_contract] Contract data to insert: {contract_data}")

    # 5. Get the MongoDB instance from the app configuration
    db = current_app.config["MONGO_CLIENT"]
    contract_collection = db.contract
    print("[save_contract] Connected to MongoDB, 'contract' collection acquired.")

    # 6. Insert the contract document
    try:
        result = contract_collection.insert_one(contract_data)
        print(f"[save_contract] Inserted contract document. _id={result.inserted_id}")
    except Exception as e:
        print(f"[save_contract] Exception when inserting to MongoDB: {e}")
        return jsonify({"error": f"Failed to save contract: {str(e)}"}), 500

    # 7. Return success response
    print("[save_contract] Contract saved successfully. Returning 200.")
    return jsonify({
        "message": "Contract saved successfully.",
        "contract_id": str(result.inserted_id)
    }), 200


@contract_bp.route('/find', methods=['GET'])
def find_contract():
    """
    Endpoint to find a contract by email.
    Example request: GET /api/contract/find?email=john@example.com
    """
    # Get the email from query parameters
    email = request.args.get('email')
    if not email:
        return jsonify({"error": "Email parameter is required."}), 400

    # Access the MongoDB instance from the app's configuration
    db = current_app.config["MONGO_CLIENT"]
    contract_collection = db.contract

    # Query the contract collection for the provided email
    contract = contract_collection.find_one({"email": email})
    if not contract:
        return jsonify({"error": "Contract not found."}), 404

    # Convert the ObjectId to a string for JSON serialization
    contract['_id'] = str(contract['_id'])

    return jsonify(contract), 200



from flask import Blueprint, request, jsonify, current_app, send_file
from datetime import datetime
import os

# Assume this helper is defined (or import it if it’s in another module)
def generate_contract_pdf(user_name, email, registration_date, signature_data):
    """
    Generate a PDF file for the contract and save it locally.
    Returns the file path of the saved PDF.
    """
    pdf_dir = "contract_pdfs"
    if not os.path.exists(pdf_dir):
        os.makedirs(pdf_dir)
    
    # Create a unique filename using the email (customize as needed)
    pdf_filename = f"{pdf_dir}/{email}_contract.pdf"
    
    # Create the PDF using ReportLab
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
    c = canvas.Canvas(pdf_filename, pagesize=letter)
    c.setFont("Helvetica", 12)
    
    # Write basic contract details into the PDF
    c.drawString(100, 750, "INDEPENDENT CONTRACTOR AGREEMENT")
    c.drawString(100, 730, f"Contractor Name: {user_name}")
    c.drawString(100, 710, f"Email: {email}")
    c.drawString(100, 690, f"Registration Date: {registration_date}")
    
    # Optionally include signature data or a reference to it
    if signature_data:
        c.drawString(100, 670, f"Signature Data: {signature_data[:30]}...")  # Show first 30 chars
    else:
        c.drawString(100, 670, "No signature provided.")
    
    c.save()
    return pdf_filename

# Create a blueprint for contract-related endpoints.
contract_bp = Blueprint('contract', __name__, url_prefix='/api/contract')

@contract_bp.route('/generate_pdf', methods=['GET'])
def generate_contract_pdf_endpoint():
    """
    Generates (or regenerates) the PDF for a saved contract.
    Expects a query parameter 'email'. Example:
       GET /api/contract/generate_pdf?email=john@example.com
    """
    email = request.args.get('email')
    if not email:
        return jsonify({"error": "Email parameter is required."}), 400

    # Retrieve the contract document from MongoDB using the shared database instance.
    db = current_app.config["MONGO_CLIENT"]
    contract_collection = db.contract
    contract = contract_collection.find_one({"email": email})
    
    if not contract:
        return jsonify({"error": "Contract not found for the provided email."}), 404

    # Extract contract data (customize keys if needed)
    user_name = contract.get("user_name")
    registration_date = contract.get("registration_date", datetime.utcnow().isoformat())
    signature_data = contract.get("signature_data", "")
    
    # Generate (or regenerate) the PDF contract using the helper function.
    pdf_path = generate_contract_pdf(user_name, email, registration_date, signature_data)
    
    # Optionally update the contract document with the new PDF path.
    contract_collection.update_one(
        {"email": email},
        {"$set": {"pdf_path": pdf_path, "pdf_generated_at": datetime.utcnow()}}
    )
    
    # Return the PDF file as an attachment.
    if not os.path.exists(pdf_path):
        return jsonify({"error": "PDF file generation failed."}), 500

    return send_file(pdf_path, as_attachment=True)

@contract_bp.route('/pdf/<email>', methods=['GET'])
def get_contract_pdf(email):
    """
    Endpoint to fetch and download the contract PDF for the given email.
    Example: GET /api/contract/pdf/john@example.com
    """
    if not email:
        return jsonify({"error": "Email parameter is required."}), 400

    # Access the MongoDB instance stored in the app's config.
    db = current_app.config["MONGO_CLIENT"]
    contract_collection = db.contract

    # Find the contract by email.
    contract = contract_collection.find_one({"email": email})
    if not contract:
        return jsonify({"error": "Contract not found."}), 404

    # Get the saved PDF file path from the contract document.
    pdf_path = contract.get("pdf_path")
    if not pdf_path or not os.path.exists(pdf_path):
        return jsonify({"error": "Contract PDF file not found."}), 404

    # Return the PDF file as a downloadable attachment.
    return send_file(pdf_path, as_attachment=True)




import os
import base64
import io
from PIL import Image  # Make sure to install Pillow: pip install Pillow

# Ensure your contract blueprint is defined once
contract_bp = Blueprint('contract', __name__, url_prefix='/api/contract')

