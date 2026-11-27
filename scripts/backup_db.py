#!/usr/bin/env python3
"""
AGEWELL Automated Database Backup Utility
Performs online atomic backup of agewell.db using SQLite backup API.
"""

import os
import sqlite3
import sys
from datetime import datetime

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SOURCE_DB = os.path.join(BASE_DIR, 'agewell.db')
BACKUP_DIR = os.path.join(BASE_DIR, 'backups')

def perform_backup(target_dir=BACKUP_DIR):
    os.makedirs(target_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_filename = f"agewell_backup_{timestamp}.db"
    dest_path = os.path.join(target_dir, backup_filename)

    if not os.path.exists(SOURCE_DB):
        raise FileNotFoundError(f"Source database not found: {SOURCE_DB}")

    src_conn = sqlite3.connect(SOURCE_DB)
    dest_conn = sqlite3.connect(dest_path)

    try:
        with dest_conn:
            src_conn.backup(dest_conn)
        print(f"[Backup Success] Created: {dest_path}")
        return dest_path
    finally:
        dest_conn.close()
        src_conn.close()

if __name__ == '__main__':
    try:
        perform_backup()
    except Exception as e:
        print(f"[Backup Error] {e}", file=sys.stderr)
        sys.exit(1)
