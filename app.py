"""EduAdapt - adaptive study platform for Computer Engineering students.

Run:  python app.py   (or: py app.py on Windows)  ->  http://127.0.0.1:5000
"""
import os
import secrets
import sqlite3
import re
import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta, date

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

from flask import (Flask, render_template, redirect, url_for, request, flash,
                   jsonify, abort, session, send_from_directory)
from flask_login import (LoginManager, UserMixin, login_user, login_required,
                         logout_user, current_user)
from werkzeug.security import generate_password_hash, check_password_hash

from curriculum_data import CURRICULUM, DESCRIPTIONS, QUESTIONS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE_DIR, 'database.db')


def _load_secret_key():
    """Use SECRET_KEY from the environment, else a random key persisted locally."""
    env = os.environ.get('SECRET_KEY')
    if env:
        return env
    path = os.path.join(BASE_DIR, '.secret_key')
    try:
        with open(path) as f:
            key = f.read().strip()
            if key:
                return key
    except OSError:
        pass
    key = secrets.token_hex(32)
    try:
        with open(path, 'w') as f:
            f.write(key)
    except OSError:
        pass
    return key


app = Flask(__name__)
app.config['SECRET_KEY'] = _load_secret_key()
app.config['SESSION_COOKIE_HTTPONLY'] = True
cookie_secure = os.environ.get('COOKIE_SECURE', '0') == '1'
app.config['SESSION_COOKIE_SAMESITE'] = 'None' if cookie_secure else 'Lax'
app.config['SESSION_COOKIE_SECURE'] = cookie_secure
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024
app.config['ADMIN_EMAIL'] = os.environ.get('ADMIN_EMAIL', '').strip().lower()
app.config['REMEMBER_COOKIE_HTTPONLY'] = True
login_manager = LoginManager(app)
login_manager.login_view = 'login'

@app.after_request
def add_security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    if request.endpoint in ('dashboard','notes','note_detail','bookmarks','progress','profile','admin'):
        response.headers.setdefault('Cache-Control','no-store, private')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
    response.headers.setdefault('Content-Security-Policy', "default-src 'self' https: data:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com data:; script-src 'self' 'unsafe-inline'; img-src 'self' data: https:")
    if request.is_secure:
        response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
    return response


DEMO_EMAIL, DEMO_PASSWORD = 'demo@eduadapt.com', 'Demo@12345'


# --------------------------------------------------------------------------- DB
def get_db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c


def ensure_column(c, table, col, definition):
    cols = [r['name'] for r in c.execute(f'PRAGMA table_info({table})').fetchall()]
    if col not in cols:
        c.execute(f'ALTER TABLE {table} ADD COLUMN {col} {definition}')


SCHEMA = '''
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,password TEXT NOT NULL,created_at TEXT NOT NULL,phone TEXT);
CREATE TABLE IF NOT EXISTS subjects(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT UNIQUE NOT NULL,description TEXT);
CREATE TABLE IF NOT EXISTS topics(id INTEGER PRIMARY KEY AUTOINCREMENT,subject_id INTEGER NOT NULL,name TEXT NOT NULL,UNIQUE(subject_id,name),FOREIGN KEY(subject_id) REFERENCES subjects(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS questions(id INTEGER PRIMARY KEY AUTOINCREMENT,topic_id INTEGER NOT NULL,question TEXT NOT NULL,option_a TEXT NOT NULL,option_b TEXT NOT NULL,option_c TEXT NOT NULL,option_d TEXT NOT NULL,correct TEXT NOT NULL,explanation TEXT,UNIQUE(topic_id,question),FOREIGN KEY(topic_id) REFERENCES topics(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS videos(id INTEGER PRIMARY KEY AUTOINCREMENT,topic_id INTEGER NOT NULL,title TEXT NOT NULL,description TEXT,url TEXT NOT NULL,difficulty TEXT NOT NULL,FOREIGN KEY(topic_id) REFERENCES topics(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS targets(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,title TEXT NOT NULL,subject_id INTEGER,deadline TEXT NOT NULL,daily_minutes INTEGER DEFAULT 60,progress INTEGER DEFAULT 0,created_at TEXT NOT NULL,daily_reminder_time TEXT DEFAULT '18:00',FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(subject_id) REFERENCES subjects(id) ON DELETE SET NULL);
CREATE TABLE IF NOT EXISTS reminders(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,title TEXT NOT NULL,remind_at TEXT NOT NULL,enabled INTEGER DEFAULT 1,interval_minutes INTEGER DEFAULT 60,last_fired_at TEXT,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS daily_target_completions(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,target_id INTEGER NOT NULL,completed_on TEXT NOT NULL,completed_at TEXT NOT NULL,UNIQUE(user_id,target_id,completed_on),FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(target_id) REFERENCES targets(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS whatsapp_reminder_sends(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,target_id INTEGER NOT NULL,sent_on TEXT NOT NULL,sent_at TEXT NOT NULL,UNIQUE(user_id,target_id,sent_on),FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(target_id) REFERENCES targets(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS test_attempts(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,topic_id INTEGER NOT NULL,score INTEGER NOT NULL,total INTEGER NOT NULL,percentage REAL NOT NULL,level TEXT NOT NULL,time_taken INTEGER DEFAULT 0,attempted_at TEXT NOT NULL,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(topic_id) REFERENCES topics(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS attempt_answers(id INTEGER PRIMARY KEY AUTOINCREMENT,attempt_id INTEGER NOT NULL,question_id INTEGER NOT NULL,answer TEXT,is_correct INTEGER NOT NULL,FOREIGN KEY(attempt_id) REFERENCES test_attempts(id) ON DELETE CASCADE,FOREIGN KEY(question_id) REFERENCES questions(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS bookmarks(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,topic_id INTEGER NOT NULL,created_at TEXT NOT NULL,UNIQUE(user_id,topic_id),FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(topic_id) REFERENCES topics(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS topic_progress(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,topic_id INTEGER NOT NULL,completed INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL,UNIQUE(user_id,topic_id),FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(topic_id) REFERENCES topics(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS learning_events(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,topic_id INTEGER NOT NULL,minutes INTEGER NOT NULL DEFAULT 0,occurred_at TEXT NOT NULL,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(topic_id) REFERENCES topics(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS admin_content(id INTEGER PRIMARY KEY AUTOINCREMENT,subject_name TEXT NOT NULL,topic_name TEXT NOT NULL,section_title TEXT NOT NULL,body TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS password_resets(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,token_hash TEXT UNIQUE NOT NULL,expires_at TEXT NOT NULL,used INTEGER NOT NULL DEFAULT 0,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
'''


def init_db():
    c = get_db()
    c.executescript(SCHEMA)
    # migrations for databases created by older versions
    ensure_column(c, 'reminders', 'interval_minutes', 'INTEGER DEFAULT 60')
    ensure_column(c, 'reminders', 'last_fired_at', 'TEXT')
    ensure_column(c, 'users', 'phone', 'TEXT')
    ensure_column(c, 'targets', 'daily_reminder_time', "TEXT DEFAULT '18:00'")
    ensure_column(c, 'test_attempts', 'time_taken', 'INTEGER DEFAULT 0')
    seed_curriculum(c)
    seed_demo_user(c)
    c.execute('UPDATE users SET phone=? WHERE email=? AND (phone IS NULL OR phone=\'\')', ('+919999999999', DEMO_EMAIL))
    c.commit()
    c.close()


def normalize_phone(value):
    """Normalize a phone number; 10-digit Indian numbers get the +91 prefix."""
    raw = ''.join(ch for ch in (value or '').strip() if ch.isdigit() or ch == '+')
    if raw.startswith('00'):
        raw = '+' + raw[2:]
    if raw.startswith('+'):
        digits = raw[1:]
    else:
        digits = raw
        if len(digits) == 10:
            digits = '91' + digits
    if not digits.isdigit() or not 10 <= len(digits) <= 15:
        return None
    return '+' + digits


def _is_production():
    return os.environ.get('FLASK_ENV', 'development').lower() == 'production'


def send_email_otp(email, otp):
    """Send sign-up verification through SMTP. Never expose OTP in the web UI."""
    host = os.environ.get('SMTP_HOST', '').strip()
    port = int(os.environ.get('SMTP_PORT', '587'))
    username = os.environ.get('SMTP_USERNAME', '').strip()
    password = os.environ.get('SMTP_PASSWORD', '').strip()
    sender = os.environ.get('SMTP_FROM_EMAIL', username).strip()
    if not (host and sender):
        app.logger.error('Sign-up email OTP unavailable: SMTP settings are not configured.')
        return False, False
    try:
        message = EmailMessage()
        message['Subject'] = 'Verify your EduAdapt account'
        message['From'] = sender
        message['To'] = email
        message.set_content(f'Your EduAdapt verification code is {otp}. It expires in 5 minutes. If you did not request this, ignore this email.')
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.ehlo()
            if os.environ.get('SMTP_USE_TLS', '1').lower() not in ('0', 'false', 'no'):
                smtp.starttls()
                smtp.ehlo()
            if username and password:
                smtp.login(username, password)
            smtp.send_message(message)
        return True, False
    except Exception:
        app.logger.exception('Unable to send sign-up verification email')
        return False, False


