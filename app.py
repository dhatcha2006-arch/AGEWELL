import os
import sqlite3
from datetime import datetime, date, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
from werkzeug.security import generate_password_hash, check_password_hash

from models import get_db, init_db, log_audit
from scheduler import start_scheduler, notify_user, dispatch_sms

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'agewell-senior-portal-secure-secret-key-2026')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB request limit

def normalize_email(email_str):
    """Trims whitespace and lowercases email address for canonical lookup."""
    return (email_str or '').strip().lower()

# Initialize DB and start APScheduler background worker
init_db()
scheduler = start_scheduler()

# ----------------- Decorators & Helpers -----------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please sign in to access this portal.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            if session.get('role') not in roles:
                flash("Access unauthorized for your user role.", "danger")
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response

@app.context_processor
def inject_global_data():
    unread_count = 0
    active_sos = None
    if 'user_id' in session:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0", (session['user_id'],))
        unread_count = cursor.fetchone()[0]
        
        # Check if there is an active emergency alert for this user or their assigned senior
        if session.get('role') == 'senior':
            cursor.execute("SELECT * FROM emergency_alerts WHERE senior_id = ? AND status IN ('active', 'responding') ORDER BY id DESC LIMIT 1", (session['user_id'],))
            active_sos = cursor.fetchone()
        elif session.get('role') == 'family':
            cursor.execute("""
                SELECT ea.*, u.name as senior_name FROM emergency_alerts ea
                JOIN family_links fl ON ea.senior_id = fl.senior_id
                JOIN users u ON ea.senior_id = u.id
                WHERE fl.family_user_id = ? AND fl.is_approved = 1 AND ea.status IN ('active', 'responding')
                ORDER BY ea.id DESC LIMIT 1
            """, (session['user_id'],))
            active_sos = cursor.fetchone()
        conn.close()
    return {
        'current_user': session.get('user_name'),
        'current_role': session.get('role'),
        'current_user_id': session.get('user_id'),
        'unread_notif_count': unread_count,
        'active_sos_global': active_sos
    }

# ----------------- Public & Auth Routes -----------------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = cursor.fetchone()
        conn.close()

        if user and check_password_hash(user['password_hash'], password):
            if not user['is_active']:
                flash("This account has been deactivated. Please contact administrator.", "danger")
                return render_template('auth/login.html')

            session['user_id'] = user['id']
            session['user_name'] = user['name']
            session['role'] = user['role']
            session['email'] = user['email']

            log_audit(user['id'], "LOGIN", "user", user['id'], f"Logged in with role {user['role']}")

            flash(f"Welcome back, {user['name']}!", "success")
            if user['role'] == 'senior':
                return redirect(url_for('senior_dashboard'))
            elif user['role'] == 'family':
                return redirect(url_for('family_dashboard'))
            elif user['role'] == 'doctor':
                return redirect(url_for('doctor_dashboard'))
            elif user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('index'))
        else:
            flash("Invalid email or password. Try one of the quick demo buttons.", "danger")

    return render_template('auth/login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        role = request.form.get('role', 'senior')
        password = request.form.get('password', '')

        if not name or not email or not password:
            flash("Please fill in all required fields.", "warning")
            return render_template('auth/register.html')

        pwd_hash = generate_password_hash(password)
        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO users (name, email, phone, password_hash, role) VALUES (?, ?, ?, ?, ?)",
                (name, email, phone, pwd_hash, role)
            )
            user_id = cursor.lastrowid
            
            # If senior, create initial profile
            if role == 'senior':
                cursor.execute(
                    "INSERT INTO senior_profiles (user_id, check_in_time, grace_time_minutes) VALUES (?, '09:00', 30)",
                    (user_id,)
                )
                # Seed a default emergency contact
                cursor.execute(
                    "INSERT INTO emergency_contacts (senior_id, name, phone, relation, priority_order) VALUES (?, 'Primary Emergency Responder', '112', 'Emergency Services', 1)",
                    (user_id,)
                )

            conn.commit()
            log_audit(user_id, "REGISTER", "user", user_id, f"Registered new account as {role}")
            flash("Account created successfully! Please sign in.", "success")
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash("An account with this email already exists.", "danger")
        finally:
            conn.close()

    return render_template('auth/register.html')

@app.route('/logout')
def logout():
    user_id = session.get('user_id')
    if user_id:
        log_audit(user_id, "LOGOUT", "user", user_id, "User signed out")
    session.clear()
    flash("You have been signed out safely.", "info")
    return redirect(url_for('login'))

# ----------------- Senior Routes -----------------
@app.route('/senior/dashboard')
@role_required('senior')
def senior_dashboard():
    s_id = session['user_id']
    today_str = date.today().strftime('%Y-%m-%d')
    conn = get_db()
    cursor = conn.cursor()

    # 1. Senior Profile
    cursor.execute("SELECT * FROM senior_profiles WHERE user_id = ?", (s_id,))
    profile = cursor.fetchone()

    # 2. Today's Checkin Status
    cursor.execute("SELECT * FROM daily_checkins WHERE senior_id = ? AND checkin_date = ?", (s_id, today_str))
    today_checkin = cursor.fetchone()

    # 3. Active Medicines and their today's logs
    cursor.execute("SELECT * FROM medicines WHERE senior_id = ? AND is_active = 1", (s_id,))
    meds = cursor.fetchall()
    
    # Enrich meds with today's status
    meds_with_status = []
    for med in meds:
        timings = [t.strip() for t in med['timings'].split(',') if t.strip()]
        for t in timings:
            cursor.execute("""
                SELECT * FROM medicine_logs 
                WHERE medicine_id = ? AND senior_id = ? AND scheduled_date = ? AND scheduled_time = ?
            """, (med['id'], s_id, today_str, t))
            log_entry = cursor.fetchone()
            status = log_entry['status'] if log_entry else 'pending'
            log_id = log_entry['id'] if log_entry else None
            meds_with_status.append({
                'med_id': med['id'],
                'log_id': log_id,
                'name': med['name'],
                'dose': med['dose'],
                'time': t,
                'instructions': med['instructions'],
                'status': status
            })

    # 4. Daily tasks
    cursor.execute("SELECT * FROM daily_tasks WHERE senior_id = ? AND due_date = ? ORDER BY is_completed ASC, time ASC", (s_id, today_str))
    tasks = cursor.fetchall()

    # 5. Upcoming Appointments
    cursor.execute("""
        SELECT * FROM appointments 
        WHERE senior_id = ? AND appointment_date >= ? AND status = 'scheduled'
        ORDER BY appointment_date ASC, appointment_time ASC LIMIT 2
    """, (s_id, today_str))
    upcoming_appointments = cursor.fetchall()

    # 6. Active SOS alert if any
    cursor.execute("SELECT * FROM emergency_alerts WHERE senior_id = ? AND status IN ('active', 'responding') ORDER BY id DESC LIMIT 1", (s_id,))
    active_sos = cursor.fetchone()

    conn.close()
    return render_template(
        'senior/dashboard.html',
        profile=profile,
        today_checkin=today_checkin,
        meds=meds_with_status,
        tasks=tasks,
        appointments=upcoming_appointments,
        active_sos=active_sos,
        today_date=date.today().strftime('%A, %B %d, %Y')
    )

