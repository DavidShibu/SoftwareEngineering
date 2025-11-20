from flask import Blueprint, render_template, request, redirect, url_for, flash
from supabase import create_client, Client
from datetime import datetime
import uuid
import os
from werkzeug.security import generate_password_hash

# Import the shared decorator
from decorators import login_required

add_employee_bp = Blueprint('add_employee_bp', __name__)

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

@add_employee_bp.route('/add_employee', methods=['GET'])
@login_required(role='admin') 
def add_employee_form():
    try:
        # 1. Fetch Terminals for the dropdown
        terminals_res = supabase.table('terminals').select('*').execute()
        terminals = terminals_res.data if terminals_res.data else []

        employees_res = supabase.table('users') \
            .select('*') \
            .eq('role', 'employee') \
            .order('created_at', desc=True) \
            .execute()
        employees = employees_res.data if employees_res.data else []

        return render_template('add_employee.html', terminals=terminals, employees=employees)

    except Exception as e:
        flash(f"Error loading data: {e}", "error")
        # If error, render with empty lists to prevent crash
        return render_template('add_employee.html', terminals=[], employees=[])


# ----------------------------------------------
# Handle Add Employee form submission
# ----------------------------------------------
@add_employee_bp.route('/add_employee', methods=['POST'])
@login_required(role='admin')
def add_employee_submit():
    try:
        full_name = request.form['full_name']
        email = request.form['email']
        phone = request.form['phone']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        employee_category = request.form['employee_category']
        terminal_id = request.form.get('terminal_id')

        if password != confirm_password:
            flash("Passwords do not match!", "error")
            return redirect(url_for('add_employee_bp.add_employee_form'))

        # Check if email already exists
        existing = supabase.table("users").select("id").eq("email", email).execute()
        if existing.data:
            flash("Email already exists!", "error")
            return redirect(url_for("add_employee_bp.add_employee_form"))

        # Hash the password
        hashed_password = generate_password_hash(password)

        # Handle empty terminal_id (convert empty string to None for database NULL)
        if not terminal_id:
            terminal_id = None

        data = {
            'id': str(uuid.uuid4()),
            'email': email,
            'password': hashed_password,
            'full_name': full_name,
            'phone': phone,
            'role': 'employee',
            'employee_category': employee_category,
            'terminal_id': terminal_id,
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat(),
            'is_active': True
        }

        supabase.table('users').insert(data).execute()
        
        flash("✅ Employee added successfully!", "success")
        
        # --- CHANGED: Redirect back to the FORM to see the new entry in the table ---
        return redirect(url_for('add_employee_bp.add_employee_form'))

    except Exception as e:
        flash(f"❌ Error adding employee: {e}", "error")
        return redirect(url_for('add_employee_bp.add_employee_form'))