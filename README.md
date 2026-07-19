# Exam Platform

Generic diagnostic analytics platform for MCQ-based exam prep. Runs mock tests, logs errors by topic, tracks topic mastery over time, and offers an admin panel that ingests questions from PDFs via Claude Sonnet 4.6. Originally built for the Rajasthan Computer Anudeshak exam; retooled to work with any subject.

Live: `https://exam-prep-db.onrender.com`

---

## Stack

- **Web**: Flask 3.x, Jinja2 templates, vanilla JS (no build step)
- **Sessions**: `flask-session` (filesystem backend)
- **Auth**: JWT (HS256) in an HttpOnly cookie, with a users table (bcrypt/scrypt password hashes) and per-user roles (`admin` / `user`)
- **DB**: SQLite locally; **Turso Cloud** (libSQL) in production via a pure-Python HTTP adapter (`turso_patch.py`) that monkey-patches `sqlite3.connect`
- **LLM**: Anthropic Claude Sonnet 4.6 for PDF → question extraction (`ai_anthropic.py`), plus Gemini (2.5-Flash) via the Generative Language REST API for the doubt-chat feature (`ai_utils.py`)
- **Deploy**: Render (`gunicorn wsgi:app`)
- **Tests**: pytest, 43 e2e + adapter + admin + extraction tests

---

## Module layout

```
exam-prep-platform/
├── wsgi.py                # Gunicorn entrypoint: loads turso_patch, imports app
├── app.py                 # create_app() factory + __main__ dev runner
├── config.py              # Env-var-driven Config class
├── db.py                  # get_db(), close_db(), init_db(), schema
├── seed.py                # Seed topics + questions (idempotent)
├── auth.py                # JWT + users table + password hashing + before_request guard
├── turso_patch.py         # sqlite3 -> Turso HTTP adapter (Row, TR, TC, executescript)
│
├── bp_auth.py             # /login, /logout
├── bp_main.py             # /
├── bp_tests.py            # /test/setup, /test/take, /test/finish, /results/<id>
├── bp_analytics.py        # /analytics
├── bp_errorlog.py         # /errorlog
├── bp_api.py              # /api/* (JSON endpoints, including /api/flag_question)
├── bp_doubt.py            # /api/doubt/deep-dive, /api/doubt/chat
├── bp_admin.py            # /admin/* — role='admin' only (flags queue, question CRUD, PDF upload)
├── bp_diag.py             # /diag, /setup/seed — JWT-secret-gated bootstrap tools
├── ai_config.py           # Static AI/notes maps for Gemini doubt-chat
├── ai_utils.py            # Gemini REST API wrapper + notes context lookup
├── ai_anthropic.py        # Claude Sonnet 4.6 PDF → question extraction
│
├── templates/             # Jinja2 templates
│   └── admin/             # Admin panel templates (dashboard, flags, questions, uploads, ...)
├── static/                # script.js (fetch wrapper + UI helpers) + style.css
├── study-notes/           # Markdown corpus consumed by AI doubt engine
├── data/                  # exam_prep.db (dev), flask_session/
└── tests/                 # pytest suite
```

---

## Environment variables

| Variable | Required? | Notes |
|---|---|---|
| `FLASK_SECRET_KEY` | **prod: yes** | 64+ hex chars. Used for Flask session cookie signing. Fail-fast on Render if missing. |
| `JWT_SECRET` | **prod: yes** | 64+ hex chars. Signs the auth JWT. Must be stable across gunicorn workers. |
| `EXAM_ADMIN_USER` | prod: recommended | Used only on first boot when `users` table is empty. |
| `EXAM_ADMIN_PASS` | prod: recommended | Plain-text password; hashed once and stored. Change via `/admin/users` after seed. |
| `ANTHROPIC_API_KEY` | for PDF extraction | Enables the admin panel's PDF → question extraction. Without it, uploads show a clear error. |
| `JWT_EXPIRY_HOURS` | no | Default 24. |
| `COOKIE_SECURE` | no | `1` in prod (default when `RENDER=true`), `0` local. |
| `TURSO_DB_URL` | prod: yes | `libsql://<db>.turso.io`. |
| `TURSO_AUTH_TOKEN` | prod: yes | Turso RW token. |
| `GEMINI_API_KEY` | for doubt-chat | Google Generative Language API key. Required for `/api/doubt/deep-dive` + `/api/doubt/chat`. Missing key → server returns an error-ID; no CLI/binary needed. |
| `GEMINI_MODEL` | no | Override the Gemini model name (default `gemini-2.5-flash`). |

Locally the app boots without any env vars — it prints a warning and generates ephemeral dev secrets each restart. In production (Render sets `RENDER=true`), missing `FLASK_SECRET_KEY` or `JWT_SECRET` is a hard fail.

---

## Local development

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Optional: put real values in a .env file (not tracked)
export FLASK_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
export JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
export EXAM_ADMIN_USER=admin
export EXAM_ADMIN_PASS=your-strong-password