@app.route('/senior/checkin', methods=['POST'])
@role_required('senior')
def senior_checkin():
    s_id = session['user_id']
    today_str = date.today().strftime('%Y-%m-%d')
    now_time = datetime.now().strftime('%I:%M %p')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id FROM daily_checkins WHERE senior_id = ? AND checkin_date = ?
    """, (s_id, today_str))
    existing = cursor.fetchone()

    if existing:
        cursor.execute("""
            UPDATE daily_checkins
            SET checkin_time = ?, status = 'ok', note = 'Pressed I am OK'
            WHERE id = ?
        """, (now_time, existing['id']))
    else:
        cursor.execute("""
            INSERT INTO daily_checkins (senior_id, checkin_date, checkin_time, status, note)
            VALUES (?, ?, ?, 'ok', 'Pressed I am OK')
        """, (s_id, today_str, now_time))
    conn.commit()

    # Notify family members
    cursor.execute("SELECT family_user_id FROM family_links WHERE senior_id = ? AND is_approved = 1", (s_id,))
    for f in cursor.fetchall():
        notify_user(
            f['family_user_id'],
            'info',
            "Senior Checked In Safely",
            f"{session['user_name']} has pressed 'I am OK' today at {now_time}.",
            channel='both'
        )

    log_audit(s_id, "DAILY_CHECKIN", "daily_checkins", s_id, f"Checked in at {now_time}")
    conn.close()

    flash("Wonderful! Your 'I am OK' check-in has been recorded and sent to your family.", "success")
    return redirect(url_for('senior_dashboard'))

@app.route('/senior/medicines')
@role_required('senior')
def senior_medicines():
    s_id = session['user_id']
    today_str = date.today().strftime('%Y-%m-%d')
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM medicines WHERE senior_id = ? AND is_active = 1", (s_id,))
    medicines = cursor.fetchall()

    cursor.execute("""
        SELECT ml.*, m.name as med_name, m.dose as med_dose 
        FROM medicine_logs ml
        JOIN medicines m ON ml.medicine_id = m.id
        WHERE ml.senior_id = ? 
        ORDER BY ml.scheduled_date DESC, ml.scheduled_time DESC LIMIT 20
    """, (s_id,))
    logs = cursor.fetchall()
    conn.close()

    return render_template('senior/medicines.html', medicines=medicines, logs=logs, today_str=today_str)

@app.route('/senior/medicine/action', methods=['POST'])
@role_required('senior')
def senior_medicine_action():
    med_id = request.form.get('med_id')
    sched_time = request.form.get('time')
    action = request.form.get('action') # 'taken' or 'skipped'
    note = request.form.get('note', '')
    today_str = date.today().strftime('%Y-%m-%d')
    now_ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    s_id = session['user_id']
    conn = get_db()
    cursor = conn.cursor()

    # Check if a log exists for today & this time
    cursor.execute("""
        SELECT id FROM medicine_logs 
        WHERE medicine_id = ? AND senior_id = ? AND scheduled_date = ? AND scheduled_time = ?
    """, (med_id, s_id, today_str, sched_time))
    existing = cursor.fetchone()

    if existing:
        cursor.execute("""
            UPDATE medicine_logs 
            SET status = ?, logged_at = ?, note = ?
            WHERE id = ?
        """, (action, now_ts, note, existing['id']))
    else:
        cursor.execute("""
            INSERT INTO medicine_logs (medicine_id, senior_id, scheduled_date, scheduled_time, logged_at, status, note)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (med_id, s_id, today_str, sched_time, now_ts, action, note))
    conn.commit()

    log_audit(s_id, f"MED_{action.upper()}", "medicine_logs", med_id, f"Marked {action} for {sched_time}")
    conn.close()

    msg = f"Marked medicine as {action}!"
    flash(msg, "success" if action == 'taken' else "info")
    return redirect(request.referrer or url_for('senior_dashboard'))

