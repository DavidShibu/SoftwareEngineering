from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
import requests, json
import re
from supabase import create_client, Client
import os
from decorators import login_required
from datetime import datetime, timedelta
from twilio.rest import Client as TwilioClient # <--- NEW

admin_features_bp = Blueprint('admin_features_bp', __name__)

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

TWILIO_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')

# --- 1. PERMITS & CERTIFICATES ---
@admin_features_bp.route('/admin/certificates')
@login_required(role='admin')
def admin_certificates():
    try:
        response = supabase.table('certificates').select('*, users:employee_id(full_name, employee_category)').order('uploaded_at', desc=True).execute()
        certificates = response.data if response.data else []
        return render_template('admin_certificates.html', certificates=certificates)
    except Exception as e:
        flash(f"Error fetching certificates: {e}", "error")
        return render_template('admin_certificates.html', certificates=[])

@admin_features_bp.route('/admin/verify_certificate/<cert_id>', methods=['POST'])
@login_required(role='admin')
def verify_certificate(cert_id):
    try:
        action = request.form.get('action')
        status = 'Verified' if action == 'verify' else 'Rejected'
        supabase.table('certificates').update({
            'status': status,
            'verified_by_id': session.get('user_id')
        }).eq('id', cert_id).execute()
        flash(f"Certificate {status}.", "success")
    except Exception as e:
        flash(f"Error updating certificate: {e}", "error")
    return redirect(url_for('admin_features_bp.admin_certificates'))


# --- 2. INCIDENTS (View & Assign) ---
@admin_features_bp.route('/admin/incidents')
@login_required(role='admin')
def admin_incidents():
    try:
        inc_res = supabase.table('accidents').select('*, users:reported_by_id(full_name)').order('accident_time', desc=True).execute()
        incidents = inc_res.data if inc_res.data else []
        emp_res = supabase.table('users').select('id, full_name, employee_category').eq('role', 'employee').eq('is_active', True).execute()
        employees = emp_res.data if emp_res.data else []
        return render_template('admin_incidents.html', incidents=incidents, employees=employees)
    except Exception as e:
        flash(f"Error loading incidents: {e}", "error")
        return render_template('admin_incidents.html', incidents=[], employees=[])

@admin_features_bp.route('/admin/assign_incident/<incident_id>', methods=['POST'])
@login_required(role='admin')
def assign_incident(incident_id):
    try:
        # 1. Get both the Name AND the ID from the form
        employee_name = request.form.get('employee_name_hidden')
        employee_id = request.form.get('employee_id') # <--- MAKE SURE YOUR FORM SENDS THIS
        
        current_narrative = request.form.get('current_narrative') or ""
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # 2. Create the narrative update
        updated_narrative = f"{current_narrative}\n\n[ASSIGNED]: Case assigned to {employee_name} on {timestamp}."
        
        # 3. Update status, narrative, AND the foreign key ID
        supabase.table('accidents').update({
            'narrative': updated_narrative,
            'status': 'Assigned',
            'assigned_to_id': employee_id  # <--- THIS LINKS THE USER
        }).eq('id', incident_id).execute()
        
        flash(f"Incident successfully assigned to {employee_name}.", "success")
    except Exception as e:
        flash(f"Error assigning incident: {e}", "error")
    
    return redirect(url_for('admin_features_bp.admin_incidents'))

# --- 3. COMPLAINTS (Replaces Maintenance) ---
@admin_features_bp.route('/admin/complaints')
@login_required(role='any')
def admin_complaints():
    try:
        # Fetch complaints with Passenger details
        res = supabase.table('complaints').select('*, users:passenger_id(full_name, email), attachments(file_url)').order('submitted_at', desc=True).execute()
        complaints = res.data if res.data else []
        return render_template('admin_complaints.html', complaints=complaints)
    except Exception as e:
        flash(f"Error loading complaints: {e}", "error")
        return render_template('admin_complaints.html', complaints=[])

