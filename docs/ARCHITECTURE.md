# AGEWELL Architecture & Technical Specification

## 1. Overview
**AGEWELL Senior Independence Portal** is a web-based clinical and family oversight platform designed to assist senior citizens in maintaining independent, dignified, and safe living while remaining actively connected with designated family members, physicians, and emergency services.

---

## 2. System Architecture

```
+-------------------------------------------------------------------------+
|                                Client UI                                |
|    - High Contrast Senior Dashboard       - Family Oversight Portal     |
|    - Doctor Clinical Roster               - System Administration       |
+------------------------------------+------------------------------------+
                                     |
                             HTTP / JSON / AJAX
                                     |
+------------------------------------v------------------------------------+
|                         Flask Application Core                          |
|  - Role-Based Access Control (RBAC)       - Session Security Engine     |
|  - Real-Time Messaging & Chat             - Twilio/Mock SMS Dispatcher  |
+------------------------------------+------------------------------------+
                                     |
                    +----------------+----------------+
                    |                                 |
+-------------------v-------------+     +-------------v-------------------+
|       SQLite Data Layer         |     |       APScheduler Engine        |
|  - 15 Relational Tables         |     |  - Medication 30-min Check      |
|  - Foreign Key Enforcements     |     |  - Daily Check-in Auto-Grace    |
|  - Audit Log Trails             |     |  - 2-Min SOS Escalation Cascade |
+---------------------------------+     +---------------------------------+
```

---

## 3. Role-Based Access Control (RBAC)

The application defines 4 distinct security roles:

| Role | Permissions & Access Scope |
|---|---|
| **Senior** | One-touch "I am OK" check-in, medication adherence confirmations, SOS emergency broadcast, physician appointment management, approved contact chat. |
| **Family** | Senior status monitoring, real-time alert feed (missed meds, SOS, check-ins), direct phone & messaging channel, emergency response acknowledgement. |
| **Doctor** | Patient clinical roster, medication prescription schedule creation, visit booking, emergency response, clinical care messaging. |
| **Admin** | System audit logs, user management, full emergency alert review, database health diagnostics. |

---

## 4. Database Schema (15 Tables)

The SQLite database (`agewell.db`) consists of 15 relational tables:
1. `users`: Credentials, names, email, phone, and role.
2. `senior_profiles`: Medical history, blood group, emergency notes, home address.
3. `emergency_contacts`: Ranked contacts (priority 1..N) with relationship tags.
4. `emergency_alerts`: Active, responding, and resolved emergency records with step tracking.
5. `medications`: Prescription schedules, dosages, instructions, and time slots.
6. `medication_logs`: Daily adherence logs (`taken`, `missed`, `pending`) with timestamps.
7. `daily_checkins`: Morning "I am OK" check-in records.
8. `family_links`: Approval-gated relationship mappings between seniors and family members.
9. `doctor_assignments`: Approval-gated assignments connecting doctors to senior patients.
10. `appointments`: Clinical and home visit schedules with clinical outcome notes.
11. `notifications`: In-app alert queue with priority indicators and delivery status.
12. `sms_logs`: Simulated and actual SMS dispatch records with delivery outcomes.
13. `audit_logs`: Immutable security tracking of user logins, role actions, and alert states.
14. `system_settings`: Global portal parameters (grace durations, emergency hotline).
15. `messages`: End-to-end private communication threads between seniors, family, and doctors.