@app.route('/senior/export/medications')
@role_required('senior', 'doctor', 'family')
def export_medications_csv():
    senior_id = session['user_id'] if session['role'] == 'senior' else request.args.get('senior_id', session['user_id'])
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ml.scheduled_date, ml.scheduled_time, m.name as medicine_name, m.dose, ml.status, ml.logged_at, ml.note
        FROM medicine_logs ml
        JOIN medicines m ON ml.medicine_id = m.id
        WHERE ml.senior_id = ?
        ORDER BY ml.scheduled_date DESC, ml.scheduled_time DESC
    """, (senior_id,))
    logs = cursor.fetchall()
    conn.close()

    import csv
    import io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Scheduled Time', 'Medicine Name', 'Dosage', 'Adherence Status', 'Logged At', 'Notes'])
    for r in logs:
        writer.writerow([r['scheduled_date'], r['scheduled_time'], r['medicine_name'], r['dose'], r['status'], r['logged_at'] or '', r['note'] or ''])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename=agewell_medication_logs_senior_{senior_id}.csv"}
    )

@app.route('/senior/appointments')
@role_required('senior')
def senior_appointments():
    s_id = session['user_id']
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM appointments WHERE senior_id = ? ORDER BY appointment_date ASC, appointment_time ASC", (s_id,))
    appointments = cursor.fetchall()
    conn.close()
    return render_template('senior/appointments.html', appointments=appointments)

@app.route('/senior/tasks', methods=['GET', 'POST'])
@role_required('senior')
def senior_tasks():
    s_id = session['user_id']
    today_str = date.today().strftime('%Y-%m-%d')
    conn = get_db()
    cursor = conn.cursor()

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            title = request.form.get('title')
            time_str = request.form.get('time', '12:00')
            desc = request.form.get('description', '')
            cursor.execute(
                "INSERT INTO daily_tasks (senior_id, title, description, time, due_date) VALUES (?, ?, ?, ?, ?)",
                (s_id, title, desc, time_str, today_str)
            )
            conn.commit()
            flash("New daily task added!", "success")
        elif action == 'toggle':
            task_id = request.form.get('task_id')
            cursor.execute("UPDATE daily_tasks SET is_completed = 1 - is_completed WHERE id = ? AND senior_id = ?", (task_id, s_id))
            conn.commit()
            flash("Task updated!", "success")

    cursor.execute("SELECT * FROM daily_tasks WHERE senior_id = ? AND due_date = ? ORDER BY is_completed ASC, time ASC", (s_id, today_str))
    tasks = cursor.fetchall()
    conn.close()
    return render_template('senior/tasks.html', tasks=tasks, today_str=today_str)

@app.route('/senior/profile', methods=['GET', 'POST'])
@role_required('senior')
def senior_profile():
    s_id = session['user_id']
    conn = get_db()
    cursor = conn.cursor()

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'update_profile':
            check_in_time = request.form.get('check_in_time')
            grace = int(request.form.get('grace_time_minutes', 30))
            notes = request.form.get('emergency_notes')
            blood = request.form.get('blood_group')
            address = request.form.get('address')
            cursor.execute("""
                UPDATE senior_profiles 
                SET check_in_time = ?, grace_time_minutes = ?, emergency_notes = ?, blood_group = ?, address = ?
                WHERE user_id = ?
            """, (check_in_time, grace, notes, blood, address, s_id))
            conn.commit()
            flash("Profile settings updated successfully!", "success")
        elif action == 'add_contact':
            name = request.form.get('name')
            phone = request.form.get('phone')
            relation = request.form.get('relation')
            priority = int(request.form.get('priority_order', 1))
            cursor.execute("""
                INSERT INTO emergency_contacts (senior_id, name, phone, relation, priority_order)
                VALUES (?, ?, ?, ?, ?)
            """, (s_id, name, phone, relation, priority))
            conn.commit()
            flash("Emergency contact added!", "success")
        elif action == 'delete_contact':
            contact_id = request.form.get('contact_id')
            cursor.execute("DELETE FROM emergency_contacts WHERE id = ? AND senior_id = ?", (contact_id, s_id))
            conn.commit()
            flash("Contact removed.", "info")

    cursor.execute("SELECT * FROM senior_profiles WHERE user_id = ?", (s_id,))
    profile = cursor.fetchone()
    cursor.execute("SELECT * FROM emergency_contacts WHERE senior_id = ? ORDER BY priority_order ASC", (s_id,))
    contacts = cursor.fetchall()
    cursor.execute("SELECT * FROM users WHERE id = ?", (s_id,))
    user = cursor.fetchone()
    conn.close()

    return render_template('senior/profile.html', profile=profile, contacts=contacts, user=user)

@app.route('/senior/approvals', methods=['GET', 'POST'])
@role_required('senior')
def senior_approvals():
    s_id = session['user_id']
    conn = get_db()
    cursor = conn.cursor()

    if request.method == 'POST':
        item_type = request.form.get('type') # 'family' or 'doctor'
        item_id = request.form.get('id')
        decision = request.form.get('decision') # 'approve' or 'revoke'

        approved_val = 1 if decision == 'approve' else 0
        if item_type == 'family':
            cursor.execute("UPDATE family_links SET is_approved = ? WHERE id = ? AND senior_id = ?", (approved_val, item_id, s_id))
        elif item_type == 'doctor':
            cursor.execute("UPDATE doctor_assignments SET is_approved = ? WHERE id = ? AND senior_id = ?", (approved_val, item_id, s_id))
        conn.commit()
        log_audit(s_id, f"{decision.upper()}_{item_type.upper()}", item_type, item_id, f"Senior {decision}d access")
        flash(f"Access permission {decision}d.", "success")

    # Fetch family links
    cursor.execute("""
        SELECT fl.*, u.name as user_name, u.email as user_email, u.phone as user_phone
        FROM family_links fl
        JOIN users u ON fl.family_user_id = u.id
        WHERE fl.senior_id = ?
    """, (s_id,))
    family_members = cursor.fetchall()

    # Fetch doctor assignments
    cursor.execute("""
        SELECT da.*, u.name as user_name, u.email as user_email, u.phone as user_phone
        FROM doctor_assignments da
        JOIN users u ON da.doctor_user_id = u.id
        WHERE da.senior_id = ?
    """, (s_id,))
    doctors = cursor.fetchall()
    conn.close()

    return render_template('senior/approvals.html', family_members=family_members, doctors=doctors)

# ----------------- SOS & Emergency System -----------------
@app.route('/senior/sos')
@login_required
def senior_sos():
    s_id = session['user_id'] if session.get('role') == 'senior' else request.args.get('senior_id')
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT ea.*, u.name as senior_name, u.phone as senior_phone, sp.emergency_notes, sp.blood_group, sp.address
        FROM emergency_alerts ea
        JOIN users u ON ea.senior_id = u.id
        JOIN senior_profiles sp ON u.id = sp.user_id
        WHERE ea.senior_id = ? AND ea.status IN ('active', 'responding')
        ORDER BY ea.id DESC LIMIT 1
    """, (s_id,))
    active_alert = cursor.fetchone()

    cursor.execute("SELECT * FROM emergency_contacts WHERE senior_id = ? ORDER BY priority_order ASC", (s_id,))
    contacts = cursor.fetchall()

    responder_name = None
    seconds_remaining = 120
    if active_alert:
        active_alert = dict(active_alert)
        max_step = len(contacts) + 1
        active_alert['contact_escalation_step'] = min(active_alert.get('contact_escalation_step', 1) or 1, max_step)

        if active_alert['responded_by_user_id']:
            cursor.execute("SELECT name FROM users WHERE id = ?", (active_alert['responded_by_user_id'],))
            row = cursor.fetchone()
            if row: responder_name = row['name']
        
        triggered_dt = datetime.strptime(str(active_alert['triggered_at']), '%Y-%m-%d %H:%M:%S')
        elapsed = (datetime.now() - triggered_dt).total_seconds()
        # 120 seconds per escalation step
        step_duration = active_alert['contact_escalation_step'] * 120
        seconds_remaining = max(0, int(step_duration - elapsed))

    conn.close()
    return render_template('senior/sos.html', active_alert=active_alert, contacts=contacts, responder_name=responder_name, seconds_remaining=seconds_remaining)

