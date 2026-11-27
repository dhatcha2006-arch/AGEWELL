import sqlite3
import os
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'agewell.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. users
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        phone TEXT,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('senior', 'family', 'doctor', 'admin')),
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # 2. senior_profiles
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS senior_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE NOT NULL,
        check_in_time TEXT DEFAULT '09:00',
        grace_time_minutes INTEGER DEFAULT 30,
        blood_group TEXT DEFAULT 'O+',
        emergency_notes TEXT,
        address TEXT,
        date_of_birth TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    ''')

    # 3. family_links
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS family_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        senior_id INTEGER NOT NULL,
        family_user_id INTEGER NOT NULL,
        relation TEXT DEFAULT 'Family Member',
        is_approved INTEGER DEFAULT 0,
        can_view_medicines INTEGER DEFAULT 1,
        can_view_notes INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (senior_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (family_user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    ''')

    # 4. doctor_assignments
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS doctor_assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        senior_id INTEGER NOT NULL,
        doctor_user_id INTEGER NOT NULL,
        specialization TEXT DEFAULT 'General Physician',
        hospital TEXT DEFAULT 'City Health Center',
        is_approved INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (senior_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (doctor_user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    ''')

    # 5. emergency_contacts
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS emergency_contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        senior_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        phone TEXT NOT NULL,
        relation TEXT NOT NULL,
        priority_order INTEGER DEFAULT 1,
        FOREIGN KEY (senior_id) REFERENCES users(id) ON DELETE CASCADE
    )
    ''')

    # 6. health_records
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS health_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        senior_id INTEGER NOT NULL,
        doctor_user_id INTEGER,
        title TEXT NOT NULL,
        record_type TEXT DEFAULT 'clinical_note',
        description TEXT NOT NULL,
        file_url TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (senior_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (doctor_user_id) REFERENCES users(id) ON DELETE SET NULL
    )
    ''')

    # 7. medicines
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS medicines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        senior_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        dose TEXT NOT NULL,
        timings TEXT NOT NULL,
        instructions TEXT,
        prescribing_doctor_id INTEGER,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (senior_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (prescribing_doctor_id) REFERENCES users(id) ON DELETE SET NULL
    )
    ''')

    # 8. medicine_logs
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS medicine_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        medicine_id INTEGER NOT NULL,
        senior_id INTEGER NOT NULL,
        scheduled_date TEXT NOT NULL,
        scheduled_time TEXT NOT NULL,
        logged_at TIMESTAMP,
        status TEXT NOT NULL CHECK(status IN ('taken', 'skipped', 'missed', 'pending')),
        note TEXT,
        FOREIGN KEY (medicine_id) REFERENCES medicines(id) ON DELETE CASCADE,
        FOREIGN KEY (senior_id) REFERENCES users(id) ON DELETE CASCADE
    )
    ''')

    # 9. daily_tasks
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS daily_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        senior_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        time TEXT NOT NULL,
        is_completed INTEGER DEFAULT 0,
        due_date TEXT NOT NULL,
        FOREIGN KEY (senior_id) REFERENCES users(id) ON DELETE CASCADE
    )
    ''')

    # 10. appointments
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS appointments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        senior_id INTEGER NOT NULL,
        doctor_user_id INTEGER,
        doctor_name TEXT NOT NULL,
        title TEXT NOT NULL,
        appointment_date TEXT NOT NULL,
        appointment_time TEXT NOT NULL,
        location TEXT,
        notes TEXT,
        status TEXT DEFAULT 'scheduled' CHECK(status IN ('scheduled', 'completed', 'cancelled')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (senior_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (doctor_user_id) REFERENCES users(id) ON DELETE SET NULL
    )
    ''')

    # 11. daily_checkins
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS daily_checkins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        senior_id INTEGER NOT NULL,
        checkin_date TEXT NOT NULL,
        checkin_time TEXT,
        status TEXT NOT NULL CHECK(status IN ('ok', 'missed', 'late', 'pending')),
        note TEXT,
        FOREIGN KEY (senior_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(senior_id, checkin_date)
    )
    ''')

    # 12. emergency_alerts
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS emergency_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        senior_id INTEGER NOT NULL,
        triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        contact_escalation_step INTEGER DEFAULT 1,
        responded_by_user_id INTEGER,
        responded_at TIMESTAMP,
        resolved_at TIMESTAMP,
        status TEXT DEFAULT 'active' CHECK(status IN ('active', 'responding', 'resolved')),
        notes TEXT,
        location_lat REAL DEFAULT 29.4241,
        location_lng REAL DEFAULT -98.4936,
        FOREIGN KEY (senior_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (responded_by_user_id) REFERENCES users(id) ON DELETE SET NULL
    )
    ''')

    # 13. notifications
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        type TEXT NOT NULL CHECK(type IN ('sos', 'missed_medicine', 'missed_checkin', 'approval_request', 'info')),
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        channel TEXT DEFAULT 'both' CHECK(channel IN ('in-app', 'sms', 'both')),
        is_read INTEGER DEFAULT 0,
        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    ''')

    # 14. audit_logs
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_user_id INTEGER,
        action TEXT NOT NULL,
        target_type TEXT NOT NULL,
        target_id INTEGER,
        details TEXT,
        ip_address TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (actor_user_id) REFERENCES users(id) ON DELETE SET NULL
    )
    ''')

    # 15. messages (Dedicated chat between Senior, Family, and Doctor)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER NOT NULL,
        receiver_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        is_read INTEGER DEFAULT 0,
        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (receiver_id) REFERENCES users(id) ON DELETE CASCADE
    )
    ''')

    # Performance Indexes for Fast Lookups & High-Concurrency Emergency Tracking
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_alerts_senior_status ON emergency_alerts (senior_id, status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_meds_senior_active ON medicines (senior_id, is_active)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_medlogs_senior_date ON medicine_logs (senior_id, scheduled_date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_checkins_senior_date ON daily_checkins (senior_id, checkin_date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_participants ON messages (sender_id, receiver_id, sent_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON notifications (user_id, is_read)')

    conn.commit()
    conn.close()

def log_audit(actor_id, action, target_type, target_id=None, details=None, ip="127.0.0.1"):
    conn = get_db()
    conn.execute(
        "INSERT INTO audit_logs (actor_user_id, action, target_type, target_id, details, ip_address) VALUES (?, ?, ?, ?, ?, ?)",
        (actor_id, action, target_type, target_id, details, ip)
    )
    conn.commit()
    conn.close()
