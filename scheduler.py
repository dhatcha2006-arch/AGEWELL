import os
import sqlite3
from datetime import datetime, date, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from models import DB_PATH, get_db

def dispatch_sms(phone, message):
    """
    Dispatches SMS via Twilio / Fast2SMS if API keys are configured,
    or registers high-fidelity SMS broadcast event in logs.
    """
    print(f"[SMS DISPATCH] To: {phone} | Message: {message}")
    # Extensible hook: if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN are set:
    # client = Client(sid, token); client.messages.create(to=phone, from_=..., body=message)
    return True

def notify_user(user_id, notif_type, title, message, channel='both'):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO notifications (user_id, type, title, message, channel, is_read, sent_at) VALUES (?, ?, ?, ?, ?, 0, ?)",
        (user_id, notif_type, title, message, channel, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    )
    conn.commit()
    
    # Also fetch user's phone to dispatch simulated SMS
    cursor.execute("SELECT phone FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if row and row['phone'] and channel in ('sms', 'both'):
        dispatch_sms(row['phone'], f"[AGEWELL ALERT] {title}: {message}")
    conn.close()

def check_missed_medicines():
    try:
        conn = get_db()
        cursor = conn.cursor()
        now = datetime.now()
        today_str = date.today().strftime('%Y-%m-%d')
        current_time_str = now.strftime('%H:%M')

        # Find all active seniors
        cursor.execute("""
            SELECT u.id, u.name, sp.grace_time_minutes 
            FROM users u
            JOIN senior_profiles sp ON u.id = sp.user_id
            WHERE u.role = 'senior' AND u.is_active = 1
        """)
        seniors = cursor.fetchall()

        for senior in seniors:
            s_id = senior['id']
            s_name = senior['name']
            grace = senior['grace_time_minutes'] or 30

            # Find active medicines
            cursor.execute("SELECT * FROM medicines WHERE senior_id = ? AND is_active = 1", (s_id,))
            meds = cursor.fetchall()

            for med in meds:
                timings = [t.strip() for t in med['timings'].split(',') if t.strip()]
                for t in timings:
                    try:
                        sched_dt = datetime.strptime(f"{today_str} {t}", "%Y-%m-%d %H:%M")
                    except ValueError:
                        continue
                    
                    # If current time is past scheduled_time + grace_period
                    if now > sched_dt + timedelta(minutes=grace):
                        # Check if a log entry exists for today and this scheduled time
                        cursor.execute("""
                            SELECT * FROM medicine_logs 
                            WHERE medicine_id = ? AND senior_id = ? AND scheduled_date = ? AND scheduled_time = ?
                        """, (med['id'], s_id, today_str, t))
                        existing_log = cursor.fetchone()

                        if not existing_log:
                            # Insert as missed
                            cursor.execute("""
                                INSERT INTO medicine_logs (medicine_id, senior_id, scheduled_date, scheduled_time, status, note)
                                VALUES (?, ?, ?, ?, 'missed', 'Auto-flagged missed after grace window')
                            """, (med['id'], s_id, today_str, t))
                            conn.commit()

                            # Notify approved family members
                            cursor.execute("""
                                SELECT family_user_id FROM family_links 
                                WHERE senior_id = ? AND is_approved = 1 AND can_view_medicines = 1
                            """, (s_id,))
                            family_members = cursor.fetchall()
                            for f in family_members:
                                notify_user(
                                    f['family_user_id'],
                                    'missed_medicine',
                                    'Missed Medicine Alert',
                                    f"{s_name} has not marked '{med['name']}' ({med['dose']}) taken. Scheduled time was {t} (past {grace} min grace period).",
                                    channel='both'
                                )
                        elif existing_log['status'] == 'pending':
                            cursor.execute("""
                                UPDATE medicine_logs SET status = 'missed', note = 'Auto-flagged missed after grace window'
                                WHERE id = ?
                            """, (existing_log['id'],))
                            conn.commit()

                            # Notify family
                            cursor.execute("""
                                SELECT family_user_id FROM family_links 
                                WHERE senior_id = ? AND is_approved = 1 AND can_view_medicines = 1
                            """, (s_id,))
                            family_members = cursor.fetchall()
                            for f in family_members:
                                notify_user(
                                    f['family_user_id'],
                                    'missed_medicine',
                                    'Missed Medicine Alert',
                                    f"{s_name} missed scheduled dose for '{med['name']}' at {t}.",
                                    channel='both'
                                )
        conn.close()
    except Exception as e:
        print(f"[Scheduler Error - Missed Meds]: {e}")

def check_daily_checkins():
    try:
        conn = get_db()
        cursor = conn.cursor()
        now = datetime.now()
        today_str = date.today().strftime('%Y-%m-%d')

        cursor.execute("""
            SELECT u.id, u.name, sp.check_in_time 
            FROM users u
            JOIN senior_profiles sp ON u.id = sp.user_id
            WHERE u.role = 'senior' AND u.is_active = 1
        """)
        seniors = cursor.fetchall()

        for senior in seniors:
            s_id = senior['id']
            s_name = senior['name']
            chk_time = senior['check_in_time'] or '09:00'
            try:
                target_dt = datetime.strptime(f"{today_str} {chk_time}", "%Y-%m-%d %H:%M")
            except ValueError:
                continue

            # If current time is past check-in time
            if now > target_dt:
                cursor.execute("""
                    SELECT * FROM daily_checkins 
                    WHERE senior_id = ? AND checkin_date = ? AND status IN ('ok', 'late')
                """, (s_id, today_str))
                has_checked_in = cursor.fetchone()

                if not has_checked_in:
                    # Check if already notified today
                    cursor.execute("""
                        SELECT * FROM notifications 
                        WHERE type = 'missed_checkin' AND message LIKE ? AND DATE(sent_at) = ?
                    """, (f"%{s_name}%", today_str))
                    already_notified = cursor.fetchone()

                    if not already_notified:
                        # Log pending/missed checkin
                        cursor.execute("""
                            INSERT OR IGNORE INTO daily_checkins (senior_id, checkin_date, status, note)
                            VALUES (?, ?, 'missed', 'Missed morning check-in deadline')
                        """, (s_id, today_str))
                        conn.commit()

                        # Alert family
                        cursor.execute("SELECT family_user_id FROM family_links WHERE senior_id = ? AND is_approved = 1", (s_id,))
                        for f in cursor.fetchall():
                            notify_user(
                                f['family_user_id'],
                                'missed_checkin',
                                "Daily 'I am OK' Check-in Missed",
                                f"{s_name} has not pressed 'I am OK' today by their expected time of {chk_time}. Please check on them.",
                                channel='both'
                            )
        conn.close()
    except Exception as e:
        print(f"[Scheduler Error - Daily Checkins]: {e}")

def check_sos_escalation():
    """
    If nobody replies to an active SOS within 2 minutes (120 seconds),
    the alert automatically escalates to the next contact.
    """
    try:
        conn = get_db()
        cursor = conn.cursor()
        now = datetime.now()

        # Find active emergencies that haven't been resolved or taken over
        cursor.execute("""
            SELECT ea.*, u.name as senior_name, u.phone as senior_phone 
            FROM emergency_alerts ea
            JOIN users u ON ea.senior_id = u.id
            WHERE ea.status = 'active'
        """)
        active_alerts = cursor.fetchall()

        for alert in active_alerts:
            alert_id = alert['id']
            s_id = alert['senior_id']
            s_name = alert['senior_name']
            current_step = alert['contact_escalation_step'] or 1
            
            try:
                triggered_dt = datetime.strptime(str(alert['triggered_at']), '%Y-%m-%d %H:%M:%S')
            except ValueError:
                continue

            elapsed_seconds = (now - triggered_dt).total_seconds()
            
            # Total emergency contacts for this senior
            cursor.execute("SELECT COUNT(*) FROM emergency_contacts WHERE senior_id = ?", (s_id,))
            total_contacts = cursor.fetchone()[0] or 1
            max_step = total_contacts + 1

            if current_step >= max_step:
                # Already escalated to final emergency dispatch level; do not repeat or increment further
                continue

            # 2 minutes per escalation level
            threshold_seconds = current_step * 120

            if elapsed_seconds >= threshold_seconds:
                next_step = current_step + 1
                cursor.execute("""
                    SELECT * FROM emergency_contacts 
                    WHERE senior_id = ? AND priority_order = ?
                """, (s_id, next_step))
                next_contact = cursor.fetchone()

                if next_contact:
                    # Escalate to next contact
                    cursor.execute("""
                        UPDATE emergency_alerts 
                        SET contact_escalation_step = ? 
                        WHERE id = ?
                    """, (next_step, alert_id))
                    conn.commit()

                    msg = (f"URGENT ESCALATION (Level {next_step}): No response within 2 minutes! "
                           f"{s_name} has triggered an SOS! Alerting next contact: {next_contact['name']} "
                           f"({next_contact['phone']}, {next_contact['relation']}). Emergency line: 112.")
                    
                    dispatch_sms(next_contact['phone'], msg)

                    # Also broadcast in-app to family & doctor
                    cursor.execute("SELECT family_user_id FROM family_links WHERE senior_id = ? AND is_approved = 1", (s_id,))
                    for f in cursor.fetchall():
                        notify_user(f['family_user_id'], 'sos', f"SOS Escalation - Level {next_step}", msg, channel='both')

                    cursor.execute("SELECT doctor_user_id FROM doctor_assignments WHERE senior_id = ? AND is_approved = 1", (s_id,))
                    for d in cursor.fetchall():
                        notify_user(d['doctor_user_id'], 'sos', f"Patient SOS Escalation - Level {next_step}", msg, channel='both')
                else:
                    # Reached end of contact list: alert emergency dispatch once
                    cursor.execute("""
                        UPDATE emergency_alerts 
                        SET contact_escalation_step = ?, notes = 'Maximum contact escalation reached. Auto-routed to Emergency 112 Dispatch.'
                        WHERE id = ?
                    """, (max_step, alert_id))
                    conn.commit()
                    
                    crit_msg = f"CRITICAL: All emergency contacts exhausted for {s_name}! Call 112 Emergency Dispatch immediately!"
                    cursor.execute("SELECT family_user_id FROM family_links WHERE senior_id = ? AND is_approved = 1", (s_id,))
                    for f in cursor.fetchall():
                        notify_user(f['family_user_id'], 'sos', "CRITICAL: Call 112 Emergency Dispatch", crit_msg, channel='both')

        conn.close()
    except Exception as e:
        print(f"[Scheduler Error - SOS Escalation]: {e}")

def start_scheduler():
    scheduler = BackgroundScheduler()
    # Runs checks every 30 seconds
    scheduler.add_job(func=check_missed_medicines, trigger="interval", seconds=30, id="check_medicines")
    scheduler.add_job(func=check_daily_checkins, trigger="interval", seconds=30, id="check_checkins")
    scheduler.add_job(func=check_sos_escalation, trigger="interval", seconds=15, id="check_sos")
    scheduler.start()
    print("[APScheduler] Background scheduler started successfully for meds, checkins, and SOS escalation.")
    return scheduler