@app.route('/sos/trigger', methods=['POST'])
@login_required
def sos_trigger():
    s_id = request.form.get('senior_id', session.get('user_id'))
    notes = request.form.get('notes', 'SOS Emergency Pressed by Senior!')

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO emergency_alerts (senior_id, contact_escalation_step, status, notes)
        VALUES (?, 1, 'active', ?)
    """, (s_id, notes))
    alert_id = cursor.lastrowid
    conn.commit()

    # Get primary contact
    cursor.execute("SELECT * FROM emergency_contacts WHERE senior_id = ? ORDER BY priority_order ASC LIMIT 1", (s_id,))
    primary = cursor.fetchone()

    cursor.execute("SELECT name FROM users WHERE id = ?", (s_id,))
    senior_name = cursor.fetchone()['name']

    sos_msg = f"EMERGENCY SOS: {senior_name} has pressed the SOS button! Please respond immediately! Emergency line: 112."
    if primary:
        dispatch_sms(primary['phone'], sos_msg)

    # Notify family members and doctors
    cursor.execute("SELECT family_user_id FROM family_links WHERE senior_id = ? AND is_approved = 1", (s_id,))
    for f in cursor.fetchall():
        notify_user(f['family_user_id'], 'sos', 'EMERGENCY SOS ALERT', sos_msg, channel='both')

    cursor.execute("SELECT doctor_user_id FROM doctor_assignments WHERE senior_id = ? AND is_approved = 1", (s_id,))
    for d in cursor.fetchall():
        notify_user(d['doctor_user_id'], 'sos', 'PATIENT EMERGENCY SOS', sos_msg, channel='both')

    log_audit(session['user_id'], "TRIGGER_SOS", "emergency_alerts", alert_id, f"SOS triggered for senior {s_id}")
    conn.close()

    flash("EMERGENCY SOS ACTIVATED! High-priority alerts dispatched to family and doctors.", "danger")
    return redirect(url_for('senior_sos', senior_id=s_id))

@app.route('/sos/respond', methods=['POST'])
@login_required
def sos_respond():
    alert_id = request.form.get('alert_id')
    user_id = session['user_id']
    now_ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE emergency_alerts 
        SET status = 'responding', responded_by_user_id = ?, responded_at = ?
        WHERE id = ?
    """, (user_id, now_ts, alert_id))
    conn.commit()

    # Broadcast that responder is responding
    cursor.execute("SELECT senior_id FROM emergency_alerts WHERE id = ?", (alert_id,))
    senior_id = cursor.fetchone()['senior_id']

    notify_msg = f"{session['user_name']} has tapped 'I am responding' and is attending to the emergency."
    notify_user(senior_id, 'info', "Help is on the way!", notify_msg, channel='both')

    log_audit(user_id, "RESPOND_SOS", "emergency_alerts", alert_id, f"User {session['user_name']} is responding")
    conn.close()

    flash("You have marked yourself as responding! Thank you.", "success")
    return redirect(request.referrer or url_for('family_alerts'))