# Inside admin_features.py

@admin_features_bp.route('/admin/reply_complaint/<complaint_id>', methods=['POST'])
@login_required(role='admin')
def reply_complaint(complaint_id):
    try:
        reply_text = request.form.get('reply_text')
        
        # 1. Update Database (Same as before)
        update_data = {
            'admin_reply': reply_text,
            'reply_at': datetime.now().isoformat(),
            'resolved_by_id': session.get('user_id'),
            'status': 'Resolved'
        }
        supabase.table('complaints').update(update_data).eq('id', complaint_id).execute()
        
        # 2. Twilio SMS Logic
        try:
            passenger_data = supabase.table('complaints') \
                .select('subject, users:passenger_id(phone, full_name)') \
                .eq('id', complaint_id) \
                .single() \
                .execute()
            
            if passenger_data.data and passenger_data.data.get('users'):
                p_phone = str(passenger_data.data['users']['phone']).strip() # Ensure string and strip spaces
                p_name = passenger_data.data['users']['full_name']
                complaint_subject = passenger_data.data['subject']

                # --- FIX START: Add Country Code if missing ---
                # If the number does not start with '+', add '+91'
                if p_phone and not p_phone.startswith('+'):
                    p_phone = f"+91{p_phone}"
                # --- FIX END ---

                if p_phone and TWILIO_SID and TWILIO_AUTH_TOKEN:
                    client = TwilioClient(TWILIO_SID, TWILIO_AUTH_TOKEN)
                    
                    sms_body = (
                        f"Hello {p_name}, your complaint regarding '{complaint_subject}' "
                        f"has been resolved. Check portal for details. - WAVELINK"
                    )

                    message = client.messages.create(
                        body=sms_body,
                        from_=TWILIO_PHONE_NUMBER,
                        to=p_phone 
                    )
                    print(f"SMS sent successfully: {message.sid}")
                    flash("Reply sent and SMS notification sent!", "success")
                else:
                    flash("Reply saved, but SMS skipped (No phone number found).", "warning")
            
        except Exception as sms_error:
            print(f"Failed to send SMS: {sms_error}")
            flash(f"Reply saved, but SMS failed: {sms_error}", "warning")

    except Exception as e:
        flash(f"Error sending reply: {e}", "error")
        
    return redirect(url_for('admin_features_bp.admin_complaints'))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

@admin_features_bp.route('/admin/ai_recommendations', methods=['POST'])
@login_required(role='admin')
def ai_recommendations():
    data = request.get_json()
    location = data.get("location", "").strip()
    if not location:
        return jsonify({"error": "Location is required."}), 400

    prompt = f"""
You are a planning expert for Water Metro terminals.

Analyze the location below as a potential site for a Water Metro terminal:

Location: "{location}"

Your job:
- Briefly describe the place in 1-2 sentences (mention local features, transport, geography, population, and any factors relevant to Water Metro operation).
- Clearly state whether the location is suitable for a terminal.
- Give a specific, fact-based reason for suitability or unsuitability (minimum 1 sentence).
- Summarize with a direct recommendation ("Suitable for Water Metro terminal." or "Not suitable for Water Metro terminal.")

Return EXACTLY this JSON object, with NO missing, extra, or blank fields, and NO outside explanation:

{{
  "location": "string",                // Repeat the input location
  "description": "string",             // Brief summary of locality with relevant features
  "suitability": "High" | "Medium" | "Low", // Overall suitability. Choose only one.
  "reasoning": "string",               // Specific reasoning supporting the suitability rating
  "finalRecommendation": "Suitable for Water Metro terminal." | "Not suitable for Water Metro terminal." // Choose only one
}}

STRICT RULES:
- VALID JSON ONLY (NO markdown, NO backticks, NO extra text—output MUST start with '{{' and end with '}}')
- All 5 fields must be filled with plausible, location-specific, well-structured content.
- If uncertain, use best professional judgment based on typical locality features (water access, demand, safety, etc).
"""


    url = "https://generativelanguage.googleapis.com/v1/models/gemini-2.0-flash-lite:generateContent"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.5, "maxOutputTokens": 512}
    }
    response = requests.post(f"{url}?key={GEMINI_API_KEY}", json=payload, headers=headers)
    if response.status_code != 200:
        return jsonify({"error": response.text}), 500

    gemini_text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    try:
        clean = gemini_text.strip()
        # Remove `````` (markdown) wrappers
        clean = re.sub(r"``````", "", clean, flags=re.IGNORECASE).strip()

        # Try to extract first {...} json block if the model hallucinated
        first_curly = clean.find("{")
        last_curly = clean.rfind("}")
        if first_curly != -1 and last_curly != -1:
            clean = clean[first_curly:last_curly+1]

        result = json.loads(clean)
        return jsonify(result) 
    except Exception as e:
        return jsonify({
            "error": f"AI returned invalid JSON: {str(e)}",
            "raw_result": gemini_text
            })