def send_whatsapp_message(phone, message_text):
    """Send a WhatsApp message through a Twilio WhatsApp-enabled sender."""
    sid = os.environ.get('TWILIO_ACCOUNT_SID', '').strip()
    token = os.environ.get('TWILIO_AUTH_TOKEN', '').strip()
    sender = os.environ.get('TWILIO_WHATSAPP_FROM', '').strip()
    if not (sid and token and sender):
        app.logger.warning('WhatsApp reminder not sent: configure Twilio WhatsApp credentials.')
        return False
    try:
        import base64
        from urllib.parse import urlencode
        from urllib.request import Request, urlopen
        to = phone if phone.startswith('whatsapp:') else f'whatsapp:{phone}'
        if not sender.startswith('whatsapp:'):
            sender = f'whatsapp:{sender}'
        url = f'https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json'
        body = urlencode({'To': to, 'From': sender, 'Body': message_text}).encode()
        auth = base64.b64encode(f'{sid}:{token}'.encode()).decode()
        req = Request(url, data=body, headers={'Authorization': f'Basic {auth}',
                                                'Content-Type': 'application/x-www-form-urlencoded'})
        with urlopen(req, timeout=12) as response:
            return 200 <= response.status < 300
    except Exception as exc:
        # Twilio's response body usually contains a useful error code (e.g.
        # sandbox recipient not joined, invalid sender, or authentication failure).
        try:
            from urllib.error import HTTPError
            if isinstance(exc, HTTPError):
                details = exc.read().decode('utf-8', errors='replace')
                app.logger.error('Twilio WhatsApp API returned HTTP %s: %s', exc.code, details)
            else:
                app.logger.exception('Unable to send WhatsApp reminder: %s', exc)
        except Exception:
            app.logger.exception('Unable to send WhatsApp reminder')
        return False


def dispatch_due_whatsapp_reminders():
    """Send each unfinished target's WhatsApp reminder at most once per local day."""
    now = datetime.now()
    today = now.date().isoformat()
    clock = now.strftime('%H:%M')
    if not all(os.environ.get(k, '').strip() for k in ('TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_WHATSAPP_FROM')):
        app.logger.warning('WhatsApp scheduler ran but Twilio is not configured. Add credentials to edu_adapt/.env.')
        return
    c = get_db()
    query = ("SELECT t.id target_id,t.user_id,t.title,t.daily_minutes,t.daily_reminder_time,u.name,u.phone "
             "FROM targets t JOIN users u ON u.id=t.user_id "
             "LEFT JOIN daily_target_completions d ON d.target_id=t.id AND d.user_id=t.user_id AND d.completed_on=? "
             "LEFT JOIN whatsapp_reminder_sends w ON w.target_id=t.id AND w.user_id=t.user_id AND w.sent_on=? "
             "WHERE t.progress<100 AND d.id IS NULL AND w.id IS NULL "
             "AND t.daily_reminder_time<=? AND u.phone IS NOT NULL AND u.phone<>''")
    rows = c.execute(query, (today, today, clock)).fetchall()
    c.close()
    for row in rows:
        text = (f"Hi {row['name']}! Your EduAdapt daily study target is still pending: "
                f"{row['title']} ({row['daily_minutes']} minutes). Open EduAdapt and mark it complete when done.")
        if send_whatsapp_message(row['phone'], text):
            conn = get_db()
            try:
                conn.execute('INSERT OR IGNORE INTO whatsapp_reminder_sends(user_id,target_id,sent_on,sent_at) VALUES(?,?,?,?)',
                             (row['user_id'], row['target_id'], today, now.isoformat(timespec='seconds')))
                conn.commit()
            finally:
                conn.close()


def seed_demo_user(c):
    if not c.execute('SELECT 1 FROM users WHERE email=?', (DEMO_EMAIL,)).fetchone():
        c.execute('INSERT INTO users(name,email,password,created_at,phone) VALUES(?,?,?,?,?)',
                  ('Demo Student', DEMO_EMAIL, generate_password_hash(DEMO_PASSWORD),
                   datetime.now().isoformat(timespec='seconds'), '+919999999999'))