@app.route('/sos/resolve', methods=['POST'])
@login_required
def sos_resolve():
    alert_id = request.form.get('alert_id')
    notes = request.form.get('resolution_notes', 'Resolved safely')
    now_ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE emergency_alerts 
        SET status = 'resolved', resolved_at = ?, notes = notes || ' [Resolution: ' || ? || ']'
        WHERE id = ?
    """, (now_ts, notes, alert_id))
    conn.commit()

    cursor.execute("SELECT senior_id FROM emergency_alerts WHERE id = ?", (alert_id,))
    senior_id = cursor.fetchone()['senior_id']

    notify_user(senior_id, 'info', "Emergency Resolved", "The emergency status has been marked resolved.", channel='both')
    log_audit(session['user_id'], "RESOLVE_SOS", "emergency_alerts", alert_id, f"Resolved by {session['user_name']}")
    conn.close()

    flash("Emergency marked as RESOLVED.", "success")
    return redirect(request.referrer or url_for('index'))

# ----------------- Family Routes -----------------
@app.route('/family/dashboard')
@role_required('family')
def family_dashboard():
    f_id = session['user_id']
    today_str = date.today().strftime('%Y-%m-%d')
    conn = get_db()
    cursor = conn.cursor()

    # Get approved linked seniors
    cursor.execute("""
        SELECT u.id, u.name, u.phone, sp.address, sp.check_in_time, fl.relation, fl.can_view_medicines, fl.can_view_notes
        FROM family_links fl
        JOIN users u ON fl.senior_id = u.id
        JOIN senior_profiles sp ON u.id = sp.user_id
        WHERE fl.family_user_id = ? AND fl.is_approved = 1
    """, (f_id,))
    seniors = cursor.fetchall()

    seniors_status = []
    for s in seniors:
        s_id = s['id']
        # Today's check-in
        cursor.execute("SELECT * FROM daily_checkins WHERE senior_id = ? AND checkin_date = ?", (s_id, today_str))
        chk = cursor.fetchone()
        
        # Today's medicines compliance
        cursor.execute("SELECT COUNT(*) FROM medicine_logs WHERE senior_id = ? AND scheduled_date = ?", (s_id, today_str))
        total_meds_today = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM medicine_logs WHERE senior_id = ? AND scheduled_date = ? AND status = 'taken'", (s_id, today_str))
        taken_meds_today = cursor.fetchone()[0]
        
        # Active SOS
        cursor.execute("SELECT * FROM emergency_alerts WHERE senior_id = ? AND status IN ('active', 'responding') ORDER BY id DESC LIMIT 1", (s_id,))
        active_sos = cursor.fetchone()

        seniors_status.append({
            'senior': s,
            'checkin': chk,
            'total_meds': total_meds_today,
            'taken_meds': taken_meds_today,
            'active_sos': active_sos
        })

    # Recent Alerts
    cursor.execute("""
        SELECT * FROM notifications 
        WHERE user_id = ? 
        ORDER BY sent_at DESC LIMIT 10
    """, (f_id,))
    recent_alerts = cursor.fetchall()

    conn.close()
    return render_template('family/dashboard.html', seniors_status=seniors_status, alerts=recent_alerts)

@app.route('/family/senior/<int:senior_id>')
@role_required('family')
def family_senior_status(senior_id):
    f_id = session['user_id']
    conn = get_db()
    cursor = conn.cursor()

    # Check permission
    cursor.execute("SELECT * FROM family_links WHERE senior_id = ? AND family_user_id = ? AND is_approved = 1", (senior_id, f_id))
    link = cursor.fetchone()
    if not link:
        flash("You do not have approved access to this senior profile.", "danger")
        return redirect(url_for('family_dashboard'))

    cursor.execute("""
        SELECT u.name, u.email, u.phone, sp.* 
        FROM users u 
        JOIN senior_profiles sp ON u.id = sp.user_id 
        WHERE u.id = ?
    """, (senior_id,))
    senior = cursor.fetchone()

    # Today's logs
    today_str = date.today().strftime('%Y-%m-%d')
    cursor.execute("""
        SELECT ml.*, m.name as med_name, m.dose as med_dose 
        FROM medicine_logs ml
        JOIN medicines m ON ml.medicine_id = m.id
        WHERE ml.senior_id = ? 
        ORDER BY ml.scheduled_date DESC, ml.scheduled_time DESC LIMIT 15
    """, (senior_id,))
    med_logs = cursor.fetchall()

    # Checkins past 7 days
    cursor.execute("SELECT * FROM daily_checkins WHERE senior_id = ? ORDER BY checkin_date DESC LIMIT 7", (senior_id,))
    checkins = cursor.fetchall()

    # Health notes if allowed
    notes = []
    if link['can_view_notes']:
        cursor.execute("SELECT * FROM health_records WHERE senior_id = ? ORDER BY created_at DESC", (senior_id,))
        notes = cursor.fetchall()

    log_audit(f_id, "VIEW_SENIOR_DETAILS", "senior_profile", senior_id, f"Family viewed details of {senior['name']}")
    conn.close()
    return render_template('family/senior_status.html', senior=senior, med_logs=med_logs, checkins=checkins, notes=notes, link=link)

@app.route('/family/alerts')
@role_required('family')
def family_alerts():
    f_id = session['user_id']
    conn = get_db()
    cursor = conn.cursor()

    # Active SOS alerts involving seniors linked to this family member
    cursor.execute("""
        SELECT ea.*, u.name as senior_name, sp.emergency_notes, sp.blood_group, sp.address
        FROM emergency_alerts ea
        JOIN family_links fl ON ea.senior_id = fl.senior_id
        JOIN users u ON ea.senior_id = u.id
        JOIN senior_profiles sp ON u.id = sp.user_id
        WHERE fl.family_user_id = ? AND fl.is_approved = 1 AND ea.status IN ('active', 'responding')
        ORDER BY ea.id DESC
    """, (f_id,))
    active_emergencies = cursor.fetchall()

    # Notifications history
    cursor.execute("SELECT * FROM notifications WHERE user_id = ? ORDER BY sent_at DESC", (f_id,))
    notifications = cursor.fetchall()

    conn.close()
    return render_template('family/alerts.html', active_emergencies=active_emergencies, notifications=notifications)

# ----------------- Doctor Routes -----------------
@app.route('/doctor/dashboard')
@role_required('doctor')
def doctor_dashboard():
    d_id = session['user_id']
    today_str = date.today().strftime('%Y-%m-%d')
    conn = get_db()
    cursor = conn.cursor()

    # Approved patients
    cursor.execute("""
        SELECT u.id, u.name, u.phone, da.specialization, sp.blood_group, sp.date_of_birth
        FROM doctor_assignments da
        JOIN users u ON da.senior_id = u.id
        JOIN senior_profiles sp ON u.id = sp.user_id
        WHERE da.doctor_user_id = ? AND da.is_approved = 1
    """, (d_id,))
    patients = cursor.fetchall()

    # Upcoming Appointments
    cursor.execute("""
        SELECT a.*, u.name as patient_name 
        FROM appointments a
        JOIN users u ON a.senior_id = u.id
        WHERE a.doctor_user_id = ? AND a.appointment_date >= ? AND a.status = 'scheduled'
        ORDER BY a.appointment_date ASC, a.appointment_time ASC
    """, (d_id, today_str))
    appointments = cursor.fetchall()

    conn.close()
    return render_template('doctor/dashboard.html', patients=patients, appointments=appointments)

@app.route('/doctor/patients')
@role_required('doctor')
def doctor_patients():
    d_id = session['user_id']
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.id, u.name, u.email, u.phone, da.specialization, da.hospital, da.is_approved, sp.blood_group, sp.emergency_notes
        FROM doctor_assignments da
        JOIN users u ON da.senior_id = u.id
        JOIN senior_profiles sp ON u.id = sp.user_id
        WHERE da.doctor_user_id = ?
    """, (d_id,))
    patients = cursor.fetchall()
    conn.close()
    return render_template('doctor/patients.html', patients=patients)

