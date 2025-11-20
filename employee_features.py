from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from supabase import create_client, Client
from datetime import datetime
import uuid
import os
import fitz  # PyMuPDF for PDF metadata extraction
import re

# Import the shared decorator
from decorators import login_required

employee_bp = Blueprint('employee_bp', __name__)

# Re-create the Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- PDF EXTRACTION HELPER FUNCTIONS ---
ISO_DATE_REGEX = r"(\d{4}-\d{1,2}-\d{1,2})" 
DATE_FORMAT = '%Y-%m-%d'

def get_expiry_date_from_pdf_metadata(pdf_file_path):
    try:
        doc = fitz.open(pdf_file_path)
        metadata = doc.metadata
        doc.close()

        # Search Author, Creator, and Producer
        metadata_search_string = f"{metadata.get('author', '')} {metadata.get('creator', '')} {metadata.get('producer', '')}"
        
        if metadata_search_string:
            match = re.search(ISO_DATE_REGEX, metadata_search_string)
            if match:
                extracted_date_str = match.group(1)
                try:
                    datetime.strptime(extracted_date_str, DATE_FORMAT)
                    return extracted_date_str
                except ValueError:
                    return None
        return None
    except Exception as e:
        print(f"Error extracting date from PDF metadata: {e}")
        return None

# --- JINJA TEMPLATE FILTER ---
def format_datetime(value, format='%Y-%m-%d %H:%M'):
    if not value: return "N/A"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return value
    return value.strftime(format)

employee_bp.app_template_filter('datetime_format')(format_datetime)

# ---------------------------------------------------------------------------------------------------
## Employee Dashboard
# ---------------------------------------------------------------------------------------------------

@employee_bp.route('/dashboard')
@login_required(role='employee')
def employee_dashboard():
    user_id = session.get('user_id')
    category = session.get('employee_category')
    
    tasks = []
    try:
        # Fetch incidents assigned to this user that are NOT Closed
        # We join 'users' to get the reporter's name if needed
        response = supabase.table('accidents') \
            .select('*, users:reported_by_id(full_name)') \
            .eq('assigned_to_id', user_id) \
            .neq('status', 'Closed') \
            .order('accident_time', desc=True) \
            .execute()
            
        tasks = response.data if response.data else []
        
    except Exception as e:
        flash(f"Error loading tasks: {e}", "error")

    return render_template('er.html', category=category, tasks=tasks)

# ---------------------------------------------------------------------------------------------------
## Certificate Management
# ---------------------------------------------------------------------------------------------------

@employee_bp.route('/upload_certificate', methods=['GET', 'POST'])
@login_required(role='employee')
def upload_certificate():
    # 1. AJAX Analysis
    if request.method == 'POST' and 'file_for_analysis' in request.files:
        file = request.files['file_for_analysis']
        if file.filename:
            temp_dir = 'temp_uploads'
            if not os.path.exists(temp_dir): os.makedirs(temp_dir)
            
            temp_path = os.path.join(temp_dir, file.filename)
            file.save(temp_path)
            
            base_name = os.path.basename(file.filename)
            initial_name = os.path.splitext(base_name)[0] 
            initial_expiry_date = get_expiry_date_from_pdf_metadata(temp_path)
            
            try: os.remove(temp_path)
            except: pass
            
            return jsonify({'certificate_name': initial_name, 'expiry_date': initial_expiry_date or ''})

    # 2. Final Submission
    if request.method == 'POST':
        try:
            user_id = session.get('user_id')
            certificate_name = request.form.get('certificate_name')
            certificate_type = request.form.get('certificate_type') 
            expiry_date_str = request.form.get('expiry_date')
            files = request.files.getlist('attachments')

            if not certificate_name or not certificate_type or not files:
                flash("Certificate name, type, and file are required.", "error")
                return redirect(url_for('employee_bp.upload_certificate'))

            expiry_date = None
            if expiry_date_str:
                expiry_date = datetime.fromisoformat(expiry_date_str).isoformat()

            file = files[0]
            file_url = None
            
            if file and file.filename:
                file_ext = os.path.splitext(file.filename)[1]
                # CHANGED: Removed user_id subfolder. Saving to root of bucket.
                storage_file_name = f"cert_{uuid.uuid4()}{file_ext}"
                
                file.seek(0)
                supabase.storage.from_('pdfs').upload(storage_file_name, file.read(), {"content-type": "application/pdf"})
                
                res_url = supabase.storage.from_('pdfs').get_public_url(storage_file_name)
                file_url = res_url if isinstance(res_url, str) else res_url.public_url

            if not file_url:
                flash("File upload failed.", "error")
                return redirect(url_for('employee_bp.upload_certificate'))

            cert_entry = {
                "employee_id": user_id,
                "certificate_name": certificate_name,
                "type": certificate_type,
                "expiry_date": expiry_date,
                "file_name": file.filename,
                "file_url": file_url,
                "uploaded_at": datetime.now().isoformat(),
                "status": "pending"
            }
            
            supabase.table('certificates').insert(cert_entry).execute()

            flash("Certificate submitted for verification!", "success")
            return redirect(url_for('employee_bp.my_certificates'))

        except Exception as e:
            print(e)
            flash(f"Error uploading certificate: {str(e)}", "error")

    return render_template('upload_certificate.html')