# --- 4. FEEDBACK (Updated Logic) ---
@admin_features_bp.route('/admin/feedbacks')
@login_required(role='any')
def admin_feedbacks():
    try:
        res = supabase.table('feedbacks').select('*, users:passenger_id(full_name, email), attachments(file_url)').order('submitted_at', desc=True).execute()
        feedbacks = res.data if res.data else []
        return render_template('admin_feedbacks.html', feedbacks=feedbacks)
    except Exception as e:
        flash(f"Error loading feedback: {e}", "error")
        return render_template('admin_feedbacks.html', feedbacks=[])

@admin_features_bp.route('/admin/reply_feedback/<feedback_id>', methods=['POST'])
@login_required(role='admin')
def reply_feedback(feedback_id):
    try:
        reply_text = request.form.get('reply_text')
        
        # Prepare update data
        update_data = {
            'admin_reply': reply_text,
            'reply_at': datetime.now().isoformat(),
            'replied_by_id': session.get('user_id')
        }
        
        # Update specific columns
        supabase.table('feedbacks').update(update_data).eq('id', feedback_id).execute()
        
        flash("Reply added to feedback.", "success")
    except Exception as e:
        flash(f"Error replying to feedback: {e}", "error")
    return redirect(url_for('admin_features_bp.admin_feedbacks'))

# Add these imports at the top if missing
from werkzeug.utils import secure_filename

@admin_features_bp.route('/admin/upload_certificate', methods=['GET', 'POST'])
@login_required(role='admin')
def admin_upload_certificate():
    # 1. GET: Fetch employees to populate the dropdown
    if request.method == 'GET':
        try:
            employees_res = supabase.table('users').select('id, full_name, employee_category').eq('role', 'employee').execute()
            employees = employees_res.data if employees_res.data else []
            return render_template('admin_upload_certificate.html', employees=employees)
        except Exception as e:
            flash(f"Error loading employees: {e}", "error")
            return render_template('admin_upload_certificate.html', employees=[])

    # 2. POST: Handle File Upload
    try:
        file = request.files.get('certificate_file')
        cert_name = request.form.get('cert_name')
        expiry_date = request.form.get('expiry_date')
        employee_id = request.form.get('employee_id')
        cert_type = request.form.get('cert_type')  # <--- 1. GET THE TYPE

        if not file or not cert_name or not employee_id or not cert_type:
            flash("Please provide all required fields.", "error")
            return redirect(url_for('admin_features_bp.admin_upload_certificate'))

        # Upload to Supabase Storage
        filename = secure_filename(file.filename)
        file_path = f"{employee_id}/{int(datetime.now().timestamp())}_{filename}"
        content_type = file.mimetype

        supabase.storage.from_('pdfs').upload(file_path, file.read(), {"content-type": content_type})
        public_url = supabase.storage.from_('pdfs').get_public_url(file_path)

        # --- FIXED DATA DICTIONARY ---
        data = {
            "employee_id": employee_id,
            "certificate_name": cert_name,
            "file_name": filename,
            "file_url": public_url,
            "expiry_date": expiry_date if expiry_date else None,
            "status": "Verified",
            "verified_by_id": session.get('user_id'),
            
            "type": cert_type  # <--- 2. SAVE THE SELECTED TYPE
        }
        
        supabase.table('certificates').insert(data).execute()

        flash("Certificate uploaded and verified successfully!", "success")
        return redirect(url_for('admin_features_bp.admin_certificates'))

    except Exception as e:
        print(f"UPLOAD ERROR: {str(e)}")
        flash(f"Upload failed: {str(e)}", "error")
        return redirect(url_for('admin_features_bp.admin_upload_certificate'))

    except Exception as e:
        # Print the error to your terminal so you can see details if it fails again
        print(f"UPLOAD ERROR: {str(e)}")
        flash(f"Upload failed: {str(e)}", "error")
        return redirect(url_for('admin_features_bp.admin_upload_certificate'))

