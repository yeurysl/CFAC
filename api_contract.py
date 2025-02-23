from flask import Blueprint, request, jsonify, current_app
from datetime import datetime

# Create a blueprint for contract-related endpoints
contracts_bp = Blueprint('contracts', __name__, url_prefix='/api/contracts')

@contracts_bp.route('/save', methods=['POST'])
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
    data = request.get_json()
    
    # Validate required fields
    user_name = data.get("user_name")
    email = data.get("email")
    accepted_terms = data.get("accepted_terms")
    
    if not user_name or not email:
        return jsonify({"error": "user_name and email are required"}), 400
    
    if accepted_terms is not True:
        return jsonify({"error": "Contract must be accepted"}), 400

    # Use the current UTC time if no registration_date is provided
    registration_date = data.get("registration_date", datetime.utcnow().isoformat())

    # Build the contract document
    contract_data = {
        "user_name": user_name,
        "email": email,
        "registration_date": registration_date,
        "signature_data": data.get("signature_data", ""),  # Optional; can be a base64 string
        "accepted_terms": accepted_terms,
        "contract_version": data.get("contract_version", "v1.0"),
        "saved_at": datetime.utcnow()
    }
    
    # Get the MongoDB instance from the app configuration.
    db = current_app.config["MONGO_CLIENT"]
    # Access (or create) the "contracts" collection.
    contracts_collection = db.contracts
    
    # Insert the contract document into the collection.
    result = contracts_collection.insert_one(contract_data)
    
    return jsonify({
        "message": "Contract saved successfully.",
        "contract_id": str(result.inserted_id)
    }), 200

@contracts_bp.route('/find', methods=['GET'])
def find_contract():
    """
    Endpoint to find a contract by email.
    Example request: GET /api/contracts/find?email=john@example.com
    """
    # Get the email from query parameters
    email = request.args.get('email')
    if not email:
        return jsonify({"error": "Email parameter is required."}), 400

    # Access the MongoDB instance from the app's configuration
    db = current_app.config["MONGO_CLIENT"]
    contracts_collection = db.contracts

    # Query the contracts collection for the provided email
    contract = contracts_collection.find_one({"email": email})
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
contracts_bp = Blueprint('contracts', __name__, url_prefix='/api/contracts')

@contracts_bp.route('/generate_pdf', methods=['GET'])
def generate_contract_pdf_endpoint():
    """
    Generates (or regenerates) the PDF for a saved contract.
    Expects a query parameter 'email'. Example:
       GET /api/contracts/generate_pdf?email=john@example.com
    """
    email = request.args.get('email')
    if not email:
        return jsonify({"error": "Email parameter is required."}), 400

    # Retrieve the contract document from MongoDB using the shared database instance.
    db = current_app.config["MONGO_CLIENT"]
    contracts_collection = db.contracts
    contract = contracts_collection.find_one({"email": email})
    
    if not contract:
        return jsonify({"error": "Contract not found for the provided email."}), 404

    # Extract contract data (customize keys if needed)
    user_name = contract.get("user_name")
    registration_date = contract.get("registration_date", datetime.utcnow().isoformat())
    signature_data = contract.get("signature_data", "")
    
    # Generate (or regenerate) the PDF contract using the helper function.
    pdf_path = generate_contract_pdf(user_name, email, registration_date, signature_data)
    
    # Optionally update the contract document with the new PDF path.
    contracts_collection.update_one(
        {"email": email},
        {"$set": {"pdf_path": pdf_path, "pdf_generated_at": datetime.utcnow()}}
    )
    
    # Return the PDF file as an attachment.
    if not os.path.exists(pdf_path):
        return jsonify({"error": "PDF file generation failed."}), 500

    return send_file(pdf_path, as_attachment=True)

@contracts_bp.route('/pdf/<email>', methods=['GET'])
def get_contract_pdf(email):
    """
    Endpoint to fetch and download the contract PDF for the given email.
    Example: GET /api/contracts/pdf/john@example.com
    """
    if not email:
        return jsonify({"error": "Email parameter is required."}), 400

    # Access the MongoDB instance stored in the app's config.
    db = current_app.config["MONGO_CLIENT"]
    contracts_collection = db.contracts

    # Find the contract by email.
    contract = contracts_collection.find_one({"email": email})
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

# Ensure your contracts blueprint is defined once
contracts_bp = Blueprint('contracts', __name__, url_prefix='/api/contracts')

@contracts_bp.route('/upload_signature', methods=['POST'])
def upload_signature():
    """
    Endpoint to accept a signature from the iOS app.
    Expects a JSON payload with:
      - email (string)
      - signature_data (string; base64 encoded image data)
      
    This endpoint decodes the signature data, saves it as a PNG file,
    and updates the contract document with the signature file path.
    """
    data = request.get_json()
    email = data.get("email")
    signature_data = data.get("signature_data")

    if not email or not signature_data:
        return jsonify({"error": "Both email and signature_data are required."}), 400

    try:
        # If the signature_data contains a data URL prefix (e.g., "data:image/png;base64,"),
        # remove it.
        if signature_data.startswith("data:"):
            header, signature_data = signature_data.split(",", 1)

        # Decode the base64 string to bytes
        image_bytes = base64.b64decode(signature_data)
        image = Image.open(io.BytesIO(image_bytes))

        # Create a directory for signatures if it doesn't exist
        signature_dir = "signatures"
        if not os.path.exists(signature_dir):
            os.makedirs(signature_dir)

        # Create a unique filename for the signature image
        signature_filename = f"{email}_signature.png"
        file_path = os.path.join(signature_dir, signature_filename)

        # Save the image as a PNG file
        image.save(file_path)
    except Exception as e:
        return jsonify({"error": "Invalid signature_data", "details": str(e)}), 400

    # Update the contract document in MongoDB with the signature file path
    db = current_app.config["MONGO_CLIENT"]
    contracts_collection = db.contracts
    result = contracts_collection.update_one(
        {"email": email},
        {"$set": {"signature_file": file_path, "signature_uploaded_at": datetime.utcnow()}}
    )

    if result.modified_count == 0:
        return jsonify({"error": "Failed to update contract with signature."}), 500

    return jsonify({
        "message": "Signature uploaded successfully.",
        "signature_file": file_path
    }), 200
