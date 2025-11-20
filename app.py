from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, Response
from supabase import create_client, Client
from datetime import timedelta
from dotenv import load_dotenv
import os, uuid, json
from werkzeug.security import generate_password_hash, check_password_hash
from dateutil import parser
import re

# Import the new decorator
from decorators import login_required

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'wavelink-secret-key-change-this')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)

# Supabase configuration
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Import blueprints
from add_employee import add_employee_bp
app.register_blueprint(add_employee_bp)

from passengers import passenger_bp
app.register_blueprint(passenger_bp, url_prefix='/passenger')

from employee_features import employee_bp
app.register_blueprint(employee_bp, url_prefix='/employee')
from admin_features import admin_features_bp
app.register_blueprint(admin_features_bp)


# ---------------------------------
# Root route
# ---------------------------------
@app.route('/')
def index():
    if 'user_id' in session:
        role = session.get('role')
        if role == 'admin':
            return redirect(url_for('admin_dashboard'))
        elif role == 'employee':
            return redirect(url_for('employee_dashboard'))
        elif role == 'passenger':
            return redirect(url_for('passenger_dashboard'))
    # If not logged in, or no role, show landing
    return render_template('landing.html') 

@app.route('/api/live_map_data')
def live_map_data():
    # Fetch active terminals with coordinates
    terminals_data = supabase.table("terminals").select("*").eq("is_active", True).execute()
    terminals = terminals_data.data

    # If you have routes table, add this too
    routes_data = supabase.table("routes").select("*").execute()
    routes = routes_data.data

    return jsonify({"terminals": terminals, "routes": routes})


@app.route('/live_map')
def live_map():
    return render_template("live_map.html")

# ---------------------------------
# Passenger registration
# ---------------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form.get("full_name")
        email = request.form.get("email")
        phone = request.form.get("phone")
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")

        if password != confirm_password:
            flash("Passwords do not match!", "error")
            return redirect(url_for("register"))

        # Check if user already exists
        existing = supabase.table("users").select("id").eq("email", email).execute()
        if existing.data:
            flash("Email already registered!", "error")
            return redirect(url_for("register"))

        # Hash the password
        hashed_password = generate_password_hash(password)

        data = {
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "password": hashed_password, 
            "role": "passenger"
        }

        try:
            supabase.table("users").insert(data).execute()
            flash("Registration successful! Please login.", "success")
            return redirect(url_for("login"))
        except Exception as e:
            flash(f"Error: {str(e)}", "error")
            return redirect(url_for("register"))
    return render_template("register.html")


# ---------------------------------
# Login
# ---------------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        if not email or not password:
            flash('Email and password are required', 'error')
            return redirect(url_for('login'))

        result = supabase.table('users').select('*').eq('email', email).limit(1).execute()

        if not result.data:
            flash('Invalid email or password', 'error')
            return redirect(url_for('login'))

        user = result.data[0]

        # Check the hashed password
        if user.get('password') and check_password_hash(user['password'], password):
            session.permanent = True
            session['user_id'] = user['id']
            session['email'] = user['email']
            session['full_name'] = user['full_name']
            session['role'] = user['role']
            session['employee_category'] = user.get('employee_category')

            flash(f'Welcome back, {user["full_name"]}!', 'success')

            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            elif user['role'] == 'employee':
                return redirect(url_for('employee_dashboard'))
            elif user['role'] == 'passenger':
                return redirect(url_for('passenger_dashboard'))
        else:
            flash('Invalid email or password', 'error')
    return render_template('login.html')


# ---------------------------------
# Logout
# ---------------------------------
@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out successfully', 'success')
    return redirect(url_for('index'))

# ---------------------------------
# PROFILE ROUTES (Consolidated Here)
# ---------------------------------
@app.route('/profile')
@login_required(role='any') 
def profile():
    try:
        user_id = session.get('user_id')
        
        # Fetch fresh user data from Supabase 'users' table
        response = supabase.table('users').select('*').eq('id', user_id).single().execute()
        user_data = response.data
        
        return render_template('profile.html', user=user_data)
    except Exception as e:
        flash(f"Error loading profile: {e}", "error")
        return redirect(url_for('index'))

