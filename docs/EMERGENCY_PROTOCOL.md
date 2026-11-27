# AGEWELL Emergency Protocol & Escalation Specification

## 1. Safety Principles
The primary mission of AGEWELL is preventing unmonitored medical emergencies or prolonged distress. The emergency engine runs background cron tasks managed via `APScheduler` executing every 30 to 60 seconds.

---

## 2. Emergency SOS Escalation Cascade

When a senior triggers the emergency SOS (either through the portal or voice/hardware button):

```
[ Senior Presses SOS ]
        |
        v
[ Alert Created (Status: ACTIVE, Step: 1) ]
        |
        +---> Instant siren blare & audio alert on Senior UI
        +---> Broadcast SMS & In-app alert to Priority #1 Emergency Contact
        |
        v
[ 2-Minute Grace Countdown ]
        |
        +---> [ Someone clicks "I AM RESPONDING" ]
        |               |
        |               v
        |     [ Status: RESPONDING ]
        |     - Escalation loop stops immediately
        |     - Audio sirens silenced
        |     - Responder details shown in emerald card on senior screen
        |
        +---> [ No response within 120 seconds ]
                        |
                        v
              [ Escalate to Priority #2 ]
              - SMS sent to next contact
              - Contact step incremented (max bound: total_contacts + 1)
              - Repeats every 2 minutes until primary emergency dispatch (112)
```

---

## 3. Daily "I AM OK" Safety Window

- **Schedule**: Every morning between 08:00 AM and 10:00 AM.
- **Grace Period**: Seniors are encouraged to press the prominent "I AM OK" button upon waking.
- **Auto-Escalation**: If no check-in is logged by 10:30 AM (past the 30-minute grace period), an automated alert is broadcast to family members to initiate a wellness check.

---

## 4. Medication Adherence Grace Policy

- Each medication has scheduled dosage times (e.g., 08:00 AM, 12:00 PM, 08:00 PM).
- A **30-minute grace window** is granted after the scheduled time.
- If the senior has not confirmed the dosage within 30 minutes, the scheduler flags a `Missed Medicine Alert` and notifies the designated caregiver.
