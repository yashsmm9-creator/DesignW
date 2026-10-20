# EduAdapt v7 — Adaptive Learning Platform

EduAdapt is a Flask + SQLite learning platform for the supplied Computer Engineering curriculum. It includes account registration/login, a dashboard, topic-based multiple-choice assessments, result history, targets, reminders, structured topic study guides, bookmarks, completion tracking, progress history, a formula/syntax reference, profile settings, and a restricted supplementary-content manager.

## Run on Windows / VS Code

1. Extract the ZIP and open the `edu_adapt` folder in VS Code.
2. Create and activate a virtual environment:
   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
3. Install dependencies:
   ```powershell
   py -m pip install -r requirements.txt
   ```
4. Start the app:
   ```powershell
   py app.py
   ```
5. Open `http://127.0.0.1:5000`.

macOS/Linux: use `python3 -m venv .venv`, `source .venv/bin/activate`, and `python app.py`.

**Local demo account:** `demo@eduadapt.com` / `Demo@12345`. For real use, register a new account.

## Configuration

- `SECRET_KEY`: set a long random secret in the environment for deployments. If omitted, a local `.secret_key` is created.
- `COOKIE_SECURE=1`: enables Secure session cookies when serving over HTTPS. Do not enable for plain local HTTP.
- `ADMIN_EMAIL=your-account@example.com`: grants the matching account access to `/admin` for adding supplementary notes and topics. Set this before launching the app.
- Password reset: the local development mode displays a short-lived reset link after a reset request. A production deployment must connect an email provider, use HTTPS, disable debug mode, and deliver reset links privately by email. Do not expose reset links to users in production logs/UI.

## Main features

- **Authentication:** password hashes (Werkzeug), password-strength rules, protected routes, logout, temporary login-attempt throttling, safer cookie settings and security response headers.
- **Study guides:** searchable list for all 135 curriculum topics, with topic detail pages organized into introduction, objectives, prerequisites, theory, definitions, formula/rule guidance, worked method, syntax/notation, comparisons, applications, mistakes, exam prompts, practice, quick revision and flashcards. Guides are a structured learning scaffold; they do not claim to replace the official syllabus or a prescribed textbook. Check the detailed page's content notice for scope limitations.
- **Practice:** questions are selected by topic; maths topics include numerical/formula questions where available, and programming/DSA topics use algorithm/code-oriented prompts. Results and explanations are stored per user.
- **Personal learning tools:** bookmarks, topic completion state, progress page, study targets, reminders and profile display name.
- **Content manager:** set `ADMIN_EMAIL`; administrators can add a subject/topic and supplementary section text without editing core route code.
- **Formula reference:** compact mathematics, complexity, Python and machine-learning metric reference.
- **Accessibility and motion:** responsive interface, existing motion effects and reduced-motion support for the added notes detail cards.

## Tests

Install requirements first, then run:

```powershell
py -m unittest discover -s tests -v
```

The smoke tests cover protected routes, registration/login, topic notes, bookmarks, topic completion and quiz-result persistence.

## Important deployment notes

This is a local educational project, not a production security certification. Before public deployment, configure HTTPS and a secret key, add CSRF protection to all state-changing forms, use a server-side rate limiter (not only a session counter), configure private email delivery for password resets and verification, add migrations/backups, and review/expand question and note content against the official course syllabus. No AI API key is required; an AI assistant is not connected in this build.


## UI refresh (v8)
The interface now uses an original, high-contrast tech editorial style inspired by modern student technology communities: dark landing hero, lime accent, bold typography, subtle motion, responsive cards, and a coordinated dashboard palette. EduAdapt branding and application routes remain intact.

## Email-verified sign-up, simple login, and WhatsApp study reminders

### Sign-up and login
- During registration, the student enters name, email, WhatsApp number, and password.
- EduAdapt emails a six-digit verification code. The account is **not created until the code is verified**. The code expires after five minutes and is limited to five attempts.
- The OTP is never displayed in the webpage or stored in the signup session as plain text. If SMTP is missing or email delivery fails, registration stops and shows a configuration/delivery error; no account is created.
- After verification, login asks for **email and password only**; no OTP or phone number is requested at login.

Configure email delivery with environment variables before launching:
- `SMTP_HOST` (for Gmail, `smtp.gmail.com`)
- `SMTP_PORT` (usually `587`)
- `SMTP_USERNAME` (email account used to send)
- `SMTP_PASSWORD` (for Gmail, use an App Password rather than your normal account password)
- `SMTP_FROM_EMAIL` (optional; defaults to `SMTP_USERNAME`)
- `SMTP_USE_TLS=1` (default; enables STARTTLS)

### WhatsApp daily target reminders
- Students enter their WhatsApp-capable mobile number during sign-up and choose a daily reminder time when adding each target.
- **Setup on Windows:** copy `.env.example` to `.env` in the `edu_adapt` folder, then fill in your real Twilio values. Install dependencies with `py -m pip install -r requirements.txt`, then start with `py app.py` (not Flask's development CLI).
- **Twilio Sandbox test:** in Twilio Console, activate the WhatsApp Sandbox and send its displayed `join ...` phrase from your recipient WhatsApp account. The recipient must join the sandbox before messages can arrive. Use the sender number shown in your own Console; the example sender may differ.
- The terminal logs explain missing credentials and now include Twilio's API error response when a send fails. Never paste your auth token into chat or commit `.env` to Git.
- When the target is still incomplete at that time, the server checks every minute and sends one WhatsApp reminder per target per day. Marking today's target complete prevents that day's reminder.
- Messages are sent through the Twilio WhatsApp API. Configure `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and `TWILIO_WHATSAPP_FROM` (for example, `whatsapp:+14155238886` for the Twilio Sandbox sender). The recipient is normalized to `whatsapp:+<countrycode><number>`.
- For sandbox testing, the recipient must first join your Twilio WhatsApp Sandbox. For real production messages, complete WhatsApp sender/business setup and follow WhatsApp's template rules; messages sent outside the customer-service window may require an approved template. Twilio usage may incur charges.
- The WhatsApp scheduler runs when the app is launched with `py app.py`; keep the app/server running. For a multi-worker or hosted deployment, run a single dedicated scheduler/worker instead of starting a scheduler in every web worker.
- WhatsApp reminders are server-side; the website does not need to remain open in the student's browser, but the EduAdapt server must be running.

Use HTTPS and a strong `SECRET_KEY` in production. Keep SMTP and Twilio credentials out of source control. The demo account (`demo@eduadapt.com` / `Demo@12345`) remains available for local UI demonstrations; it is pre-seeded and does not need registration OTP.
