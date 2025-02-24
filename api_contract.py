from flask import Blueprint, request, jsonify, current_app, send_file
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from io import BytesIO
from bson import ObjectId


# Create a blueprint for contract-related endpoints
contract_bp = Blueprint('contract', __name__, url_prefix='/api/contract')





@contract_bp.route('/save', methods=['POST'])
def save_contract():
    """
    Example endpoint to:
      1) Generate a PDF with the user's details,
      2) Store the PDF binary + fields in the 'contract' collection.
    """

    current_app.logger.info("====== [save_contract] Endpoint called ======")

    # 1) Parse JSON
    try:
        data = request.get_json()
        current_app.logger.info(f"Received contract data: {data}")
    except Exception as e:
        current_app.logger.error(f"Error parsing JSON payload: {e}")
        return jsonify({"error": "Invalid JSON body"}), 400

    if not data:
        current_app.logger.error("Empty JSON request body.")
        return jsonify({"error": "Request body cannot be empty"}), 400

    # 2) Validate required fields
    user_name = data.get("user_name")
    if not user_name:
        current_app.logger.error("Missing 'user_name' field.")
        return jsonify({"error": "user_name is required"}), 400

    email = data.get("email", "no-email-provided")
    registration_date = data.get("registration_date", datetime.utcnow().isoformat())

    current_app.logger.info(f"Contract user_name: {user_name}, email: {email}, registration_date: {registration_date}")

    # 3) Generate PDF in-memory with ReportLab
    try:
        current_app.logger.info("Generating in-memory PDF with ReportLab.")
        pdf_buffer = BytesIO()
        pdf = canvas.Canvas(pdf_buffer, pagesize=letter)
        pdf.setFont("Helvetica", 12)

        # Title
        pdf.drawString(72, 750, "Independent Contractor Agreement")

        # User details
        pdf.drawString(72, 730, f"Name: {user_name}")
        pdf.drawString(72, 710, f"Email: {email}")
        pdf.drawString(72, 690, f"Registration Date: {registration_date}")

        # Body Text
        contract_text = """
        1. INDEPENDENT CONTRACTOR STATUS
        The Contractor is an independent contractor and not an employee of the Company.

        2. SCOPE OF WORK
        The Contractor agrees to provide sales and client acquisition services.

        ...
        """
        text_lines = contract_text.split("\n")
        y = 670
        for line in text_lines:
            pdf.drawString(72, y, line)
            y -= 15

        pdf.showPage()
        pdf.save()
        pdf_buffer.seek(0)

        pdf_bytes = pdf_buffer.getvalue()
        current_app.logger.info(f"Generated PDF of size {len(pdf_bytes)} bytes.")
    except Exception as e:
        current_app.logger.error(f"Error generating PDF: {e}")
        return jsonify({"error": f"PDF generation failed: {str(e)}"}), 500

    # 4) Build the Mongo document
    contract_document = {
        "user_name": user_name,
        "email": email,
        "registration_date": registration_date,
        "created_at": datetime.utcnow(),
        "pdf_data": pdf_bytes  # Binary PDF data
    }
    current_app.logger.debug(f"Contract document to be inserted: {contract_document}")

    # 5) Insert into MongoDB “contract” collection
    try:
        db = current_app.config["MONGO_CLIENT"]
        contract_collection = db.contract

        current_app.logger.info("Inserting contract document into 'contract' collection.")
        result = contract_collection.insert_one(contract_document)
        contract_id = str(result.inserted_id)
        current_app.logger.info(f"PDF contract inserted with _id={contract_id}")
    except Exception as e:
        current_app.logger.error(f"Exception while inserting into MongoDB: {e}")
        return jsonify({"error": f"Failed to save contract: {str(e)}"}), 500

    # 6) Return success response
    current_app.logger.info("Contract and PDF stored successfully. Returning 201.")
    return jsonify({
        "message": "Contract and PDF stored successfully!",
        "contract_id": contract_id
    }), 201


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
def generate_contract_pdf(user_name, email, registration_date):
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
    
    
    c.save()
    return pdf_filename


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
    
    # Generate (or regenerate) the PDF contract using the helper function.
    pdf_path = generate_contract_pdf(user_name, email, registration_date)
    
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
    current_app.logger.info("===== [get_contract_pdf] Endpoint called =====")

    # 1) Check the 'email' parameter
    if not email:
        current_app.logger.error("[get_contract_pdf] Missing 'email' parameter -> 400")
        return jsonify({"error": "Email parameter is required."}), 400
    
    current_app.logger.info(f"[get_contract_pdf] Requested email: {email}")

    # 2) Access the MongoDB instance stored in the app's config.
    try:
        db = current_app.config["MONGO_CLIENT"]
        contract_collection = db.contract
        current_app.logger.info("[get_contract_pdf] Connected to 'contract' collection.")
    except Exception as e:
        current_app.logger.error(f"[get_contract_pdf] Error accessing MongoDB: {e}")
        return jsonify({"error": "Database connection error"}), 500

    # 3) Find the contract by email.
    try:
        contract = contract_collection.find_one({"email": email})
        if contract:
            current_app.logger.info(f"[get_contract_pdf] Found contract document: {contract}")
        else:
            current_app.logger.error(f"[get_contract_pdf] No contract found for email: {email} -> 404")
            return jsonify({"error": "Contract not found."}), 404
    except Exception as e:
        current_app.logger.error(f"[get_contract_pdf] Exception while fetching contract: {e}")
        return jsonify({"error": f"Error fetching contract: {str(e)}"}), 500

    # 4) Check for the saved PDF file path in the contract document.
    pdf_path = contract.get("pdf_path")
    if not pdf_path:
        current_app.logger.error("[get_contract_pdf] 'pdf_path' not found in contract document -> 404")
        return jsonify({"error": "Contract PDF file not found."}), 404
    
    current_app.logger.info(f"[get_contract_pdf] pdf_path from contract: {pdf_path}")

    # 5) Confirm the file actually exists on disk.
    if not os.path.exists(pdf_path):
        current_app.logger.error(f"[get_contract_pdf] File does not exist at path: {pdf_path} -> 404")
        return jsonify({"error": "Contract PDF file not found."}), 404

    # 6) Return the PDF file as a downloadable attachment.
    current_app.logger.info(f"[get_contract_pdf] Returning PDF file: {pdf_path}")
    return send_file(pdf_path, as_attachment=True)