from twilio.rest import Client as TwilioClient

# --- NEW ROUTE: SEND ANNOUNCEMENTS ---
@admin_features_bp.route('/admin/send_announcement', methods=['POST'])
@login_required(role='admin')
def send_announcement():
    try:
        # 1. Get Form Data
        selected_routes = request.form.getlist('route_ids') # List of IDs
        selected_times = request.form.getlist('time_slots') # List of time strings "08:00", etc.
        message_text = request.form.get('message')

        if not selected_routes or not selected_times or not message_text:
            flash("Please select at least one route, one time slot, and enter a message.", "error")
            return redirect(url_for('admin_dashboard'))

        # 2. Query Passenger Preferences to find matches
        # matching_prefs will contain: passenger_id, route_id, preferred_time
        # We use the 'in' filter for both columns
        route_res = supabase.table('routes').select('id, name').in_('id', selected_routes).execute()
        route_names = [r['name'] for r in route_res.data] if route_res.data else []
        announcement_data = {
            'message': message_text,
            'affected_routes': ", ".join(route_names), # e.g., "Vytilla, Fort Kochi"
            'affected_times': ", ".join(selected_times) # e.g., "08:00, 09:30"
        }
        supabase.table('announcements').insert(announcement_data).execute()
        # Note: Supabase-py "in_" filter requires a list
        response = supabase.table('passenger_preferences') \
            .select('passenger_id, users:passenger_id(phone, full_name)') \
            .in_('route_id', selected_routes) \
            .in_('preferred_time', selected_times) \
            .execute()
            
        matches = response.data if response.data else []
        
        # 3. Deduplicate Users (A user might match multiple times)
        unique_users = {}
        for match in matches:
            user = match.get('users')
            if user and user.get('phone'):
                unique_users[match['passenger_id']] = user

        # 4. Send SMS via Twilio
        client = TwilioClient(TWILIO_SID, TWILIO_AUTH_TOKEN)
        sent_count = 0
        
        for pid, user_data in unique_users.items():
            phone = user_data.get('phone')
            name = user_data.get('full_name')
            
            # Format phone number
            if phone and not str(phone).startswith('+'):
                phone = f"+91{phone}"
            
            try:
                sms_body = f"📢 WAVELINK ALERT: Hello {name}, {message_text}"
                client.messages.create(
                    body=sms_body,
                    from_=TWILIO_PHONE_NUMBER,
                    to=phone
                )
                sent_count += 1
            except Exception as sms_err:
                print(f"Failed to send to {phone}: {sms_err}")

        flash(f"Announcement sent successfully to {sent_count} affected passengers.", "success")
        flash(f"Announcement published to Landing Page.", "success")

    except Exception as e:
        flash(f"Error sending announcement: {e}", "error")
    
    return redirect(url_for('admin_dashboard'))