@app.route('/update_profile', methods=['POST'])
@login_required(role='any')
def update_profile():
    try:
        user_id = session.get('user_id')
        full_name = request.form.get('full_name')
        phone = request.form.get('phone')
        
        # Update 'users' table
        data = {"full_name": full_name, "phone": phone}
        supabase.table('users').update(data).eq('id', user_id).execute()
        
        # Update session data to reflect changes immediately
        session['full_name'] = full_name
        
        flash("Profile updated successfully!", "success")
    except Exception as e:
        flash(f"Error updating profile: {e}", "error")
        
    return redirect(url_for('profile'))

@app.route('/change_password', methods=['POST'])
@login_required(role='any')
def change_password():
    try:
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if new_password != confirm_password:
            flash("Passwords do not match.", "error")
            return redirect(url_for('profile'))
            
        if len(new_password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return redirect(url_for('profile'))

        # Update password in Supabase Auth
        # Note: This requires service_role key if modifying auth.users directly, 
        # but here we might be assuming a custom user table or admin rights.
        attributes = {"password": new_password}
        try:
            supabase.auth.admin.update_user_by_id(session.get('user_id'), attributes)
            flash("Password changed successfully.", "success")
        except:
            # If not using Supabase Auth, update your local users table hash
            hashed = generate_password_hash(new_password)
            supabase.table('users').update({'password': hashed}).eq('id', session.get('user_id')).execute()
            flash("Password changed successfully.", "success")

    except Exception as e:
        flash(f"Error changing password: {e}", "error")
        
    return redirect(url_for('profile'))

@app.route('/download_data')
@login_required(role='any')
def download_data():
    try:
        user_id = session.get('user_id')
        
        # Fetch all user data
        user_res = supabase.table('users').select('*').eq('id', user_id).single().execute()
        user_data = user_res.data
        
        # Convert to JSON string
        json_str = json.dumps(user_data, indent=4, default=str)
        
        # Create file download response
        return Response(
            json_str,
            mimetype="application/json",
            headers={"Content-disposition": "attachment; filename=my_wavelink_data.json"}
        )
    except Exception as e:
        flash(f"Error downloading data: {e}", "error")
        return redirect(url_for('profile'))

# ---------------------------------
# Dashboards
# ---------------------------------
@app.route('/admin/dashboard')
@login_required(role='admin')
def admin_dashboard():
    try:
        # Use .count() for cleaner count fetching
        total_users = supabase.table('users').select('id', count='exact').execute()
        employees = supabase.table('users').select('id', count='exact').eq('role', 'employee').execute()
        passengers = supabase.table('users').select('id', count='exact').eq('role', 'passenger').execute()

        stats = {
            'total_users': total_users.count or 0,
            'employees': employees.count or 0,
            'passengers': passengers.count or 0,
        }

        return render_template('admin_dashboard.html', stats=stats)
    except Exception as e:
        flash(f'Error loading dashboard: {str(e)}', 'error')
        return render_template('admin_dashboard.html', stats={})


@app.route('/employee/dashboard')
@login_required(role='employee')
def employee_dashboard():
    category = session.get('employee_category', 'General')
    return render_template('er.html', category=category)


@app.route('/passenger/dashboard')
@login_required(role='passenger')
def passenger_dashboard():
    return render_template('passenger_dashboard.html')

# --- REMOVED THE DUPLICATE PROFILE ROUTE THAT WAS HERE ---

@app.template_filter('format_datetime')
def format_datetime(value, format='%Y-%m-%d %H:%M'):
    if value is None:
        return ""
    # Assuming value is an ISO 8601 string with timezone
    try:
        dt = parser.parse(value)
        return dt.strftime(format)
    except:
        return value


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)