@app.route('/doctor/patient/<int:senior_id>', methods=['GET', 'POST'])
@role_required('doctor')
def doctor_patient_details(senior_id):
    d_id = session['user_id']
    conn = get_db()
    cursor = conn.cursor()

    # Verify assignment
    cursor.execute("SELECT * FROM doctor_assignments WHERE doctor_user_id = ? AND senior_id = ? AND is_approved = 1", (d_id, senior_id))
    assignment = cursor.fetchone()
    if not assignment:
        flash("You are not authorized to view this patient (pending senior approval).", "danger")
        return redirect(url_for('doctor_patients'))

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add_medicine':
            name = request.form.get('name')
            dose = request.form.get('dose')
            timings = request.form.get('timings')
            instructions = request.form.get('instructions')
            cursor.execute("""
                INSERT INTO medicines (senior_id, name, dose, timings, instructions, prescribing_doctor_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (senior_id, name, dose, timings, instructions, d_id))
            conn.commit()
            flash("New medicine prescribed successfully!", "success")
        elif action == 'add_record':
            title = request.form.get('title')
            record_type = request.form.get('record_type')
            desc = request.form.get('description')
            cursor.execute("""
                INSERT INTO health_records (senior_id, doctor_user_id, title, record_type, description)
                VALUES (?, ?, ?, ?, ?)
            """, (senior_id, d_id, title, record_type, desc))
            conn.commit()
            flash("Clinical note / Health record saved.", "success")
        elif action == 'update_medicine':
            med_id = request.form.get('med_id')
            instructions = request.form.get('instructions')
            cursor.execute("UPDATE medicines SET instructions = ? WHERE id = ? AND senior_id = ?", (instructions, med_id, senior_id))
            conn.commit()
            flash("Medicine instructions updated.", "success")

    cursor.execute("SELECT u.name, u.email, u.phone, sp.* FROM users u JOIN senior_profiles sp ON u.id = sp.user_id WHERE u.id = ?", (senior_id,))
    patient = cursor.fetchone()

    cursor.execute("SELECT * FROM medicines WHERE senior_id = ? ORDER BY is_active DESC, name ASC", (senior_id,))
    medicines = cursor.fetchall()

    cursor.execute("SELECT * FROM health_records WHERE senior_id = ? ORDER BY created_at DESC", (senior_id,))
    records = cursor.fetchall()

    # Adherence Calculation (Last 30 doses)
    cursor.execute("SELECT COUNT(*) FROM medicine_logs WHERE senior_id = ?", (senior_id,))
    total_logs = cursor.fetchone()[0] or 1
    cursor.execute("SELECT COUNT(*) FROM medicine_logs WHERE senior_id = ? AND status = 'taken'", (senior_id,))
    taken_logs = cursor.fetchone()[0]
    compliance_rate = round((taken_logs / total_logs) * 100)

    log_audit(d_id, "VIEW_PATIENT_MEDICAL", "health_records", senior_id, f"Doctor viewed medical records of {patient['name']}")
    conn.close()
    return render_template('doctor/patient_details.html', patient=patient, medicines=medicines, records=records, compliance_rate=compliance_rate)

@app.route('/doctor/appointments', methods=['GET', 'POST'])
@role_required('doctor')
def doctor_appointments():
    d_id = session['user_id']
    conn = get_db()
    cursor = conn.cursor()

    if request.method == 'POST':
        senior_id = request.form.get('senior_id')
        title = request.form.get('title')
        app_date = request.form.get('date')
        app_time = request.form.get('time')
        location = request.form.get('location')
        notes = request.form.get('notes')
        
        cursor.execute("SELECT name FROM users WHERE id = ?", (d_id,))
        doc_name = cursor.fetchone()['name']

        cursor.execute("""
            INSERT INTO appointments (senior_id, doctor_user_id, doctor_name, title, appointment_date, appointment_time, location, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (senior_id, d_id, doc_name, title, app_date, app_time, location, notes))
        conn.commit()
        flash("Appointment scheduled with patient!", "success")

    cursor.execute("""
        SELECT a.*, u.name as patient_name 
        FROM appointments a 
        JOIN users u ON a.senior_id = u.id 
        WHERE a.doctor_user_id = ? 
        ORDER BY a.appointment_date ASC, a.appointment_time ASC
    """, (d_id,))
    appointments = cursor.fetchall()

    cursor.execute("""
        SELECT u.id, u.name FROM doctor_assignments da 
        JOIN users u ON da.senior_id = u.id 
        WHERE da.doctor_user_id = ? AND da.is_approved = 1
    """, (d_id,))
    patients = cursor.fetchall()
    conn.close()

    return render_template('doctor/appointments.html', appointments=appointments, patients=patients)

@app.route('/doctor/export/appointments')
@role_required('doctor', 'admin')
def export_appointments_csv():
    d_id = session['user_id']
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT a.appointment_date, a.appointment_time, u.name as patient_name, a.title, a.status, a.notes
        FROM appointments a 
        JOIN users u ON a.senior_id = u.id 
        WHERE a.doctor_user_id = ? 
        ORDER BY a.appointment_date DESC, a.appointment_time DESC
    """, (d_id,))
    appts = cursor.fetchall()
    conn.close()

    import csv
    import io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Time', 'Patient Name', 'Title / Reason', 'Status', 'Clinical Notes'])
    for r in appts:
        writer.writerow([r['appointment_date'], r['appointment_time'], r['patient_name'], r['title'], r['status'], r['notes'] or ''])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename=agewell_doctor_appointments_{d_id}.csv"}
    )

# ----------------- Admin Routes -----------------
# PDF Requirement: "Admin: Manages accounts and sees statistics. Cannot see private medical details"
@app.route('/admin/dashboard')
@role_required('admin')
def admin_dashboard():
    conn = get_db()
    cursor = conn.cursor()

    # Statistics
    cursor.execute("SELECT role, COUNT(*) as count FROM users GROUP BY role")
    user_counts = {row['role']: row['count'] for row in cursor.fetchall()}

    cursor.execute("SELECT COUNT(*) FROM emergency_alerts")
    total_emergencies = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM emergency_alerts WHERE status IN ('active', 'responding')")
    active_emergencies = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM notifications")
    total_notifications = cursor.fetchone()[0]

    # Recent Audit Logs
    cursor.execute("""
        SELECT al.*, u.name as actor_name 
        FROM audit_logs al
        LEFT JOIN users u ON al.actor_user_id = u.id
        ORDER BY al.created_at DESC LIMIT 8
    """, ())
    recent_audits = cursor.fetchall()

    conn.close()
    return render_template(
        'admin/dashboard.html',
        user_counts=user_counts,
        total_emergencies=total_emergencies,
        active_emergencies=active_emergencies,
        total_notifications=total_notifications,
        recent_audits=recent_audits
    )

@app.route('/admin/users', methods=['GET', 'POST'])
@role_required('admin')
def admin_users():
    conn = get_db()
    cursor = conn.cursor()

    if request.method == 'POST':
        action = request.form.get('action')
        user_id = request.form.get('user_id')
        if action == 'toggle_status':
            cursor.execute("UPDATE users SET is_active = 1 - is_active WHERE id = ?", (user_id,))
            conn.commit()
            log_audit(session['user_id'], "TOGGLE_USER_STATUS", "users", user_id, "Toggled active state")
            flash("User status changed.", "info")
        elif action == 'create_user':
            name = request.form.get('name')
            email = request.form.get('email').strip().lower()
            phone = request.form.get('phone')
            role = request.form.get('role')
            pwd = generate_password_hash("password123")
            try:
                cursor.execute(
                    "INSERT INTO users (name, email, phone, password_hash, role) VALUES (?, ?, ?, ?, ?)",
                    (name, email, phone, pwd, role)
                )
                new_uid = cursor.lastrowid
                if role == 'senior':
                    cursor.execute("INSERT INTO senior_profiles (user_id) VALUES (?)", (new_uid,))
                conn.commit()
                flash("New user account created!", "success")
            except sqlite3.IntegrityError:
                flash("Email already registered.", "danger")

    cursor.execute("SELECT id, name, email, phone, role, is_active, created_at FROM users ORDER BY created_at DESC")
    users = cursor.fetchall()
    conn.close()
    return render_template('admin/users.html', users=users)

@app.route('/admin/emergencies')
@role_required('admin')
def admin_emergencies():
    conn = get_db()
    cursor = conn.cursor()
    # Admin can see emergency metadata and response times, but NOT private doctor clinical notes
    cursor.execute("""
        SELECT ea.*, u.name as senior_name, resp.name as responder_name
        FROM emergency_alerts ea
        JOIN users u ON ea.senior_id = u.id
        LEFT JOIN users resp ON ea.responded_by_user_id = resp.id
        ORDER BY ea.triggered_at DESC
    """, ())
    emergencies = cursor.fetchall()
    conn.close()
    return render_template('admin/emergencies.html', emergencies=emergencies)

@app.route('/admin/audit-logs')
@role_required('admin')
def admin_audit_logs():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT al.*, u.name as actor_name, u.role as actor_role
        FROM audit_logs al
        LEFT JOIN users u ON al.actor_user_id = u.id
        ORDER BY al.created_at DESC LIMIT 50
    """, ())
    logs = cursor.fetchall()
    conn.close()
    return render_template('admin/audit_logs.html', logs=logs)

