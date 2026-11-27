# Contributing to AGEWELL Senior Independence Portal

Thank you for your interest in contributing to **AGEWELL**! Our goal is to empower senior citizens with dignified independence, safety monitoring, and seamless family/doctor oversight.

---

## 1. Development Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/ARIPRAKASH32/AGEWELL.git
   cd AGEWELL
   ```

2. **Set up Python Virtual Environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Initialize Database & Seed Data:**
   ```bash
   python -c "import models; models.init_db()"
   python scripts/seed_data.py
   ```

4. **Start Local Development Server:**
   ```bash
   python app.py
   ```
   Open [http://localhost:5000](http://localhost:5000) in your web browser.

---

## 2. Git Branching & Commit Conventions

We follow Conventional Commits formatting:
- `feat(...)`: New user-facing feature or enhancement
- `fix(...)`: Bug fix (e.g. SOS escalation, UI rendering)
- `test(...)`: Automated tests (Pytest)
- `ci(...)`: GitHub Actions, Docker, deployment configs
- `docs(...)`: Documentation, architecture, protocols
- `perf(...)`: Database query indexes, caching, optimization
- `sec(...)`: Security headers, sanitization, access controls

### Branch Naming
- `feat/feature-name`
- `fix/bug-description`
- `test/suite-name`

---

## 3. Running Automated Tests

Before submitting a pull request, run the full Pytest suite:
```bash
pytest -v
```
All unit and integration tests must pass cleanly.

---

## 4. Submitting a Pull Request
1. Fork or branch from `main`.
2. Keep PRs focused, atomic, and well-documented.
3. Ensure all tests pass.
4. Submit your Pull Request targeting `main`.
