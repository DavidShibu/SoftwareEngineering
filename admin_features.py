from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from supabase import create_client, Client
import os
from decorators import login_required
from datetime import datetime

admin_features_bp = Blueprint('admin_features_bp', __name__)

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- HELPER ---
def append_reply_to_message(original_message, reply_text, admin_name):
    """Appends admin reply to the existing text field to avoid DB schema changes."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"{original_message}\n\n--------------------------------------------------\n[REPLY from {admin_name} on {timestamp}]:\n{reply_text}"

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
        employee_name = request.form.get('employee_name_hidden')
        current_narrative = request.form.get('current_narrative') or ""
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        updated_narrative = f"{current_narrative}\n\n[ASSIGNED]: Case assigned to {employee_name} on {timestamp}."
        
        supabase.table('accidents').update({
            'narrative': updated_narrative,
            'status': 'Assigned'
        }).eq('id', incident_id).execute()
        flash(f"Incident assigned to {employee_name}.", "success")
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
        original_message = request.form.get('original_message')
        
        new_message = append_reply_to_message(original_message, reply_text, session.get('full_name'))
        
        # Update status to 'Resolved' (or 'Replied') and update message
        supabase.table('complaints').update({
            'message': new_message,
            'status': 'Resolved' 
        }).eq('id', complaint_id).execute()
        
        flash("Reply sent successfully.", "success")
    except Exception as e:
        flash(f"Error sending reply: {e}", "error")
    return redirect(url_for('admin_features_bp.admin_complaints'))


# --- 4. FEEDBACK (With Reply) ---
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
        original_message = request.form.get('original_message')
        
        new_message = append_reply_to_message(original_message, reply_text, session.get('full_name'))
        
        # Feedback usually has no 'status' column, so we just update the message
        supabase.table('feedbacks').update({
            'message': new_message
        }).eq('id', feedback_id).execute()
        
        flash("Reply added to feedback.", "success")
    except Exception as e:
        flash(f"Error replying to feedback: {e}", "error")
    return redirect(url_for('admin_features_bp.admin_feedbacks'))