@app.route('/admin/export/audit-logs')
@role_required('admin')
def export_audit_logs_csv():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT al.created_at, u.name as actor_name, al.action, al.target_type, al.target_id, al.details, al.ip_address
        FROM audit_logs al
        LEFT JOIN users u ON al.actor_user_id = u.id
        ORDER BY al.created_at DESC LIMIT 500
    """)
    logs = cursor.fetchall()
    conn.close()

    import csv
    import io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Timestamp', 'Actor Name', 'Action', 'Target Type', 'Target ID', 'Details', 'IP Address'])
    for r in logs:
        writer.writerow([r['created_at'], r['actor_name'] or 'System', r['action'], r['target_type'], r['target_id'] or '', r['details'] or '', r['ip_address'] or ''])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=agewell_audit_trail_export.csv"}
    )

# ----------------- Notifications API -----------------
@app.route('/api/notifications/unread-count')
def api_unread_count():
    if 'user_id' not in session:
        return jsonify({'count': 0})
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0", (session['user_id'],))
    count = cursor.fetchone()[0]
    conn.close()
    return jsonify({'count': count})

@app.route('/api/session/heartbeat')
def api_session_heartbeat():
    is_authenticated = 'user_id' in session
    return jsonify({
        'authenticated': is_authenticated,
        'user_id': session.get('user_id'),
        'role': session.get('role')
    })

@app.route('/notifications')
@login_required
def notifications_view():
    conn = get_db()
    cursor = conn.cursor()
    # Mark as read
    cursor.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (session['user_id'],))
    conn.commit()

    cursor.execute("SELECT * FROM notifications WHERE user_id = ? ORDER BY sent_at DESC", (session['user_id'],))
    notifs = cursor.fetchall()
    conn.close()
    return render_template('notifications.html', notifications=notifs)

# ----------------- Chat / Messaging System -----------------
def get_user_chat_contacts(user_id, role):
    """Returns authorized contacts for chat based on user role and relationships."""
    conn = get_db()
    cursor = conn.cursor()
    contacts = []

    if role == 'senior':
        # Senior can message approved Family Members
        cursor.execute("""
            SELECT u.id, u.name, u.role, u.phone, fl.relation as subtitle
            FROM family_links fl
            JOIN users u ON fl.family_user_id = u.id
            WHERE fl.senior_id = ? AND fl.is_approved = 1
            ORDER BY u.name ASC
        """, (user_id,))
        for r in cursor.fetchall():
            contacts.append(dict(r))

        # Senior can message assigned Doctors
        cursor.execute("""
            SELECT u.id, u.name, u.role, u.phone, da.specialization as subtitle
            FROM doctor_assignments da
            JOIN users u ON da.doctor_user_id = u.id
            WHERE da.senior_id = ? AND da.is_approved = 1
            ORDER BY u.name ASC
        """, (user_id,))
        for r in cursor.fetchall():
            contacts.append(dict(r))

    elif role == 'family':
        # Family can message approved Seniors
        cursor.execute("""
            SELECT u.id, u.name, u.role, u.phone, fl.relation as subtitle
            FROM family_links fl
            JOIN users u ON fl.senior_id = u.id
            WHERE fl.family_user_id = ? AND fl.is_approved = 1
            ORDER BY u.name ASC
        """, (user_id,))
        for r in cursor.fetchall():
            contacts.append(dict(r))

        # Family can also message assigned Doctors for their Seniors
        cursor.execute("""
            SELECT DISTINCT u.id, u.name, u.role, u.phone, da.specialization as subtitle
            FROM family_links fl
            JOIN doctor_assignments da ON fl.senior_id = da.senior_id
            JOIN users u ON da.doctor_user_id = u.id
            WHERE fl.family_user_id = ? AND fl.is_approved = 1 AND da.is_approved = 1
            ORDER BY u.name ASC
        """, (user_id,))
        for r in cursor.fetchall():
            if not any(c['id'] == r['id'] for c in contacts):
                contacts.append(dict(r))

    elif role == 'doctor':
        # Doctor can message assigned Seniors
        cursor.execute("""
            SELECT u.id, u.name, u.role, u.phone, da.specialization as subtitle
            FROM doctor_assignments da
            JOIN users u ON da.senior_id = u.id
            WHERE da.doctor_user_id = ? AND da.is_approved = 1
            ORDER BY u.name ASC
        """, (user_id,))
        for r in cursor.fetchall():
            contacts.append(dict(r))

        # Doctor can also message approved Family Members of their Seniors
        cursor.execute("""
            SELECT DISTINCT u.id, u.name, u.role, u.phone, fl.relation as subtitle
            FROM doctor_assignments da
            JOIN family_links fl ON da.senior_id = fl.senior_id
            JOIN users u ON fl.family_user_id = u.id
            WHERE da.doctor_user_id = ? AND da.is_approved = 1 AND fl.is_approved = 1
            ORDER BY u.name ASC
        """, (user_id,))
        for r in cursor.fetchall():
            if not any(c['id'] == r['id'] for c in contacts):
                contacts.append(dict(r))

    elif role == 'admin':
        # Admin can view/message active users for support
        cursor.execute("""
            SELECT id, name, role, phone, role as subtitle
            FROM users
            WHERE id != ?
            ORDER BY name ASC
        """, (user_id,))
        for r in cursor.fetchall():
            contacts.append(dict(r))

    # Add last message and unread count for each contact
    for c in contacts:
        c_id = c['id']
        cursor.execute("""
            SELECT message, sent_at, sender_id
            FROM messages
            WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
            ORDER BY sent_at DESC LIMIT 1
        """, (user_id, c_id, c_id, user_id))
        last_m = cursor.fetchone()
        if last_m:
            c['last_message'] = last_m['message']
            c['last_message_time'] = last_m['sent_at']
        else:
            c['last_message'] = 'No messages yet'
            c['last_message_time'] = ''

        cursor.execute("""
            SELECT COUNT(*) FROM messages
            WHERE sender_id = ? AND receiver_id = ? AND is_read = 0
        """, (c_id, user_id))
        c['unread_count'] = cursor.fetchone()[0]

    conn.close()
    return contacts

@app.route('/chat')
@app.route('/chat/<int:contact_id>')
@login_required
def chat_view(contact_id=None):
    user_id = session['user_id']
    role = session['role']
    contacts = get_user_chat_contacts(user_id, role)

    active_contact = None
    messages = []

    if contacts:
        if contact_id:
            active_contact = next((c for c in contacts if c['id'] == contact_id), None)
        if not active_contact:
            active_contact = contacts[0]

        # Fetch messages between user and active_contact
        conn = get_db()
        cursor = conn.cursor()
        c_id = active_contact['id']

        # Mark messages from active_contact as read
        cursor.execute("""
            UPDATE messages SET is_read = 1
            WHERE sender_id = ? AND receiver_id = ?
        """, (c_id, user_id))
        conn.commit()

        cursor.execute("""
            SELECT m.*, u.name as sender_name
            FROM messages m
            JOIN users u ON m.sender_id = u.id
            WHERE (m.sender_id = ? AND m.receiver_id = ?)
               OR (m.sender_id = ? AND m.receiver_id = ?)
            ORDER BY m.sent_at ASC
        """, (user_id, c_id, c_id, user_id))
        messages = cursor.fetchall()
        conn.close()

    return render_template(
        'chat.html',
        contacts=contacts,
        active_contact=active_contact,
        messages=messages
    )

@app.route('/api/chat/send', methods=['POST'])
@login_required
def api_chat_send():
    data = request.get_json() or {}
    receiver_id = data.get('receiver_id')
    message_text = (data.get('message') or '').strip()

    if not receiver_id or not message_text:
        return jsonify({'success': False, 'error': 'Missing recipient or message'}), 400

    user_id = session['user_id']
    role = session['role']

    # Security check: verify receiver is an authorized contact
    contacts = get_user_chat_contacts(user_id, role)
    allowed_ids = [c['id'] for c in contacts]
    if int(receiver_id) not in allowed_ids:
        return jsonify({'success': False, 'error': 'Unauthorized conversation'}), 403

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO messages (sender_id, receiver_id, message, is_read, sent_at)
        VALUES (?, ?, ?, 0, datetime('now', 'localtime'))
    """, (user_id, receiver_id, message_text))
    new_msg_id = cursor.lastrowid
    conn.commit()

    cursor.execute("SELECT * FROM messages WHERE id = ?", (new_msg_id,))
    msg = dict(cursor.fetchone())
    conn.close()

    return jsonify({'success': True, 'message': msg})

@app.route('/api/chat/poll/<int:contact_id>')
@login_required
def api_chat_poll(contact_id):
    user_id = session['user_id']
    conn = get_db()
    cursor = conn.cursor()

    # Mark incoming as read
    cursor.execute("""
        UPDATE messages SET is_read = 1
        WHERE sender_id = ? AND receiver_id = ?
    """, (contact_id, user_id))
    conn.commit()

    cursor.execute("""
        SELECT m.*, u.name as sender_name
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE (m.sender_id = ? AND m.receiver_id = ?)
           OR (m.sender_id = ? AND m.receiver_id = ?)
        ORDER BY m.sent_at ASC
    """, (user_id, contact_id, contact_id, user_id))
    msgs = [dict(r) for r in cursor.fetchall()]
    conn.close()

    return jsonify({'success': True, 'messages': msgs})

# ----------------- Custom Error Handlers -----------------
@app.errorhandler(404)
def not_found_error(error):
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('errors/500.html'), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