def topic_questions(topic):
    """Prefer concrete subject-aware questions for maths and coding topics."""
    t = topic.lower()
    # Concrete, answer-checkable examples take priority over generic topic prompts.
    if 'matrices' in t or 'determinant' in t:
        bank = [
            ("For A = [[1, 2], [3, 4]], what is det(A)?", "-2", "2", "10", "-10", 'A', "For a 2×2 matrix [[a,b],[c,d]], det(A)=ad−bc=1×4−2×3=−2."),
            ("When can a square matrix have an inverse?", "Only when every entry is positive", "When its determinant is non-zero", "Only when it is diagonal", "When its determinant is zero", 'B', "A square matrix is invertible exactly when its determinant is non-zero."),
            ("If A is 2×3 and B is 3×4, what is the size of AB?", "3×3", "4×2", "2×4", "3×4", 'C', "The inner dimensions match (3), and the product uses the outer dimensions: 2×4."),
            ("Which operation is generally not commutative for matrices?", "Scalar multiplication", "Adding the zero matrix", "Multiplying by identity", "Matrix multiplication", 'D', "In general AB is not equal to BA."),
        ]
        return bank + QUESTIONS[topic][4:10]
    if 'eigenvalue' in t:
        bank = [
            ("For a square matrix A, an eigenpair satisfies:", "Av = λv for a non-zero vector v", "A+v = λ", "Aλ = v for every v", "det(A)=v", 'A', "An eigenvector v is non-zero and satisfies Av=λv."),
            ("To find eigenvalues of A, solve:", "Aλ=0", "det(A−λI)=0", "A+λI=I", "det(A)=λ for every matrix", 'B', "Eigenvalues are roots of the characteristic equation det(A−λI)=0."),
            ("Why must an eigenvector be non-zero?", "So every matrix is invertible", "To make λ always positive", "The zero vector satisfies Av=λv for every λ and gives no useful direction", "To make A symmetric", 'C', "The zero vector is excluded because it trivially satisfies the equation for all λ."),
            ("If Av=5v for non-zero v, the eigenvalue is:", "0", "1", "v", "5", 'D', "Comparing Av=λv with Av=5v gives λ=5."),
        ]
        return bank + QUESTIONS[topic][4:10]
    if 'limits' in t or 'continuity' in t or 'differential calculus' in t:
        bank = [
            ("Using the power rule, d(x³)/dx equals:", "3x²", "x²", "3x", "x⁴/4", 'A', "The power rule gives d(xⁿ)/dx = n xⁿ⁻¹, so the derivative is 3x²."),
            ("A function is continuous at x=a when:", "Its derivative is zero", "The limit exists and equals f(a)", "f(a) must be positive", "Its graph is a straight line", 'B', "Continuity requires lim(x→a) f(x)=f(a), with the function defined at a."),
            ("For a differentiable function, the derivative at a point represents:", "The area under the whole curve", "The y-intercept", "The instantaneous rate of change/slope of the tangent", "Always the maximum value", 'C', "The derivative is the instantaneous rate of change and tangent slope."),
            ("The limit of (x²−1)/(x−1) as x approaches 1 is:", "0", "1", "Undefined after simplification", "2", 'D', "Factor x²−1=(x−1)(x+1), cancel for x≠1, then the limit is 2."),
        ]
        return bank + QUESTIONS[topic][4:10]
    if 'set theory' in t or 'relations' in t:
        bank = [
            ("If A={1,2} and B={2,3}, then A∩B is:", "{2}", "{1,2,3}", "{1,3}", "∅", 'A', "Intersection contains elements common to both sets, here only 2."),
            ("If |A|=3 and |B|=4, then |A×B| is:", "7", "12", "4", "1", 'B', "The Cartesian product has |A|×|B| ordered pairs: 3×4=12."),
            ("A relation on set A is reflexive if:", "It is symmetric only", "No element relates to itself", "(a,a) belongs to R for every a in A", "It contains exactly one pair", 'C', "Reflexivity requires every element to be related to itself."),
            ("The empty set is a subset of:", "Only itself", "No non-empty set", "Only finite sets", "Every set", 'D', "The empty set has no counterexample element, so it is a subset of every set."),
        ]
        return bank + QUESTIONS[topic][4:10]
    if 'linear algebra' in t or 'linear equations' in t:
        bank = [
            ("A system of linear equations has a unique solution when its equations are:", "Consistent and independent", "Always inconsistent", "All identical", "Missing all variables", 'A', "A consistent system with independent equations has a unique solution."),
            ("For two equations in two unknowns, a non-zero determinant of the coefficient matrix indicates:", "No solution", "A unique solution", "Infinitely many solutions", "The equations are nonlinear", 'B', "A non-zero determinant means the coefficient matrix is invertible."),
            ("Which is a valid elementary row operation?", "Squaring one row", "Deleting a variable without justification", "Adding a multiple of one row to another row", "Changing only one entry arbitrarily", 'C', "Elementary row operations preserve the solution set."),
            ("Gaussian elimination aims to transform the augmented matrix into:", "A random matrix", "A matrix with no pivots", "A diagonal matrix in every case", "An echelon form suitable for back substitution", 'D', "Elimination creates echelon form; solve by back substitution."),
        ]
        return bank + QUESTIONS[topic][4:10]
    if any(k in t for k in ('matrix', 'determinant', 'eigenvalue', 'linear equation', 'calculus', 'limit', 'differential', 'set theory', 'propositional logic', 'counting', 'graph theory', 'recurrence')):
        bank = [
            (f"For {topic}, which approach is most useful when solving a new problem?", "Identify the definition/formula and apply it to the given values", "Guess without checking the conditions", "Ignore the given information", "Change the question", 'A', "Start from the relevant mathematical definition, then apply it carefully."),
            (f"Which step helps verify a result in {topic}?", "Skip calculations", "Check the result against the original conditions", "Always round every value immediately", "Use unrelated values", 'B', "Checking against the original conditions helps catch arithmetic and reasoning errors."),
            (f"Why is {topic} useful to computer engineering students?", "It removes the need for algorithms", "It is only for memorisation", "It supports modelling, computation and logical problem solving", "It replaces all programming languages", 'C', "Mathematical reasoning supports modelling and computational problem solving."),
            (f"When working on a {topic} exercise, what should you do first?", "Write a random answer", "Ignore variable definitions", "Start with the longest calculation", "Identify known values, unknowns and applicable rules", 'D', "Listing knowns and unknowns clarifies which rule or formula applies."),
        ]
        return bank + QUESTIONS[topic][4:10]
    if 'stack' in t or 'queue' in t:
        bank = [
            ("A stack follows which order?", "FIFO", "LIFO", "Random order", "Sorted order", 'B', "A stack is last-in, first-out; the most recent push is popped first."),
            ("Which operation removes the front item from a queue?", "push", "peek", "dequeue", "enqueue", 'C', "Dequeue removes an item from the front; enqueue inserts at the rear."),
            ("After push(4), push(7), pop() on an empty stack initially, what is popped?", "4", "An error before any push", "Nothing", "7", 'D', "The most recently pushed value, 7, is on top and is popped first."),
            ("A queue is commonly used to implement:", "Breadth-first search", "Binary search", "In-order traversal recursion only", "Quick sort partitioning only", 'A', "Breadth-first search processes nodes in first-in, first-out order."),
        ]
        return bank + QUESTIONS[topic][4:10]
    if 'binary search' in t:
        bank = [
            ("Binary search requires the input array to be:", "Sorted", "Circular", "All unique by definition", "Stored in a linked list only", 'A', "Binary search eliminates half the remaining search interval each step and requires sorted order."),
            ("The time complexity of binary search on a sorted array is:", "O(n²)", "O(log n)", "O(n log n)", "O(1) in every case", 'B', "The search interval halves at each step, giving logarithmic time."),
            ("For a sorted array of 16 elements, binary search needs at most about how many halvings to isolate one item?", "16", "8", "4", "2", 'C', "log₂(16)=4 halvings isolate a single candidate."),
            ("If the target is smaller than the middle value in ascending order, continue in the:", "Right half", "Both halves", "Same interval without change", "Left half", 'D', "All values in the right half are at least the middle value, so search left."),
        ]
        return bank + QUESTIONS[topic][4:10]
    if any(k in t for k in ('array', 'linked list', 'stack', 'queue', 'tree', 'heap', 'hash', 'graph', 'algorithm', 'programming', 'pointer', 'sorting', 'searching', 'dynamic programming', 'backtracking', 'greedy', 'recursion', 'stl')):
        bank = [
            (f"In a coding problem about {topic}, what should you define before implementation?", "Input, expected output and constraints", "Only variable names", "The screen colour", "A random test result", 'A', "Clear inputs, outputs and constraints guide a correct implementation."),
            (f"Which is a good way to test an implementation of {topic}?", "Run it once with one normal input", "Use normal, boundary and edge-case inputs", "Avoid testing empty inputs", "Assume it always works", 'B', "Normal, boundary and edge cases expose different classes of bugs."),
            (f"When analysing {topic}, time complexity describes:", "The monitor refresh rate", "The number of comments", "How the running time grows with input size", "The file extension", 'C', "Time complexity describes how an algorithm's running time scales with input size."),
            (f"What is the best next step if a {topic} solution gives a wrong answer?", "Delete the tests", "Ignore the failing case", "Increase the number of print statements only", "Trace a small failing input and inspect each operation", 'D', "Tracing a small failing input makes logic errors easier to locate."),
        ]
        return bank + QUESTIONS[topic][4:10]
    return QUESTIONS[topic]


def seed_curriculum(c):
    for sname, topics in CURRICULUM.items():
        c.execute('INSERT OR IGNORE INTO subjects(name,description) VALUES(?,?)',
                  (sname, DESCRIPTIONS.get(sname, '')))
        sid = c.execute('SELECT id FROM subjects WHERE name=?', (sname,)).fetchone()['id']
        for topic in topics:
            c.execute('INSERT OR IGNORE INTO topics(subject_id,name) VALUES(?,?)', (sid, topic))
            tid = c.execute('SELECT id FROM topics WHERE subject_id=? AND name=?',
                            (sid, topic)).fetchone()['id']
            for q in topic_questions(topic):
                c.execute('INSERT OR IGNORE INTO questions(topic_id,question,option_a,option_b,'
                          'option_c,option_d,correct,explanation) VALUES(?,?,?,?,?,?,?,?)', (tid, *q))
            search = topic.replace(' ', '+')
            resources = [
                ('Start: ' + topic, 'Foundation lesson and key concepts.',
                 'https://www.youtube.com/results?search_query=' + search + '+basics', 'Beginner'),
                ('Practice: ' + topic, 'Examples, problem solving and implementation practice.',
                 'https://www.youtube.com/results?search_query=' + search + '+tutorial+examples', 'Intermediate'),
                ('Advanced: ' + topic, 'Advanced problems, applications and exam preparation.',
                 'https://www.youtube.com/results?search_query=' + search + '+advanced+lecture', 'Advanced'),
            ]
            for title, desc, url, diff in resources:
                if not c.execute('SELECT 1 FROM videos WHERE topic_id=? AND title=?',
                                 (tid, title)).fetchone():
                    c.execute('INSERT INTO videos(topic_id,title,description,url,difficulty) '
                              'VALUES(?,?,?,?,?)', (tid, title, desc, url, diff))


# ------------------------------------------------------------------------- Auth
class User(UserMixin):
    def __init__(self, row):
        self.id = row['id']
        self.name = row['name']
        self.email = row['email']
        self.phone = row['phone'] if 'phone' in row.keys() else None


@login_manager.user_loader
def load_user(uid):
    c = get_db()
    r = c.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    c.close()
    return User(r) if r else None


# ---------------------------------------------------------------------- Helpers
def safe_int(value, default, lo=None, hi=None):
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    if lo is not None:
        n = max(lo, n)
    if hi is not None:
        n = min(hi, n)
    return n


def parse_dt(value):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def level_for_score(p):
    return ('Beginner' if p < 40 else 'Basic' if p < 60 else
            'Intermediate' if p < 75 else 'Advanced' if p < 90 else 'Expert')


def level_class(level):
    return (level or '').lower()


def days_left(deadline):
    try:
        return (date.fromisoformat(deadline) - date.today()).days
    except (TypeError, ValueError):
        return None


def fmt_dt(value):
    d = parse_dt(value)
    return d.strftime('%d %b %Y, %H:%M') if d else (value or '')


def fmt_duration(seconds):
    seconds = int(seconds or 0)
    return f'{seconds // 60:02d}:{seconds % 60:02d}'


