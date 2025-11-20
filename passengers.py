from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from supabase import create_client, Client
from datetime import datetime
import uuid
import os

from decorators import login_required

passenger_bp = Blueprint('passenger_bp', __name__)

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_time_slots():
    
    slots = []
    for hour in range(8, 21): 
        slots.append(f"{hour:02d}:00")
        if hour != 20: 
            slots.append(f"{hour:02d}:30")
    return slots
# -----------------------------------------------------------

@passenger_bp.route('/dashboard')
@login_required(role='passenger')
def passenger_dashboard():

    user_id = session.get('user_id')
    preferences = []
    terminals = []
    
    try:

        pref_response = supabase.table('passenger_preferences').select('id, preferred_time, routes(name, base_price)') \
            .eq('passenger_id', user_id).order('preferred_time').execute()
        if pref_response.data:
            preferences = pref_response.data
           
        term_response = supabase.table('terminals').select('*').order('name').execute()
        if term_response.data:
            terminals = term_response.data

    except Exception as e:
        flash(f"Error loading dashboard data: {e}", "error")

    time_slots = get_time_slots()

    return render_template(
        'passenger_dashboard.html',
        preferences=preferences,
        terminals=terminals,
        time_slots=time_slots
    )

@passenger_bp.route('/save_preferences', methods=['POST'])
@login_required(role='passenger')
def save_preferences():
    """
    Saves the notification preferences from the dashboard form.
    --- MODIFIED: This function now ONLY ADDS new preferences. ---
    """
    user_id = session.get('user_id')
    
    try:

        from_terminal_ids = request.form.getlist('from_terminal_id')
        to_terminal_ids = request.form.getlist('to_terminal_id')
        preferred_times = request.form.getlist('preferred_time')

    
        new_prefs_data = []
        
        for from_id, to_id, time_str in zip(from_terminal_ids, to_terminal_ids, preferred_times):
            if not from_id or not to_id or not time_str:
                continue # Skip incomplete rows

            if from_id == to_id:
                flash(f"'From' and 'To' terminals cannot be the same. Skipping row.", "error")
                continue

            route_response = supabase.table('routes').select('id') \
                .eq('origin_terminal_id', from_id) \
                .eq('destination_terminal_id', to_id) \
                .limit(1).execute()

            if route_response.data:
                route_id = route_response.data[0]['id']
                
                existing_pref = supabase.table('passenger_preferences') \
                    .select('id') \
                    .eq('passenger_id', user_id) \
                    .eq('route_id', route_id) \
                    .eq('preferred_time', time_str) \
                    .limit(1).execute()
                
                if not existing_pref.data:
                    new_prefs_data.append({
                        'passenger_id': user_id,
                        'route_id': route_id,
                        'preferred_time': time_str
                    })
                else:
                    flash(f"Preference already exists and was skipped.", "info")
            else:
                flash(f"Could not find a valid route for one of your selections. Skipping.", "error")

        if new_prefs_data:
            supabase.table('passenger_preferences').insert(new_prefs_data).execute()

        flash("New preferences saved successfully!", "success")

    except Exception as e:
        flash(f"Error saving preferences: {e}", "error")

    return redirect(url_for('passenger_bp.passenger_dashboard'))

@passenger_bp.route('/delete_preference/<preference_id>', methods=['POST'])
@login_required(role='passenger')
def delete_preference(preference_id):
    """
    Deletes a single preference entry.
    """
    user_id = session.get('user_id')
    try:
       
        response = supabase.table('passenger_preferences').delete() \
            .eq('id', preference_id) \
            .eq('passenger_id', user_id) \
            .execute()
        
        if response.data:
            flash("Preference removed successfully.", "success")
        else:
            flash("Could not find preference to remove.", "error")
            
    except Exception as e:
        flash(f"Error removing preference: {e}", "error")

    return redirect(url_for('passenger_bp.passenger_dashboard'))