# --- Make sure these imports are present ---
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
import requests
import json
import re
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv # Import this to load the .env file
from decorators import login_required

# Load environment variables
load_dotenv()

# Ensure these imports are at the top of your file
import requests
import json
import re
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

@admin_features_bp.route('/admin/ai_chat', methods=['POST'])
@login_required(role='admin')
def ai_chat():
    user_input = request.json.get('message', '').strip()
    if not user_input:
        return jsonify({"text": "Please say something.", "data": []})

    print(f"\n--- 🤖 AI Chat Request: '{user_input}' ---")

    cmd_data = {}
    
    # 1. DETECT COMMAND (Direct, AI, or Keyword)
    # Check RAW command first
    if user_input.upper().startswith("FETCH_"):
        cmd_data["command"] = user_input.upper()
        if "EXPIRING" in user_input.upper(): cmd_data["parameters"] = {"days": 30}
    else:
        # Try Gemini
        GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
        ai_success = False
        
        if GEMINI_API_KEY:
            # STRICTER PROMPT to force specific keys
            system_prompt = f"""
            Classify user intent into JSON with keys: "command" and "parameters".
            
            1. FETCH_EXPIRING_CERTIFICATES (Params: "days": int)
            2. FETCH_PENDING_CERTIFICATES
            3. FETCH_CRITICAL_INCIDENTS
            
            User: "{user_input}"
            """
            
            url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite-preview-02-05:generateContent"
            headers = {"Content-Type": "application/json"}
            payload = {"contents": [{"parts": [{"text": system_prompt}]}]}

            try:
                response = requests.post(f"{url}?key={GEMINI_API_KEY}", json=payload, headers=headers)
                if response.status_code == 200:
                    text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
                    clean = re.sub(r"```json|```", "", text, flags=re.IGNORECASE).strip()
                    start = clean.find("{")
                    end = clean.rfind("}")
                    if start != -1:
                        cmd_data = json.loads(clean[start:end+1])
                        ai_success = True
                        print(f"-> AI Raw Response: {cmd_data}")
            except Exception as e:
                print(f"-> AI Failed: {e}")

        # Fallback Keywords
        if not ai_success:
            print("-> Using Keyword Fallback")
            txt = user_input.lower()
            if any(x in txt for x in ["pending", "wait", "approval"]):
                cmd_data = {"command": "FETCH_PENDING_CERTIFICATES"}
            elif any(x in txt for x in ["expire", "valid", "renew"]):
                cmd_data = {"command": "FETCH_EXPIRING_CERTIFICATES", "parameters": {"days": 30}}
            elif any(x in txt for x in ["critical", "accident", "severe"]):
                cmd_data = {"command": "FETCH_CRITICAL_INCIDENTS"}

    # 2. NORMALIZE DATA (The Fix for your Error)
    # The AI might send 'action' or 'command'. We accept both.
    command = cmd_data.get('command') or cmd_data.get('action')
    
    # The AI might send 'parameters' or 'params'. We accept both.
    params = cmd_data.get('parameters') or cmd_data.get('params') or {}

    print(f"-> Executing Command: {command}") # Debug print

    results = []
    bot_text = "I didn't understand. Try 'pending certificates' or 'critical accidents'."

    try:
        if command == "FETCH_EXPIRING_CERTIFICATES":
            # Handle case where days is None
            raw_days = params.get('days')
            days = int(raw_days) if raw_days else 30
            
            target_date = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
            
            res = supabase.table('certificates')\
                .select('certificate_name, expiry_date, file_url')\
                .lte('expiry_date', target_date)\
                .neq('status', 'Rejected')\
                .execute()
            results = res.data
            bot_text = f"Found {len(results)} certificates expiring soon."

        elif command == "FETCH_PENDING_CERTIFICATES":
            res = supabase.table('certificates')\
                .select('certificate_name, uploaded_at, file_url')\
                .ilike('status', '%pending%')\
                .execute()
            results = res.data
            bot_text = f"Found {len(results)} pending approvals."

        elif command == "FETCH_CRITICAL_INCIDENTS":
            res = supabase.table('accidents')\
                .select('subject, narrative, file_url, accident_time')\
                .or_('severity.ilike.high,severity.ilike.High')\
                .execute()
            results = res.data
            bot_text = f"Found {len(results)} critical/major incidents."

    except Exception as db_err:
        print(f"❌ DB Error: {db_err}")
        bot_text = "I tried to check the database but faced a technical issue."

    return jsonify({"text": bot_text, "data": results})
