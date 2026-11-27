#!/usr/bin/env python3
"""
AGEWELL Developer Seed Utility
Populates sample seniors, medications, appointments, and contacts for local testing.
"""

import sys
import os

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, BASE_DIR)

from models import get_db, init_db

def seed_sample_records():
    init_db()
    conn = get_db()
    cursor = conn.cursor()

    # Check if senior user exists
    cursor.execute("SELECT id FROM users WHERE email = 'senior@agewell.com'")
    senior = cursor.fetchone()

    if senior:
        s_id = senior['id']
        # Ensure sample medicine exists
        cursor.execute("SELECT id FROM medicines WHERE senior_id = ? AND name = 'Vitamin D3'", (s_id,))
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO medicines (senior_id, name, dose, timings, instructions, is_active)
                VALUES (?, 'Vitamin D3', '1000 IU', '09:00', 'Take after breakfast', 1)
            """, (s_id,))
            print("[Seeder] Added sample medicine: Vitamin D3")

        # Ensure sample appointment exists
        cursor.execute("SELECT id FROM appointments WHERE senior_id = ? AND title = 'Annual Wellness Checkup'", (s_id,))
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO appointments (senior_id, doctor_user_id, appointment_date, appointment_time, title, status)
                VALUES (?, 3, '2026-12-05', '10:30', 'Annual Wellness Checkup', 'scheduled')
            """, (s_id,))
            print("[Seeder] Added sample appointment: Annual Wellness Checkup")

    conn.commit()
    conn.close()
    print("[Seeder Success] Database seeded successfully.")

if __name__ == '__main__':
    seed_sample_records()