@passenger_bp.route('/feedback', methods=['GET', 'POST'])
@login_required(role='passenger')
def give_feedback():
    if request.method == 'POST':
        try:
            user_id = session.get('user_id')
            subject = request.form.get('subject')
            message = request.form.get('message')
            files = request.files.getlist('attachments')

            if not message:
                flash("Message is required.", "error")
                return redirect(url_for('passenger_bp.give_feedback'))

            feedback_entry = {
                "passenger_id": user_id,
                "subject": subject,
                "message": message
            }
            feedback_res = supabase.table('feedbacks').insert(feedback_entry).execute()
            feedback_id = feedback_res.data[0]['id']

            if files and feedback_id:
                attachment_entries = []
                for file in files:
                    if file.filename:

                        file_ext = os.path.splitext(file.filename)[1]
                        file_name = f"{user_id}/{feedback_id}_{uuid.uuid4()}{file_ext}"
                        content_type = file.mimetype
                        supabase.storage.from_('pdfs').upload(file_name, file.read(),{"content-type": content_type})
                        
                      
                        public_url = supabase.storage.from_('pdfs').get_public_url(file_name)
                        
                        attachment_entries.append({
                            "feedback_id": feedback_id,
                            "file_url": public_url,
                            "file_type": file.mimetype
                        })

                if attachment_entries:
                    supabase.table('attachments').insert(attachment_entries).execute()

            flash("Feedback submitted successfully!", "success")
            return redirect(url_for('passenger_bp.previous_feedbacks'))

        except Exception as e:
            flash(f"Error submitting feedback: {e}", "error")
    
    return render_template('give_feedback.html')

@passenger_bp.route('/my_feedbacks')
@login_required(role='passenger')
def previous_feedbacks():
    feedbacks = []
    try:
        user_id = session.get('user_id')
        response = supabase.table('feedbacks').select('*, attachments(*)') \
            .eq('passenger_id', user_id).order('submitted_at', desc=True).execute()
        
        if response.data:
            feedbacks = response.data
            
    except Exception as e:
        flash(f"Error loading feedback history: {e}", "error")

    return render_template('previous_feedbacks.html', feedbacks=feedbacks)

@passenger_bp.route('/complaint', methods=['GET', 'POST'])
@login_required(role='passenger')
def give_complaint():
    if request.method == 'POST':
        try:
            user_id = session.get('user_id')
            subject = request.form.get('subject')
            message = request.form.get('message')
            files = request.files.getlist('attachments')

            if not message:
                flash("Complaint message is required.", "error")
                return redirect(url_for('passenger_bp.give_complaint'))
            complaint_entry = {
                "passenger_id": user_id,
                "subject": subject,
                "message": message,
                "status": "pending"
            }
            complaint_res = supabase.table('complaints').insert(complaint_entry).execute()
            complaint_id = complaint_res.data[0]['id']
            if files and complaint_id:
                attachment_entries = []
                for file in files:
                    if file.filename:
                        file_ext = os.path.splitext(file.filename)[1]
                        file_name = f"{user_id}/complaint_{complaint_id}_{uuid.uuid4()}{file_ext}"
                        contentt_type = file.mimetype
                        supabase.storage.from_('pdfs').upload(file_name, file.read(),{"content-type": contentt_type})
                        public_url = supabase.storage.from_('pdfs').get_public_url(file_name)
                        
                        attachment_entries.append({
                            "complaint_id": complaint_id,
                            "file_url": public_url,
                            "file_type": file.mimetype
                        })
                if attachment_entries:
                    supabase.table('attachments').insert(attachment_entries).execute()

            flash("Complaint submitted successfully! We will review it shortly.", "success")
            return redirect(url_for('passenger_bp.previous_complaints'))

        except Exception as e:
            flash(f"Error submitting complaint: {e}", "error")
            
    return render_template('give_complaint.html')

@passenger_bp.route('/my_complaints')
@login_required(role='passenger')
def previous_complaints():
    complaints = []
    try:
        user_id = session.get('user_id')
        response = supabase.table('complaints').select('*, attachments(*)') \
            .eq('passenger_id', user_id).order('submitted_at', desc=True).execute()
        
        if response.data:
            complaints = response.data
            
    except Exception as e:
        flash(f"Error loading complaint history: {e}", "error")

    return render_template('previous_complaints.html', complaints=complaints)