import collections
@admin_features_bp.route("/admin/terminals")
def admin_terminals():
    # Fetch all terminals
    terms_resp = supabase.table("terminals").select("id,name,pontoons,pontoons_active").execute()
    terminals = terms_resp.data
    # Fetch all users to count employees per terminal
    users_resp = supabase.table("users").select("id,terminal_id,role").eq("role","employee").eq("is_active",True).execute()
    users = users_resp.data if users_resp.data else []
    # Count employees per terminal
    emp_counter = collections.Counter([u['terminal_id'] for u in users if u['terminal_id']])
    # Create cards
    cards = []
    for t in terminals:
        terminal_id = t['id']
        name = t['name']
        image = url_for('static', filename=f'images/{name.lower().replace(" ", "")}.png') # image file should match terminal name
        employees = emp_counter.get(terminal_id, 0)
        pontoons_active = t.get('pontoons_active', 0)
        pontoons_inactive = (t.get('pontoons', 0) - pontoons_active)
        cards.append({
            "id": terminal_id,
            "name": name,
            "image": image,
            "employees": employees,
            "pontoons_active": pontoons_active,
            "pontoons_inactive": pontoons_inactive
        })
    return render_template("admin_terminals.html", terminals=cards)
@admin_features_bp.route("/admin/reports")
def admin_reports():
    # Employees per terminal
    users_resp = supabase.table("users").select("id,terminal_id,role").eq("role","employee").eq("is_active",True).execute()
    users = users_resp.data
    emp_counter = collections.Counter([u['terminal_id'] for u in users if u['terminal_id']])
    terminals_resp = supabase.table("terminals").select("id,name,pontoons,pontoons_active").execute()
    terminals = terminals_resp.data
    id_to_name = {t['id']: t['name'] for t in terminals}
    employee_per_terminal = {id_to_name.get(tid,tid): count for tid, count in emp_counter.items()}
    for term in terminals:
        employee_per_terminal.setdefault(term['name'], 0)
    # Incidents per terminal
    acc_resp = supabase.table("accidents").select("id,terminal_id,accident_time").execute()
    accidents = acc_resp.data
    inc_counter = collections.Counter([id_to_name.get(a['terminal_id'],a['terminal_id']) for a in accidents if a['terminal_id']])
    incidents_per_terminal = {id_to_name.get(tid,tid): inc_counter.get(id_to_name.get(tid,tid), 0) for tid in id_to_name}
    # Incident trend by month
    monthly_counter = collections.Counter()
    for a in accidents:
        if a.get('accident_time'):
            month = str(a['accident_time'])[:7]
            monthly_counter[month] += 1
    incidents_monthly = dict(sorted(monthly_counter.items()))
    # Pontoons pie
    pontoons_active = sum(t['pontoons_active'] or 0 for t in terminals)
    pontoons_inactive = sum((t['pontoons'] or 0)-(t['pontoons_active'] or 0) for t in terminals)
    chart_data = dict(
        employee_per_terminal=employee_per_terminal,
        incidents_per_terminal=incidents_per_terminal,
        pontoons_active=pontoons_active,
        pontoons_inactive=pontoons_inactive,
        incidents_monthly=incidents_monthly
    )
    return render_template("admin_reports.html", chart_data=chart_data)