from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
import requests, json
import re
from supabase import create_client, Client
import os
from decorators import login_required
from datetime import datetime

admin_features_bp = Blueprint('admin_features_bp', __name__)

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

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
@login_required(role='admin')
def admin_complaints():
    try:
        # Fetch complaints with Passenger details
        res = supabase.table('complaints').select('*, users:passenger_id(full_name, email), attachments(file_url)').order('submitted_at', desc=True).execute()
        complaints = res.data if res.data else []
        return render_template('admin_complaints.html', complaints=complaints)
    except Exception as e:
        flash(f"Error loading complaints: {e}", "error")
        return render_template('admin_complaints.html', complaints=[])

@admin_features_bp.route('/admin/reply_complaint/<complaint_id>', methods=['POST'])
@login_required(role='admin')
def reply_complaint(complaint_id):
    try:
        reply_text = request.form.get('reply_text')
        
        # Prepare the update data
        update_data = {
            'admin_reply': reply_text,
            'reply_at': datetime.now().isoformat(), # standard ISO format for timestamptz
            'resolved_by_id': session.get('user_id'),
            'status': 'Resolved'
        }
        
        # Update the specific columns instead of appending to message
        supabase.table('complaints').update(update_data).eq('id', complaint_id).execute()
        
        flash("Reply sent successfully.", "success")
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
@login_required(role='admin')
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