python3 app.py          # dev server on http://localhost:5050
```

The first boot creates `data/exam_prep.db`, applies the schema, seeds ~42 topics + ~208 questions, and inserts your admin user with a hashed password.

To wipe and start over: `rm data/exam_prep.db data/flask_session/*` then restart.

---

## Admin panel

At `/admin/` (role='admin' users only). Sections:

- **Dashboard** — flag/question/user counts + recent open flags
- **Flags queue** — inline actions per flag: **Fix inline** (opens the question editor), **Disable question** (auto-resolves the flag and excludes the question from future tests), **Resolve**, **Dismiss**
- **Questions** — filter by topic/paper/difficulty, edit any field, toggle `disabled`, delete
- **Topics** — CRUD
- **Users** — CRUD, change password, toggle role/active
- **Master prompts** — edit the Claude extraction prompt live; version-tagged; multiple prompts per app for different subjects
- **PDF Uploads** — upload a PDF, pick a topic + prompt, Claude extracts MCQs into strict JSON, admin previews and imports selected questions

**Flag flow** (during a test): users click **⚑ Report issue** below any question → picks a category (data inconsistency / bad LaTeX / typo / wrong answer / other) + optional note → the flag lands in the admin flags queue. Scoring is unaffected.

**Question exclusion**: setting `questions.disabled = 1` (via the flags queue or the question editor) prevents that question from being selected for future tests. Existing test history keeps its references.

---

## Testing

```bash
python3 -m pytest tests/ -q
```

The suite covers:

- `tests/test_auth.py` — login flow, JWT expiry, logout, protected-route redirects, `/api/*` 401s
- `tests/test_routes.py` — every public page returns 200 for a logged-in user
- `tests/test_db.py` — schema, seed data, users table
- `tests/test_turso.py` — mocked Turso adapter (executescript, Row indexing, typed args)
- `tests/test_boot_with_turso.py` — `create_app()` boots cleanly with the Turso patch active

Each test gets an isolated temp DB (see `conftest.py`).

---

## Deployment (Render)

1. **Push to `main`** — Render auto-deploys.
2. **Set env vars once** in the Render dashboard (Environment tab):
   - `FLASK_SECRET_KEY`, `JWT_SECRET`, `EXAM_ADMIN_USER`, `EXAM_ADMIN_PASS`
   - `TURSO_DB_URL`, `TURSO_AUTH_TOKEN`
   - `COOKIE_SECURE=1`
3. **Manual Deploy → Deploy latest commit** — first time only; auto-deploys thereafter.

On first successful boot with an empty `users` table, `EXAM_ADMIN_USER`/`EXAM_ADMIN_PASS` are used to insert a hashed admin. After that seed runs, the env vars are ignored — password changes must go through the DB.

Start command in `render.yaml`:

```
gunicorn wsgi:app -b 0.0.0.0:10000 --timeout 120
```

`wsgi.py` imports `turso_patch` **before** importing `app`, so `sqlite3.connect` is already routed to Turso by the time `create_app()` calls `init_db()`.

---

## Common tasks

**Change the admin password**

```python
python3 -c "
import os
os.environ.setdefault('FLASK_SECRET_KEY','x'); os.environ.setdefault('JWT_SECRET','x')
from app import app
from werkzeug.security import generate_password_hash
with app.app_context():
    from db import get_db
    db = get_db()
    db.execute('UPDATE users SET password_hash=? WHERE username=?',
               (generate_password_hash('new-password'), 'admin'))
    db.commit()
"
```

**Add another user**

```python
db.execute('INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)',
           ('newuser', generate_password_hash('pw'), 'user'))
```

**Reset a stuck test session** (in-browser, if the test UI is unresponsive)

```
GET /test/setup  →  server drops any stale session['test_id'] / session['questions']
```

---

## Turso adapter details

`turso_patch.py` monkey-patches `sqlite3.connect` so any path containing `exam_prep` is routed to the Hrana v2 `/v2/pipeline` REST endpoint. It provides:

- `TR` (connection): `execute`, `executemany`, `executescript`, `commit`, `rollback`, `cursor`, `close`
- `TC` (cursor): `fetchone`, `fetchall`, iteration, `description`, `lastrowid`
- `Row`: `sqlite3.Row`-compatible — supports both `row[0]` and `row['col']`

Params are auto-typed into Hrana's `{"type": "text"|"integer"|"null"|"float"|"blob", "value": ...}` shape. `executescript` splits on `;` while respecting single-quoted strings and `''` escapes.

Limits:
- No connection pooling (each `sqlite3.connect(...)` returns a fresh `TR`; each `execute` is one HTTPS round-trip).
- Multi-statement batches are chunked at 50 requests per pipeline call.
- Transactions are not supported (`commit`/`rollback` are no-ops).

---

## Security notes

Findings from the 2026-07-12 audit; status after the refactor:

- ✅ `JWT_SECRET` and `FLASK_SECRET_KEY` are stable (env-driven, no per-worker/per-restart drift)
- ✅ Passwords hashed (werkzeug scrypt/pbkdf2) — no more plaintext compare
- ✅ Cookie flags: `HttpOnly`, `SameSite=Lax`, `Secure` (in prod), explicit `Path=/`, `Max-Age` tied to JWT expiry
- ✅ JWT `exp` + `iat` validated on every request
- ✅ Single auth gate (`before_request`) — no more decorator/before-request double-check
- ✅ Global 401 handler in `static/script.js` redirects to `/login`
- ✅ XSS: `test.html` question/options/feedback rebuilt with DOM APIs (no more `innerHTML` with DB text)
- ⚠️ **Deferred**: a Turso auth token was previously committed to git history (`migrate_to_turso.py` at `e8907d4`). Rotate in the Turso dashboard, then update `TURSO_AUTH_TOKEN` on Render. Optional: purge the token from history with `git filter-repo`.
- ⚠️ No CSRF token on `/login` POST (single-user, low risk; add `flask-wtf` if multi-user).
- ⚠️ No rate limiting (add `flask-limiter` if exposed publicly).

---

## License

Personal project — no license granted.