def next_occurrence(reminder, now=None):
    """Next time a recurring reminder will ring (>= now)."""
    now = now or datetime.now()
    start = parse_dt(reminder['remind_at'])
    if not start:
        return None
    if now <= start:
        return start
    interval = max(1, int(reminder['interval_minutes'] or 60))
    steps = -(-int((now - start).total_seconds()) // (interval * 60))  # ceil
    return start + timedelta(minutes=steps * interval)


def study_streak(c, user_id):
    rows = c.execute('SELECT DISTINCT substr(attempted_at,1,10) d FROM test_attempts '
                     'WHERE user_id=? ORDER BY d DESC', (user_id,)).fetchall()
    days = {r['d'] for r in rows}
    cur, streak = date.today(), 0
    if cur.isoformat() not in days:          # a streak survives until the day ends
        cur -= timedelta(days=1)
    while cur.isoformat() in days:
        streak += 1
        cur -= timedelta(days=1)
    return streak


def topic_best(c, user_id):
    rows = c.execute('SELECT topic_id,MAX(percentage) best,COUNT(*) n FROM test_attempts '
                     'WHERE user_id=? GROUP BY topic_id', (user_id,)).fetchall()
    return {r['topic_id']: {'best': r['best'], 'n': r['n']} for r in rows}


def adaptive_videos(c, tid, level):
    order = {'Beginner': ['Beginner'], 'Basic': ['Beginner', 'Intermediate'],
             'Intermediate': ['Intermediate', 'Beginner'],
             'Advanced': ['Intermediate', 'Advanced'],
             'Expert': ['Advanced', 'Intermediate']}.get(level, ['Beginner', 'Intermediate'])
    ph = ','.join('?' * len(order))
    case = ' '.join(f"WHEN '{x}' THEN {i}" for i, x in enumerate(order))
    return c.execute(f'SELECT * FROM videos WHERE topic_id=? AND difficulty IN ({ph}) '
                     f'ORDER BY CASE difficulty {case} ELSE 99 END,id', (tid, *order)).fetchall()


app.jinja_env.globals.update(level_class=level_class, days_left=days_left)
app.jinja_env.filters['dt'] = fmt_dt
app.jinja_env.filters['duration'] = fmt_duration


@app.context_processor
def inject_now():
    return {'current_year': datetime.now().year}


# ------------------------------------------------------------------ Public pages
@app.route('/')
def index():
    c = get_db()
    stats = {
        'subjects': c.execute('SELECT COUNT(*) n FROM subjects').fetchone()['n'],
        'topics': c.execute('SELECT COUNT(*) n FROM topics').fetchone()['n'],
        'questions': c.execute('SELECT COUNT(*) n FROM questions').fetchone()['n'],
    }
    c.close()
    return render_template('index.html', stats=stats)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        stage = request.form.get('stage', 'details')
        if stage == 'verify_email_otp':
            pending = session.get('pending_signup')
            submitted = ''.join(ch for ch in request.form.get('otp', '') if ch.isdigit())
            if not pending or datetime.now().timestamp() > pending.get('expires_at', 0):
                session.pop('pending_signup', None)
                flash('Your verification code expired. Please register again.', 'error')
                return redirect(url_for('register'))
            if not submitted or not check_password_hash(pending.get('otp_hash', ''), submitted):
                pending['attempts'] = int(pending.get('attempts', 0)) + 1
                if pending['attempts'] >= 5:
                    session.pop('pending_signup', None)
                    flash('Too many incorrect codes. Please register again.', 'error')
                    return redirect(url_for('register'))
                session['pending_signup'] = pending
                flash('Incorrect verification code. Please try again.', 'error')
                return render_template('register.html', form={'name': pending['name'], 'email': pending['email'],
                                                               'phone': pending['phone']}, otp_stage=True)
            c = get_db()
            try:
                c.execute('INSERT INTO users(name,email,password,created_at,phone) VALUES(?,?,?,?,?)',
                          (pending['name'], pending['email'], pending['password_hash'],
                           datetime.now().isoformat(timespec='seconds'), pending['phone']))
                c.commit()
            except sqlite3.IntegrityError:
                session.pop('pending_signup', None)
                flash('That email is already registered. Please log in.', 'error')
                return redirect(url_for('login'))
            finally:
                c.close()
            session.pop('pending_signup', None)
            flash('Email verified and account created. You can now log in with your email and password.', 'success')
            return redirect(url_for('login'))

        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        pw = request.form.get('password', '')
        phone = normalize_phone(request.form.get('phone', ''))
        confirm = request.form.get('confirm', '')
        error = None
        if not name or not email or not pw or not phone:
            error = 'Please fill in all fields and enter a valid WhatsApp mobile number.'
        elif '@' not in email or '.' not in email.split('@')[-1]:
            error = 'Enter a valid email address.'
        elif len(pw) < 8 or not any(ch.islower() for ch in pw) or not any(ch.isupper() for ch in pw) or not any(ch.isdigit() for ch in pw) or not any(not ch.isalnum() for ch in pw):
            error = 'Use 8+ characters with uppercase, lowercase, number and symbol.'
        elif pw != confirm:
            error = 'Passwords do not match.'
        if error:
            flash(error, 'error')
            return render_template('register.html', form=request.form), 400
        c = get_db()
        existing = c.execute('SELECT 1 FROM users WHERE email=?', (email,)).fetchone()
        c.close()
        if existing:
            flash('That email is already registered. Please log in.', 'error')
            return render_template('register.html', form=request.form), 409
        otp = f'{secrets.randbelow(1000000):06d}'
        sent, _ = send_email_otp(email, otp)
        # Local development fallback requested for this project: show the OTP on the page
        # when SMTP is unavailable. In production, fail closed and never expose it.
        development_otp = None
        if not sent:
            if _is_production():
                flash('We could not send your OTP email. Please try again later or contact the administrator.', 'error')
                return render_template('register.html', form=request.form), 503
            development_otp = otp
            app.logger.warning('Development signup OTP generated for %s because SMTP delivery is unavailable.', email)
        session['pending_signup'] = {
            'name': name, 'email': email, 'phone': phone,
            'password_hash': generate_password_hash(pw),
            'otp_hash': generate_password_hash(otp),
            'expires_at': datetime.now().timestamp() + 300, 'attempts': 0
        }
        if sent:
            flash('A verification code was sent to your email. Your account will be created after verification.', 'success')
        else:
            flash('Development mode: email is not configured, so use the test OTP shown below. Your account will be created only after verification.', 'warning')
        return render_template('register.html', form={'name': name, 'email': email, 'phone': phone},
                               otp_stage=True, development_otp=development_otp)
    return render_template('register.html', form={}, otp_stage=False)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        now = int(datetime.now().timestamp())
        attempts = [t for t in session.get('login_attempts', []) if now - int(t) < 300]
        if len(attempts) >= 5:
            flash('Too many login attempts. Please wait 5 minutes before trying again.', 'error')
            return render_template('login.html', email=request.form.get('email', '').strip().lower()), 429
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        c = get_db()
        user_row = c.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        c.close()
        if user_row and check_password_hash(user_row['password'], password):
            session.pop('login_attempts', None)
            session.pop('pending_signup', None)
            login_user(User(user_row), fresh=True)
            session.permanent = True
            return redirect(url_for('dashboard'))
        attempts.append(now)
        session['login_attempts'] = attempts
        flash('Invalid email or password.', 'error')
        return render_template('login.html', email=email), 401
    return render_template('login.html', email='')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


# --------------------------------------------------------------------- Dashboard
@app.route('/dashboard')
@login_required
def dashboard():
    uid = current_user.id
    c = get_db()
    targets = c.execute('SELECT targets.*,subjects.name subject_name FROM targets LEFT JOIN subjects '
                        'ON subjects.id=targets.subject_id WHERE user_id=? AND progress<100 '
                        'ORDER BY deadline LIMIT 4', (uid,)).fetchall()
    active_targets = c.execute('SELECT COUNT(*) n FROM targets WHERE user_id=? AND progress<100',
                               (uid,)).fetchone()['n']
    attempts = c.execute('SELECT test_attempts.*,topics.name topic_name,subjects.name subject_name '
                         'FROM test_attempts JOIN topics ON topics.id=topic_id '
                         'JOIN subjects ON subjects.id=topics.subject_id WHERE user_id=? '
                         'ORDER BY attempted_at DESC LIMIT 6', (uid,)).fetchall()
    reminders = c.execute('SELECT * FROM reminders WHERE user_id=? AND enabled=1', (uid,)).fetchall()
    stats = c.execute('SELECT COUNT(*) tests,COALESCE(AVG(percentage),0) avg_score '
                      'FROM test_attempts WHERE user_id=?', (uid,)).fetchone()
    stats = dict(stats)
    stats['completed_topics'] = c.execute('SELECT COUNT(*) n FROM topic_progress WHERE user_id=? AND completed=1',(uid,)).fetchone()['n']
    stats['learning_minutes'] = c.execute('SELECT COALESCE(SUM(minutes),0) n FROM learning_events WHERE user_id=?',(uid,)).fetchone()['n']
    focus = c.execute('SELECT topics.id topic_id,topics.name topic_name,subjects.name subject_name,'
                      'AVG(percentage) avg_score FROM test_attempts JOIN topics ON topics.id=topic_id '
                      'JOIN subjects ON subjects.id=topics.subject_id WHERE user_id=? '
                      'GROUP BY topic_id HAVING avg_score<75 ORDER BY avg_score LIMIT 4',
                      (uid,)).fetchall()
    streak = study_streak(c, uid)
    c.close()
    upcoming = sorted(((next_occurrence(r), r) for r in reminders if next_occurrence(r)),
                      key=lambda x: x[0])
    next_reminder = upcoming[0] if upcoming else None
    hour = datetime.now().hour
    greeting = 'Good morning' if hour < 12 else 'Good afternoon' if hour < 18 else 'Good evening'
    return render_template('dashboard.html', targets=targets, attempts=attempts, stats=stats,
                           active_targets=active_targets, next_reminder=next_reminder,
                           focus=focus, streak=streak, greeting=greeting)


# ----------------------------------------------------------------------- Targets
@app.route('/targets', methods=['GET', 'POST'])
@login_required
def targets():
    c = get_db()
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        sid = safe_int(request.form.get('subject_id'), None)
        deadline = request.form.get('deadline', '')
        mins = safe_int(request.form.get('daily_minutes'), 60, 5, 600)
        reminder_time = request.form.get('daily_reminder_time', '18:00')
        if not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', reminder_time):
            reminder_time = '18:00'
        try:
            date.fromisoformat(deadline)
            valid_date = True
        except ValueError:
            valid_date = False
        if title and valid_date:
            c.execute('INSERT INTO targets(user_id,title,subject_id,deadline,daily_minutes,created_at,daily_reminder_time) '
                      'VALUES(?,?,?,?,?,?,?)', (current_user.id, title, sid, deadline, mins,
                                              datetime.now().isoformat(timespec='seconds'), reminder_time))
            c.commit()
            flash('Target added.', 'success')
        else:
            flash('Please enter a title and a valid deadline.', 'error')
        c.close()
        return redirect(url_for('targets'))
    rows = c.execute('''SELECT targets.*,subjects.name subject_name,
                     CASE WHEN daily_target_completions.id IS NULL THEN 0 ELSE 1 END AS completed_today
                     FROM targets LEFT JOIN subjects ON subjects.id=targets.subject_id
                     LEFT JOIN daily_target_completions ON daily_target_completions.target_id=targets.id
                       AND daily_target_completions.user_id=targets.user_id AND daily_target_completions.completed_on=?
                     WHERE targets.user_id=? ORDER BY targets.progress>=100,targets.deadline''',
                     (date.today().isoformat(), current_user.id)).fetchall()
    subjects_ = c.execute('SELECT * FROM subjects ORDER BY id').fetchall()
    c.close()
    return render_template('targets.html', targets=rows, subjects=subjects_,
                           today=date.today().isoformat())


@app.post('/targets/<int:target_id>/progress')
@login_required
def target_progress(target_id):
    p = safe_int(request.form.get('progress'), 0, 0, 100)
    c = get_db()
    c.execute('UPDATE targets SET progress=? WHERE id=? AND user_id=?', (p, target_id, current_user.id))
    c.commit()
    c.close()
    return redirect(url_for('targets'))


@app.post('/targets/<int:target_id>/delete')
@login_required
def delete_target(target_id):
    c = get_db()
    c.execute('DELETE FROM targets WHERE id=? AND user_id=?', (target_id, current_user.id))
    c.commit()
    c.close()
    flash('Target deleted.', 'info')
    return redirect(url_for('targets'))


@app.get('/api/daily-targets')
@login_required
def api_daily_targets():
    today = date.today().isoformat()
    c = get_db()
    rows = c.execute("""SELECT t.id,t.title,t.daily_minutes,t.daily_reminder_time,t.progress,
        CASE WHEN d.id IS NULL THEN 0 ELSE 1 END AS completed_today
        FROM targets t LEFT JOIN daily_target_completions d
          ON d.target_id=t.id AND d.user_id=t.user_id AND d.completed_on=?
        WHERE t.user_id=? AND t.progress<100 ORDER BY t.id""", (today, current_user.id)).fetchall()
    c.close()
    return jsonify([dict(r) for r in rows])


@app.post('/targets/<int:target_id>/complete-today')
@login_required
def complete_daily_target(target_id):
    today = date.today().isoformat()
    c = get_db()
    owned = c.execute('SELECT id FROM targets WHERE id=? AND user_id=?',
                      (target_id, current_user.id)).fetchone()
    if not owned:
        c.close()
        abort(404)
    c.execute('INSERT OR IGNORE INTO daily_target_completions(user_id,target_id,completed_on,completed_at) VALUES(?,?,?,?)',
              (current_user.id, target_id, today, datetime.now().isoformat(timespec='seconds')))
    c.commit()
    c.close()
    return jsonify(ok=True, completed_on=today)


# --------------------------------------------------------------------- Reminders
@app.route('/reminders')
@login_required
def reminders():
    c = get_db()
    rows = c.execute('SELECT * FROM reminders WHERE user_id=? ORDER BY remind_at',
                     (current_user.id,)).fetchall()
    c.close()
    items = [(r, next_occurrence(r)) for r in rows]
    now_local = datetime.now().replace(second=0, microsecond=0, minute=(datetime.now().minute // 5) * 5)
    return render_template('reminders.html', items=items,
                           default_start=(now_local + timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M'))


@app.post('/reminders/add')
@login_required
def add_reminder():
    title = request.form.get('title', '').strip() or 'Study Reminder'
    at = request.form.get('remind_at', '')
    interval = safe_int(request.form.get('interval_minutes'), 60, 1, 10080)
    if not parse_dt(at):
        flash('Choose a valid start date and time.', 'error')
        return redirect(url_for('reminders'))
    c = get_db()
    c.execute('INSERT INTO reminders(user_id,title,remind_at,enabled,interval_minutes,last_fired_at) '
              'VALUES(?,?,?,1,?,NULL)', (current_user.id, title, at, interval))
    c.commit()
    c.close()
    flash('Recurring reminder created.', 'success')
    return redirect(url_for('reminders'))


@app.post('/reminders/<int:reminder_id>/delete')
@login_required
def delete_reminder(reminder_id):
    c = get_db()
    c.execute('DELETE FROM reminders WHERE id=? AND user_id=?', (reminder_id, current_user.id))
    c.commit()
    c.close()
    flash('Reminder deleted.', 'info')
    return redirect(url_for('reminders'))


@app.route('/api/reminders')
@login_required
def api_reminders():
    c = get_db()
    rows = c.execute('SELECT id,title,remind_at,interval_minutes,last_fired_at FROM reminders '
                     'WHERE user_id=? AND enabled=1 ORDER BY remind_at', (current_user.id,)).fetchall()
    c.close()
    now, out = datetime.now(), []
    for r in rows:
        item = dict(r)
        try:
            start = datetime.fromisoformat(r['remind_at'])
            interval = max(1, int(r['interval_minutes'] or 60))
            last = datetime.fromisoformat(r['last_fired_at']) if r['last_fired_at'] else None
            if now >= start:
                n = int((now - start).total_seconds() // 60 // interval)
                due_at = start + timedelta(minutes=n * interval)
                item['due'] = last is None or last < due_at
                item['due_at'] = due_at.isoformat()
            else:
                item['due'], item['due_at'] = False, start.isoformat()
        except Exception:
            item['due'], item['due_at'] = False, None
        out.append(item)
    return jsonify(out)


@app.post('/api/reminders/<int:reminder_id>/fired')
@login_required
def reminder_fired(reminder_id):
    c = get_db()
    c.execute('UPDATE reminders SET last_fired_at=? WHERE id=? AND user_id=?',
              (datetime.now().isoformat(timespec='seconds'), reminder_id, current_user.id))
    c.commit()
    c.close()
    return jsonify(ok=True)


# ------------------------------------------------------------ Password recovery
@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        c = get_db(); user = c.execute('SELECT id FROM users WHERE email=?', (email,)).fetchone()
        # Always show the same general response to avoid account enumeration.
        message = 'If that account exists, a password-reset link has been prepared.'
        if user:
            token = secrets.token_urlsafe(32)
            token_hash = __import__('hashlib').sha256(token.encode()).hexdigest()
            expires = (datetime.now() + timedelta(minutes=30)).isoformat(timespec='seconds')
            c.execute('INSERT INTO password_resets(user_id,token_hash,expires_at,used) VALUES(?,?,?,0)', (user['id'], token_hash, expires))
            c.commit()
            # Local-only delivery helper. Production must send this link via verified email.
            if app.debug or os.environ.get('RESET_DELIVERY') == 'console':
                flash(message + ' Local development reset link: ' + url_for('reset_password', token=token, _external=False), 'success')
        c.close()
        if not user or not (app.debug or os.environ.get('RESET_DELIVERY') == 'console'):
            flash(message, 'success')
        return redirect(url_for('forgot_password'))
    return render_template('forgot_password.html')

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    token_hash = __import__('hashlib').sha256(token.encode()).hexdigest()
    c = get_db(); reset = c.execute('SELECT * FROM password_resets WHERE token_hash=? AND used=0', (token_hash,)).fetchone()
    if not reset or not parse_dt(reset['expires_at']) or parse_dt(reset['expires_at']) < datetime.now():
        c.close(); flash('This reset link is invalid or expired. Request a new one.', 'error'); return redirect(url_for('forgot_password'))
    if request.method == 'POST':
        pw = request.form.get('password', ''); confirm = request.form.get('confirm', '')
        valid = len(pw) >= 8 and any(ch.islower() for ch in pw) and any(ch.isupper() for ch in pw) and any(ch.isdigit() for ch in pw) and any(not ch.isalnum() for ch in pw)
        if not valid or pw != confirm:
            c.close(); flash('Use 8+ characters with uppercase, lowercase, number and symbol; both passwords must match.', 'error'); return render_template('reset_password.html', token=token), 400
        c.execute('UPDATE users SET password=? WHERE id=?', (generate_password_hash(pw), reset['user_id']))
        c.execute('UPDATE password_resets SET used=1 WHERE user_id=?', (reset['user_id'],))
        c.commit(); c.close(); flash('Password reset. You can now log in.', 'success'); return redirect(url_for('login'))
    c.close(); return render_template('reset_password.html', token=token)

# ------------------------------------------------------------ Notes & study tools

def build_note(topic, subject):
    """Create a structured, student-friendly study guide adapted to the subject family.
    These are scaffolded learning notes, not a claim that every university syllabus is covered.
    """
    sl, tl = subject.lower(), topic.lower()
    math = any(k in sl for k in ('mathematics','calculus','algebra')) or any(k in tl for k in ('matrix','calculus','equation','probability','statistics','set theory','logic','graph theory','recurrence','limit','derivative','integral'))
    code = any(k in sl for k in ('programming','data structure','algorithm','full stack','software development')) or any(k in tl for k in ('array','linked list','stack','queue','tree','sorting','searching','recursion','algorithm','pointer','function','loop','class','inheritance','dynamic programming'))
    ml = any(k in sl for k in ('machine learning','deep learning','data mining','data exploration'))
    if math:
        theory = [f'{topic} is studied by identifying the mathematical objects involved, stating the applicable rule, and applying it carefully to the given values.', 'Write down known values and the quantity to find before calculating.', 'Check assumptions, domain restrictions, units and dimensions. Keep exact values until the final step when possible.']
        definitions = [f'{topic}: the set of ideas and methods used to represent, reason about, and solve problems in this area.', 'Variable: a symbol representing a value that may be known or unknown.', 'Identity/theorem: a statement that holds under its stated conditions.']
        formulas = ['Choose the formula only after checking its conditions.', 'Show substitutions explicitly, then simplify one step at a time.', 'Verify by substitution, an alternate method, a graph, or a boundary case when possible.']
        worked = f'Worked-method example for {topic}: (1) list the given values; (2) identify the relevant definition or formula from your course; (3) substitute the values; (4) simplify line by line; (5) check that the result satisfies the original conditions. The exact formula depends on the specific subtopic and your prescribed syllabus.'
        practice = [f'Easy: state the main definition used in {topic}.', f'Medium: solve a standard textbook problem on {topic}, showing every step.', f'Hard: solve a multi-step problem on {topic} and verify the result using a second method.']
        quick = ['State the rule before using it.', 'Check all conditions and restrictions.', 'Show intermediate steps and verify the answer.']
    elif code:
        theory = [f'{topic} is best understood through its purpose, operations, representation, and constraints.', 'Identify inputs, expected outputs and edge cases before implementation.', 'Trace a small example by hand, then implement and test it. Compare the time and extra space used as input size grows.']
        definitions = [f'{topic}: a programming or computing concept used to represent data, solve a task, or organize system behaviour.', 'Algorithm: a finite, ordered set of steps for solving a problem.', 'Edge case: an unusual but valid input such as an empty collection, a single item, duplicates, or a boundary value.']
        formulas = ['Time complexity describes how operation count grows with input size n.', 'Space complexity describes extra memory growth with input size n.', 'Common growth rates: O(1), O(log n), O(n), O(n log n), O(n²). Select the bound that matches the actual algorithm; do not assume one without analysing loops/recursion.']
        worked = f'Worked implementation method for {topic}: (1) define input and output; (2) write pseudocode; (3) dry-run a small input in a trace table; (4) implement using the language required by your course; (5) test normal, empty, duplicate and boundary cases; (6) state time and space complexity with justification.'
        practice = [f'Easy: explain the purpose and core operation of {topic}.', f'Medium: write pseudocode or code for a basic operation in {topic}.', f'Hard: analyse edge cases and derive time/space complexity for a solution involving {topic}.']
        quick = ['Understand the representation and supported operations.', 'Dry-run before coding; test edge cases.', 'Explain correctness and complexity.']
    elif ml:
        theory = [f'{topic} is part of the machine-learning workflow: define the task, inspect data, prepare features, train a model, and evaluate on data not used for fitting.', 'Keep training and test data separate to avoid leakage. Fit preprocessing steps only on the training set.', 'Choose evaluation metrics that match the problem and class balance; compare against a simple baseline.']
        definitions = ['Feature: an input variable used by a model.', 'Label/target: the value a supervised model learns to predict.', 'Overfitting: strong training performance but weaker generalization to unseen examples.']
        formulas = ['Regression MSE = (1/n) Σ(yᵢ − ŷᵢ)².', 'Accuracy = (TP + TN)/(TP + TN + FP + FN), when classification accuracy is appropriate.', 'Precision = TP/(TP+FP); Recall = TP/(TP+FN). Handle zero denominators and consider class imbalance.']
        worked = f'Worked workflow for {topic}: (1) define the target; (2) inspect missing values, types and distributions; (3) split train/test; (4) fit preprocessing on training data only; (5) train a baseline and candidate model; (6) evaluate with an appropriate metric; (7) inspect errors and document limitations.'
        practice = [f'Easy: define {topic} and give one use case.', f'Medium: describe preprocessing and a suitable evaluation metric for a {topic} task.', f'Hard: design a leakage-safe experiment for {topic} and justify the metric and baseline.']
        quick = ['Split before fitting preprocessing.', 'Use metrics aligned with the task.', 'Compare against a baseline and inspect errors.']
    else:
        theory = [f'{topic} is a core area of {subject}. Begin with terminology and the purpose of the concept, then understand the components and how they interact.', 'Relate each abstract concept to a diagram, example, or real engineering scenario.', 'Compare alternatives by their assumptions, strengths, limitations and typical failure modes.']
        definitions = [f'{topic}: a subject area concerned with the principles, methods and practical applications described in this chapter.', 'System/component: a part that contributes to a larger process or architecture.', 'Trade-off: a choice in which improving one property may affect another.']
        formulas = ['No single universal formula applies to every topic in this chapter. Use formulas specified by your lecturer or course notes and define every symbol before substituting values.', 'For numerical questions, include units, assumptions, intermediate steps and a reasonableness check.']
        worked = f'Worked study example for {topic}: (1) state the problem or use case; (2) identify the relevant components and terms; (3) draw a labelled flow/architecture if applicable; (4) explain the sequence; (5) compare an alternative; (6) note one limitation and one practical application.'
        practice = [f'Easy: define {topic} and list its main components.', f'Medium: explain how {topic} works using a labelled example or diagram.', f'Hard: compare two approaches related to {topic} and justify which fits a given scenario.']
        quick = ['Know the definitions and key components.', 'Explain the flow using an example.', 'Remember use cases, limitations and comparisons.']
    return {'topic':topic,'subject':subject,'intro':f'This study guide introduces {topic} in the context of {subject}. Use it alongside your lecturer-provided syllabus and prescribed textbook.', 'objectives':[f'Explain the main ideas behind {topic}.','Use relevant terminology correctly.','Apply the concept to a worked example and answer practice questions.'], 'prerequisites':['Read the topic title and course outline.','Review prerequisite concepts identified by your lecturer.','Keep a notebook for unfamiliar symbols and terms.'], 'theory':theory,'definitions':definitions,'key_concepts':theory,'formulas':formulas,'worked':worked,'syntax':['Use the notation, programming language, or conventions required by your course.','For code, keep input/output contracts explicit and test examples.'], 'code':('Use this pseudocode template: define input → validate constraints → apply the core operation → return/output the result → test edge cases.' if code else 'For this non-code topic, write a numbered solution or process flow and label each step.'), 'comparisons':['Compare purpose, assumptions, complexity/cost, strengths, limitations and appropriate use cases.','Use a small table when comparing two related methods.'], 'advantages':['Provides a structured way to reason about the topic.','Can be applied to textbook exercises and practical problems.'], 'limitations':['This generated guide is a revision scaffold; it is not a substitute for your official syllabus or complete prescribed textbook.','Exact formulas, language syntax and assessment scope can vary by course.'], 'applications':[f'Connect {topic} to a real problem in {subject}.','Look for one industry or software example and explain why the concept is useful.'], 'mistakes':['Memorising a rule without knowing when it applies.','Skipping assumptions, units, input constraints or edge cases.','Accepting an answer without checking it.'], 'exam':[f'Define {topic} and explain its importance.','Explain the core process with a labelled example.','Discuss advantages, limitations and applications.'], 'practice':practice,'quick':quick,'flashcards':[('What is the main purpose of '+topic+'?','Explain the problem it addresses and one use case.'),('What should be checked before applying '+topic+'?','Definitions, assumptions, constraints and expected result.'),('How can you test your understanding?','Explain a worked example and solve a new practice problem.') ]}

@app.route('/notes/<int:topic_id>')
@login_required
def note_detail(topic_id):
    c=get_db()
    topic=c.execute('SELECT topics.*,subjects.name subject_name FROM topics JOIN subjects ON subjects.id=topics.subject_id WHERE topics.id=?',(topic_id,)).fetchone()
    if not topic:
        c.close(); abort(404)
    note=build_note(topic['name'],topic['subject_name'])
    extras=c.execute('SELECT section_title,body FROM admin_content WHERE lower(subject_name)=lower(?) AND lower(topic_name)=lower(?) ORDER BY id',(topic['subject_name'],topic['name'])).fetchall()
    bookmarked=bool(c.execute('SELECT 1 FROM bookmarks WHERE user_id=? AND topic_id=?',(current_user.id,topic_id)).fetchone())
    progress_row=c.execute('SELECT completed FROM topic_progress WHERE user_id=? AND topic_id=?',(current_user.id,topic_id)).fetchone()
    c.close()
    return render_template('note_detail.html',topic=topic,note=note,extras=extras,bookmarked=bookmarked,completed=bool(progress_row and progress_row['completed']))

@app.post('/notes/<int:topic_id>/bookmark')
@login_required
def toggle_bookmark(topic_id):
    c=get_db()
    if not c.execute('SELECT 1 FROM topics WHERE id=?',(topic_id,)).fetchone():
        c.close(); abort(404)
    existing=c.execute('SELECT id FROM bookmarks WHERE user_id=? AND topic_id=?',(current_user.id,topic_id)).fetchone()
    if existing:
        c.execute('DELETE FROM bookmarks WHERE id=?',(existing['id'],)); flash('Bookmark removed.','success')
    else:
        c.execute('INSERT OR IGNORE INTO bookmarks(user_id,topic_id,created_at) VALUES(?,?,?)',(current_user.id,topic_id,datetime.now().isoformat(timespec='seconds'))); flash('Topic saved to bookmarks.','success')
    c.commit(); c.close(); return redirect(url_for('note_detail',topic_id=topic_id))

@app.post('/notes/<int:topic_id>/complete')
@login_required
def toggle_topic_complete(topic_id):
    c=get_db()
    if not c.execute('SELECT 1 FROM topics WHERE id=?',(topic_id,)).fetchone():
        c.close(); abort(404)
    row=c.execute('SELECT completed FROM topic_progress WHERE user_id=? AND topic_id=?',(current_user.id,topic_id)).fetchone()
    completed=0 if row and row['completed'] else 1
    c.execute('INSERT INTO topic_progress(user_id,topic_id,completed,updated_at) VALUES(?,?,?,?) ON CONFLICT(user_id,topic_id) DO UPDATE SET completed=excluded.completed,updated_at=excluded.updated_at',(current_user.id,topic_id,completed,datetime.now().isoformat(timespec='seconds')))
    if completed: c.execute('INSERT INTO learning_events(user_id,topic_id,minutes,occurred_at) VALUES(?,?,?,?)',(current_user.id,topic_id,5,datetime.now().isoformat(timespec='seconds')))
    c.commit(); c.close(); flash('Topic marked complete.' if completed else 'Topic moved back to revision.','success'); return redirect(url_for('note_detail',topic_id=topic_id))

@app.route('/bookmarks')
@login_required
def bookmarks():
    c=get_db(); rows=c.execute('SELECT topics.id topic_id,topics.name topic_name,subjects.name subject_name,bookmarks.created_at FROM bookmarks JOIN topics ON topics.id=bookmarks.topic_id JOIN subjects ON subjects.id=topics.subject_id WHERE bookmarks.user_id=? ORDER BY bookmarks.created_at DESC',(current_user.id,)).fetchall(); c.close()
    return render_template('bookmarks.html',items=rows)

@app.route('/formula-reference')
@login_required
def formula_reference():
    return render_template('formula_reference.html')

@app.route('/profile',methods=['GET','POST'])
@login_required
def profile():
    if request.method=='POST':
        name=request.form.get('name','').strip()
        phone=normalize_phone(request.form.get('phone',''))
        if not name or len(name)>80:
            flash('Name must contain 1–80 characters.','error')
        elif not phone:
            flash('Enter a valid mobile number.','error')
        else:
            c=get_db(); c.execute('UPDATE users SET name=?,phone=? WHERE id=?',(name,phone,current_user.id)); c.commit(); c.close(); flash('Profile and mobile number updated. Your next login will use OTP verification on this number.','success'); return redirect(url_for('profile'))
    return render_template('profile.html')

@app.route('/admin',methods=['GET','POST'])
@login_required
def admin():
    # Local-development content manager. Enable only with ADMIN_EMAIL configured.
    if not os.environ.get('ADMIN_EMAIL') or current_user.email != os.environ.get('ADMIN_EMAIL','').strip().lower():
        abort(403)
    if request.method=='POST':
        subject=request.form.get('subject','').strip(); topic=request.form.get('topic','').strip(); title=request.form.get('title','').strip(); body=request.form.get('body','').strip()
        if not all([subject,topic,title,body]): flash('Fill in all content fields.','error')
        else:
            c=get_db(); c.execute('INSERT OR IGNORE INTO subjects(name,description) VALUES(?,?)',(subject,'Administrator-added subject')); sid=c.execute('SELECT id FROM subjects WHERE name=?',(subject,)).fetchone()['id']; c.execute('INSERT OR IGNORE INTO topics(subject_id,name) VALUES(?,?)',(sid,topic)); c.execute('INSERT INTO admin_content(subject_name,topic_name,section_title,body,created_at) VALUES(?,?,?,?,?)',(subject,topic,title,body,datetime.now().isoformat(timespec='seconds'))); c.commit(); c.close(); flash('Topic and supplementary content saved.','success'); return redirect(url_for('admin'))
    c=get_db(); entries=c.execute('SELECT * FROM admin_content ORDER BY id DESC LIMIT 50').fetchall(); subjects=c.execute('SELECT name FROM subjects ORDER BY name').fetchall(); c.close(); return render_template('admin.html',entries=entries,subjects=subjects)

# --------------------------------------------------------------- Syllabus & tests
@app.route('/subjects')
@login_required
def subjects():
    c = get_db()
    data = []
    for s in c.execute('SELECT * FROM subjects ORDER BY id').fetchall():
        data.append((s, c.execute('SELECT * FROM topics WHERE subject_id=? ORDER BY id',
                                  (s['id'],)).fetchall()))
    best = topic_best(c, current_user.id)
    c.close()
    return render_template('subjects.html', data=data, best=best)


@app.route('/notes')
@login_required
def notes():
    c = get_db()
    rows = c.execute('SELECT subjects.name subject_name, subjects.description subject_description, topics.id topic_id, topics.name topic_name FROM subjects JOIN topics ON topics.subject_id=subjects.id ORDER BY subjects.id, topics.id').fetchall()
    c.close()
    # Topic-aware study notes: concise definitions, key ideas and a practice prompt for every syllabus topic.
    note_rows = []
    for r in rows:
        topic = r['topic_name']; subject = r['subject_name']; low = (subject + ' ' + topic).lower()
        if any(k in low for k in ('linear algebra','calculus','matrices','determinant','eigenvalue','limit','differential','discrete mathematics','set theory','propositional logic','graph theory','counting','recurrence')):
            summary = f'{topic} builds mathematical reasoning used in engineering and computing. Identify the definitions, formulas, assumptions and conditions before solving a problem.'
            key_points = ['Write the relevant definition or formula first.', 'Work through a small numerical example step by step.', 'Check domain, dimensions and edge cases before accepting the result.']
            practice = f'Solve one example involving {topic}, then explain why each step is valid.'
        elif any(k in low for k in ('data structure','algorithm','programming','coding','arrays','linked lists','stack','queue','tree','heap','hash','graph','sorting','searching','dynamic programming','backtracking','greedy','recursion','stl','pointer')):
            summary = f'{topic} is best learned by understanding the operation, implementing it, and analysing its time and space complexity.'
            key_points = ['Know the input, output and core operation.', 'Trace a small example by hand before coding.', 'Test empty, single-element, duplicate and boundary cases.', 'State time and auxiliary-space complexity.']
            practice = f'Write a short program for a core {topic} operation and test it with at least three edge cases.'
        elif any(k in low for k in ('security','cryptography','forensic','network','protocol','cloud')):
            summary = f'{topic} covers systems concepts and practical trade-offs. Focus on terminology, architecture, how the components interact and common failure modes.'
            key_points = ['Define the core terms accurately.', 'Draw or describe the flow between components.', 'Compare benefits, limitations and risks.', 'Use a real-world computing example.']
            practice = f'Draw a simple diagram that explains {topic} and annotate each component.'
        else:
            summary = f'{topic} introduces the core concepts of {subject}. Connect the theory to a worked example and a practical computer-engineering application.'
            key_points = ['Learn the main definitions and terminology.', 'Summarise the process or architecture in your own words.', 'Review one worked example and note common mistakes.']
            practice = f'Write a short explanation of {topic} and give one practical application.'
        note_rows.append({'subject': subject, 'description': r['subject_description'], 'id': r['topic_id'], 'topic': topic, 'summary': summary, 'points': key_points, 'practice': practice})
    c = get_db()
    saved = {r['topic_id'] for r in c.execute('SELECT topic_id FROM bookmarks WHERE user_id=?',(current_user.id,)).fetchall()}
    completed = {r['topic_id'] for r in c.execute('SELECT topic_id FROM topic_progress WHERE user_id=? AND completed=1',(current_user.id,)).fetchall()}
    c.close()
    return render_template('notes.html', notes=note_rows, saved=saved, completed=completed)


@app.route('/tests')
@login_required
def tests():
    c = get_db()
    topics = c.execute('SELECT topics.*,subjects.name subject_name,COUNT(questions.id) question_count '
                       'FROM topics JOIN subjects ON subjects.id=topics.subject_id '
                       'LEFT JOIN questions ON questions.topic_id=topics.id '
                       'GROUP BY topics.id ORDER BY subjects.id,topics.id').fetchall()
    best = topic_best(c, current_user.id)
    c.close()
    groups, order = {}, []
    for t in topics:
        if t['subject_name'] not in groups:
            groups[t['subject_name']] = []
            order.append(t['subject_name'])
        groups[t['subject_name']].append(t)
    return render_template('tests.html', groups=[(n, groups[n]) for n in order], best=best,
                           total=len(topics))


@app.route('/test/<int:topic_id>', methods=['GET', 'POST'])
@login_required
def take_test(topic_id):
    c = get_db()
    topic = c.execute('SELECT topics.*,subjects.name subject_name FROM topics JOIN subjects '
                      'ON subjects.id=topics.subject_id WHERE topics.id=?', (topic_id,)).fetchone()
    if not topic:
        c.close()
        abort(404)
    questions = c.execute('SELECT * FROM questions WHERE topic_id=? ORDER BY id', (topic_id,)).fetchall()
    if len(questions) < 10:
        c.close()
        flash('This test needs at least 10 questions.', 'error')
        return redirect(url_for('tests'))
    if request.method == 'POST':
        try:
            elapsed = max(0, int(datetime.now().timestamp() - float(request.form.get('started_at', '0'))))
        except (TypeError, ValueError):
            elapsed = 0
        score, answers = 0, []
        for q in questions:
            a = request.form.get('q_' + str(q['id']), '')
            ok = int(a == q['correct'])
            score += ok
            answers.append((q['id'], a, ok))
        total = len(questions)
        pct = round(score * 100 / total, 2)
        cur = c.execute('INSERT INTO test_attempts(user_id,topic_id,score,total,percentage,level,'
                        'time_taken,attempted_at) VALUES(?,?,?,?,?,?,?,?)',
                        (current_user.id, topic_id, score, total, pct, level_for_score(pct), elapsed,
                         datetime.now().isoformat(timespec='seconds')))
        aid = cur.lastrowid
        c.executemany('INSERT INTO attempt_answers(attempt_id,question_id,answer,is_correct) '
                      'VALUES(?,?,?,?)', [(aid, *x) for x in answers])
        c.commit()
        c.close()
        return redirect(url_for('result', attempt_id=aid))
    c.close()
    return render_template('take_test.html', topic=topic, questions=questions,
                           started_at=datetime.now().timestamp())


@app.route('/result/<int:attempt_id>')
@login_required
def result(attempt_id):
    c = get_db()
    a = c.execute('SELECT test_attempts.*,topics.name topic_name,subjects.name subject_name '
                  'FROM test_attempts JOIN topics ON topics.id=topic_id '
                  'JOIN subjects ON subjects.id=topics.subject_id '
                  'WHERE test_attempts.id=? AND user_id=?', (attempt_id, current_user.id)).fetchone()
    if not a:
        c.close()
        abort(404)
    answers = c.execute('SELECT attempt_answers.answer,attempt_answers.is_correct,questions.question,'
                        'questions.correct,questions.explanation,questions.option_a,questions.option_b,'
                        'questions.option_c,questions.option_d FROM attempt_answers '
                        'JOIN questions ON questions.id=question_id WHERE attempt_id=? '
                        'ORDER BY attempt_answers.id', (attempt_id,)).fetchall()
    videos = adaptive_videos(c, a['topic_id'], a['level'])
    c.close()
    return render_template('result.html', attempt=a, answers=answers, playlist=videos)


@app.route('/playlist/<int:topic_id>')
@login_required
def playlist(topic_id):
    c = get_db()
    topic = c.execute('SELECT topics.*,subjects.name subject_name FROM topics JOIN subjects '
                      'ON subjects.id=topics.subject_id WHERE topics.id=?', (topic_id,)).fetchone()
    if not topic:
        c.close()
        abort(404)
    latest = c.execute('SELECT * FROM test_attempts WHERE user_id=? AND topic_id=? '
                       'ORDER BY attempted_at DESC,id DESC LIMIT 1', (current_user.id, topic_id)).fetchone()
    videos = (adaptive_videos(c, topic_id, latest['level']) if latest else
              c.execute('SELECT * FROM videos WHERE topic_id=? ORDER BY id', (topic_id,)).fetchall())
    c.close()
    return render_template('playlist.html', topic=topic, latest=latest, videos=videos)


@app.route('/progress')
@login_required
def progress():
    uid = current_user.id
    c = get_db()
    attempts = c.execute('SELECT test_attempts.*,topics.name topic_name,subjects.name subject_name '
                         'FROM test_attempts JOIN topics ON topics.id=topic_id '
                         'JOIN subjects ON subjects.id=topics.subject_id WHERE user_id=? '
                         'ORDER BY attempted_at DESC,test_attempts.id DESC', (uid,)).fetchall()
    summary = c.execute('SELECT topics.id topic_id,topics.name topic_name,subjects.name subject_name,'
                        'ROUND(AVG(percentage),1) avg_score,COUNT(*) attempts FROM test_attempts '
                        'JOIN topics ON topics.id=topic_id JOIN subjects ON subjects.id=topics.subject_id '
                        'WHERE user_id=? GROUP BY topic_id ORDER BY avg_score', (uid,)).fetchall()
    c.close()
    chart = [{'label': a['attempted_at'][:10], 'topic': a['topic_name'],
              'value': round(a['percentage'], 1)} for a in reversed(attempts)]   # oldest -> newest
    return render_template('progress.html', attempts=attempts, topic_summary=summary, chart=chart)


# ------------------------------------------------------------ Hosting endpoints
@app.get('/_app/health')
def app_health():
    return '', 204


@app.get('/manus-routes.json')
def manus_routes():
    return send_from_directory(os.path.join(BASE_DIR, 'public'), 'manus-routes.json',
                               mimetype='application/json')


# ------------------------------------------------------------------ Error pages
@app.errorhandler(404)
def not_found(_e):
    return render_template('error.html', code=404, title='Page not found',
                           message="We couldn't find what you were looking for."), 404


@app.errorhandler(500)
def server_error(_e):
    return render_template('error.html', code=500, title='Something went wrong',
                           message='An unexpected error occurred. Please try again.'), 500


init_db()

if __name__ == '__main__':
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler(daemon=True)
        scheduler.add_job(dispatch_due_whatsapp_reminders, 'interval', minutes=1, id='whatsapp-target-reminders',
                          max_instances=1, coalesce=True)
        scheduler.start()
        app.logger.info('WhatsApp target reminder scheduler started (checks every minute).')
    except ImportError:
        app.logger.warning('APScheduler is not installed; WhatsApp reminders are disabled. Run pip install -r requirements.txt.')
    app.run(host=os.environ.get('HOST', '127.0.0.1'), port=int(os.environ.get('PORT', 5000)),
            debug=os.environ.get('FLASK_DEBUG', '1') == '1', use_reloader=False)