@employee_bp.route('/my_certificates')
@login_required(role='employee')
def my_certificates():
    certificates = []
    try:
        user_id = session.get('user_id')
        response = supabase.table('certificates')\
            .select('*')\
            .eq('employee_id', user_id)\
            .order('uploaded_at', desc=True)\
            .execute()
        
        if response.data:
            certificates = response.data
    except Exception as e:
        flash(f"Error loading certificate history: {e}", "error")

    return render_template('my_certificates.html', certificates=certificates)

# ---------------------------------------------------------------------------------------------------
## Accidents / Incidents
# ---------------------------------------------------------------------------------------------------

@employee_bp.route('/report_incident', methods=['GET', 'POST'])
@login_required(role='employee')
def report_incident():
    if request.method == 'POST':
        try:
            user_id = session.get('user_id')
            
            # 1. Get New Form Data
            subject = request.form.get('subject')
            narrative = request.form.get('description')
            accident_time = request.form.get('accident_time') # Now coming from form
            severity = request.form.get('severity')
            involved_party = request.form.get('involved_party')
            
            files = request.files.getlist('attachments')

            if not narrative or not subject or not accident_time:
                flash("Subject, Description, and Time are required.", "error")
                return redirect(url_for('employee_bp.report_incident'))

            # 2. Handle File Upload (Single file per your schema image)
            file_name = None
            file_url = None
            
            if files and files[0].filename:
                file = files[0]
                file_ext = os.path.splitext(file.filename)[1]
                storage_name = f"accident_{uuid.uuid4()}{file_ext}"
                
                # Upload
                file.seek(0)
                supabase.storage.from_('pdfs').upload(storage_name, file.read(), {"content-type": file.mimetype})
                
                # Generate Signed URL
                res = supabase.storage.from_('pdfs').create_signed_url(storage_name, 31536000) # 1 Year expiry
                
                # Extract URL
                if isinstance(res, dict) and 'signedURL' in res: file_url = res['signedURL']
                elif isinstance(res, str): file_url = res
                elif hasattr(res, 'signedURL'): file_url = res.signedURL
                
                file_name = file.filename

            # 3. Insert into Database (Matches your Schema Image)
            accident_entry = {
                "reported_by_id": user_id,
                "terminal_id": "2e728c0f-ae27-4830-b5f7-139bfd0784ab", # Ensure this is a valid UUID in your DB
                "subject": subject,
                "narrative": narrative,
                "accident_time": datetime.fromisoformat(accident_time).isoformat(),
                "severity": severity,
                "involved_party": involved_party,
                "status": "investigation",
                "file_name": file_name, # New column from your image
                "file_url": file_url,   # New column from your image
                "uploaded_at": datetime.now().isoformat()
            }
            
            supabase.table('accidents').insert(accident_entry).execute()

            flash("Incident reported successfully!", "success")
            return redirect(url_for('employee_bp.my_incidents'))

        except Exception as e:
            print(e)
            flash(f"Error submitting report: {e}", "error")
    
    return render_template('report_incident.html')


@employee_bp.route('/my_incidents')
@login_required(role='employee')
def my_incidents():
    incidents = []
    try:
        user_id = session.get('user_id')
        response = supabase.table('accidents').select('*') \
            .eq('reported_by_id', user_id).order('accident_time', desc=True).execute()
        if response.data: incidents = response.data
    except Exception as e:
        flash(f"Error loading incident history: {e}", "error")

    return render_template('my_incidents.html', incidents=incidents)

# ---------------------------------------------------------------------------------------------------
## Repairs
# ---------------------------------------------------------------------------------------------------

@employee_bp.route('/upload_repair', methods=['POST'])
@login_required(role='employee')
def upload_repair():
    try:
        user_id = session.get('user_id')
        terminal_id = session.get('terminal_id') 
        subject = request.form.get('subject') 
        description = request.form.get('description')
        files = request.files.getlist('attachments')
        
        if not subject or not description:
            flash("Repair title and description are required.", "error")
            return redirect(url_for('employee_bp.employee_dashboard'))

        file_urls_text = ""
        if files:
            for file in files:
                if file.filename:
                    file_ext = os.path.splitext(file.filename)[1]
                    # CHANGED: Removed user_id subfolder.
                    file_name = f"repair_{uuid.uuid4()}{file_ext}"
                    file.seek(0)
                    supabase.storage.from_('pdfs').upload(file_name, file.read())
                    res_url = supabase.storage.from_('pdfs').get_public_url(file_name)
                    url = res_url if isinstance(res_url, str) else res_url.public_url
                    file_urls_text += f"\n\n[Attached File: {url}]"

        final_description = description + file_urls_text

        repair_entry = {
            "reported_by_id": user_id,
            "terminal_id": terminal_id, 
            "subject": subject,
            "description": final_description,
            "status": "pending",        
            "priority": "medium",
            "reported_at": datetime.now().isoformat()
        }
        
        supabase.table('repairs').insert(repair_entry).execute()

        flash("Repair report submitted successfully!", "success")
        return redirect(url_for('employee_bp.employee_dashboard'))

    except Exception as e:
        flash(f"Error submitting repair report: {e}", "error")
        return redirect(url_for('employee_bp.employee_dashboard'))