import json
import os
import datetime
import uuid
import secrets
import hashlib
import sqlite3
from collections import defaultdict
from io import BytesIO

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, send_file
from werkzeug.security import generate_password_hash, check_password_hash
import numpy as np
from tensorflow.keras.models import load_model
from tensorflow.keras.preprocessing import image

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False


app = Flask(__name__, template_folder="../templates", static_folder='../static')
app.secret_key = "replace-with-random-secret"  # change for production

# Email configuration for password reset (use a real SMTP account and app password)
app.config.update({
    'MAIL_SERVER': 'smtp.gmail.com',
    'MAIL_PORT': 587,
    'MAIL_USE_TLS': True,
    'MAIL_USERNAME': 'velan.mca2024@adhiyamaan.in',
    'MAIL_PASSWORD': '',  # set actual password or app-specific password here
    'MAIL_DEFAULT_SENDER': 'velan.mca2024@adhiyamaan.in'
})

USERS_FILE = os.path.join(os.path.dirname(__file__), 'users.json')
OTP_DB_FILE = os.path.join(os.path.dirname(__file__), 'otp_store.db')


def init_otp_db():
    conn = sqlite3.connect(OTP_DB_FILE)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS otp_requests (
            email TEXT PRIMARY KEY,
            otp TEXT,
            expires_at TEXT,
            attempts INTEGER DEFAULT 0,
            lockout_until TEXT,
            channel TEXT,
            created_at TEXT,
            verified INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()


def get_otp_entry(email):
    conn = sqlite3.connect(OTP_DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT email, otp, expires_at, attempts, lockout_until, channel, created_at, verified FROM otp_requests WHERE email=?', (email,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {
        'email': row[0],
        'otp': row[1],
        'expires_at': row[2],
        'attempts': row[3],
        'lockout_until': row[4],
        'channel': row[5],
        'created_at': row[6],
        'verified': bool(row[7])
    }


def save_otp_entry(email, otp, expires_at, channel='email'):
    conn = sqlite3.connect(OTP_DB_FILE)
    conn.execute('''
        INSERT OR REPLACE INTO otp_requests (email, otp, expires_at, attempts, lockout_until, channel, created_at, verified)
        VALUES (?, ?, ?, 0, NULL, ?, ?, 0)
    ''', (email, otp, expires_at.isoformat(), channel, datetime.datetime.now().isoformat()))
    conn.commit()
    conn.close()


def increment_otp_attempts(email):
    entry = get_otp_entry(email)
    if not entry:
        return
    attempts = entry['attempts'] + 1
    lockout_until = None
    if attempts >= 5:
        lockout_until = (datetime.datetime.now() + datetime.timedelta(minutes=15)).isoformat()
    conn = sqlite3.connect(OTP_DB_FILE)
    conn.execute('UPDATE otp_requests SET attempts = ?, lockout_until = ? WHERE email = ?', (attempts, lockout_until, email))
    conn.commit()
    conn.close()


def mark_otp_verified(email):
    conn = sqlite3.connect(OTP_DB_FILE)
    conn.execute('UPDATE otp_requests SET verified = 1 WHERE email = ?', (email,))
    conn.commit()
    conn.close()


def delete_otp_entry(email):
    conn = sqlite3.connect(OTP_DB_FILE)
    conn.execute('DELETE FROM otp_requests WHERE email = ?', (email,))
    conn.commit()
    conn.close()


def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_users(users):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2)


def current_user():
    email = session.get('email')
    users = load_users()
    return users.get(email)


# initialize OTP store database
init_otp_db()


def send_reset_email(to_email, otp):
    from email.message import EmailMessage
    import smtplib

    sender = app.config['MAIL_DEFAULT_SENDER']
    msg = EmailMessage()
    msg['Subject'] = 'Nutrition Analyzer Password Reset OTP'
    msg['From'] = sender
    msg['To'] = to_email

    plain_body = f"""
Hello,

You requested a password reset for Nutrition Analyzer.

Your One-Time Password (OTP): {otp}

- OTP expires in 10 minutes.
- This is an auto-generated email from {sender}.
- If you did not request this, please ignore this email.

Use this OTP on the password reset page to continue.

Thanks,
Nutrition Analyzer Support
"""

    html_body = render_template('email_otp.html', otp=otp, expires_minutes=10, sender=sender)

    msg.set_content(plain_body)
    msg.add_alternative(html_body, subtype='html')

    try:
        with smtplib.SMTP(app.config['MAIL_SERVER'], app.config['MAIL_PORT']) as server:
            server.ehlo()
            server.starttls()
            server.login(app.config['MAIL_USERNAME'], app.config['MAIL_PASSWORD'])
            server.send_message(msg)
    except Exception as e:
        app.logger.error(f"Failed to send reset email: {e}")
        raise


def send_sms_otp(phone_number, otp):
    # Twilio-based SMS fallback. Configure env vars: TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM
    try:
        from twilio.rest import Client
    except ImportError:
        raise RuntimeError('Twilio library not installed (pip install twilio)')

    account_sid = os.getenv('TWILIO_SID')
    auth_token = os.getenv('TWILIO_TOKEN')
    from_phone = os.getenv('TWILIO_FROM')

    if not account_sid or not auth_token or not from_phone:
        raise RuntimeError('Twilio configuration missing in environment variables')

    client = Client(account_sid, auth_token)
    message_body = f"Your Nutrition Analyzer OTP is {otp} (valid 10 minutes)."
    client.messages.create(body=message_body, from_=from_phone, to=phone_number)


MODEL_PATH = os.path.join(os.path.dirname(__file__), 'nutrition.h5')
if not os.path.exists(MODEL_PATH):
    raise FileNotFoundError(f"Model file not found: {MODEL_PATH}")

model = load_model(MODEL_PATH)
print(f"Loaded model from disk: {MODEL_PATH}")


@app.route('/')
def home():
    return render_template('home.html', user=current_user())


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        users = load_users()
        user = users.get(email)
        if user and check_password_hash(user['password'], password):
            session['email'] = email
            flash('Logged in successfully.', 'success')
            return redirect(url_for('home'))
        else:
            flash('Invalid email or password.', 'error')
    return render_template('login.html', user=current_user())


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        channel = request.form.get('channel', 'email')

        if not email:
            flash('Please enter your email address.', 'error')
            return render_template('forgot_password.html', user=current_user())

        users = load_users()
        if email not in users:
            flash('If an account with that email exists, an OTP has been sent.', 'info')
            return redirect(url_for('login'))

        user = users[email]
        otp = "{0:06d}".format(secrets.randbelow(1000000))
        expires_at = datetime.datetime.now() + datetime.timedelta(minutes=10)
        save_otp_entry(email, otp, expires_at, channel=channel)

        try:
            if channel == 'sms':
                if 'phone' not in user or not user['phone']:
                    flash('SMS channel requires a phone number in your profile.', 'error')
                    return redirect(url_for('forgot_password'))
                send_sms_otp(user['phone'], otp)
                method_msg = 'SMS'
            else:
                send_reset_email(email, otp)
                method_msg = 'email'

            session['reset_email'] = email  # Set the email in session for OTP verification
            flash(f'OTP sent via {method_msg}. Please check spam/junk if using email.', 'success')
            return redirect(url_for('verify_otp'))
        except Exception as ex:
            app.logger.error(f'OTP send failure: {ex}')
            flash('Unable to send OTP right now. Please try again after a minute.', 'error')
            # For debugging local development only (remove in production):
            session['reset_email'] = email  # Set session even for debug
            flash(f'OTP (debug): {otp}', 'info')
            return redirect(url_for('verify_otp'))

    return render_template('forgot_password.html', user=current_user())

@app.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    email = session.get('reset_email')
    if not email:
        flash('No active password reset request. Please start again.', 'error')
        return redirect(url_for('forgot_password'))

    entry = get_otp_entry(email)
    if not entry:
        flash('No OTP request found. Please start again.', 'error')
        return redirect(url_for('forgot_password'))

    now = datetime.datetime.now()

    if entry['lockout_until']:
        lockout_until = datetime.datetime.fromisoformat(entry['lockout_until'])
        if now < lockout_until:
            flash('Too many incorrect attempts. Try again after 15 minutes.', 'error')
            return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        entered_otp = request.form.get('otp', '').strip()

        if now > datetime.datetime.fromisoformat(entry['expires_at']):
            flash('OTP has expired. Please request a new one.', 'error')
            delete_otp_entry(email)
            return redirect(url_for('forgot_password'))

        if entered_otp != entry['otp']:
            increment_otp_attempts(email)
            attempts_left = max(0, 5 - (entry['attempts'] + 1))
            flash(f'Incorrect OTP. {attempts_left} attempt(s) left.', 'error')
            return render_template('verify_otp.html', user=current_user())

        # Correct OTP
        mark_otp_verified(email)
        session['otp_verified_email'] = email
        session['reset_token'] = secrets.token_urlsafe(32)
        session['reset_expires'] = (now + datetime.timedelta(minutes=15)).isoformat()

        # optional 2FA via security question if configured
        users = load_users()
        user = users.get(email)
        if user and user.get('security_question'):
            session['reset_step'] = 'security_question'
            flash('OTP verified. Please answer your security question to continue.', 'success')
            return redirect(url_for('verify_security_question'))

        flash('OTP verified. Please set a new password now.', 'success')
        return redirect(url_for('reset_password', token=session['reset_token']))

    return render_template('verify_otp.html', user=current_user())


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if session.get('reset_token') != token or not session.get('reset_expires'):
        flash('Invalid or expired reset token.', 'error')
        return redirect(url_for('forgot_password'))

    if datetime.datetime.now() > datetime.datetime.fromisoformat(session['reset_expires']):
        flash('Reset token has expired. Please start again.', 'error')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not password or len(password) < 6:
            flash('Password must be at least 6 characters long.', 'error')
            return render_template('reset_password.html', token=token)

        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return render_template('reset_password.html', token=token)

        users = load_users()
        email = session.get('reset_email')
        if email and email in users:
            users[email]['password'] = generate_password_hash(password)
            save_users(users)

            session.pop('reset_token', None)
            session.pop('reset_email', None)
            session.pop('reset_expires', None)

            flash('Password has been reset successfully. You can now log in.', 'success')
            return redirect(url_for('login'))
        else:
            flash('User not found.', 'error')
            return redirect(url_for('forgot_password'))

    return render_template('reset_password.html', token=token)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        security_question = request.form.get('security_question', '').strip()
        security_answer = request.form.get('security_answer', '').strip()
        
        if not name or not email or not password or not confirm_password or not security_question or not security_answer:
            flash('All fields are required.', 'error')
            return render_template('register.html', user=current_user())
        
        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return render_template('register.html', user=current_user())
        
        if len(security_answer) < 2:
            flash('Security answer must be at least 2 characters long.', 'error')
            return render_template('register.html', user=current_user())

        users = load_users()
        if email in users:
            flash('Email already registered. Please login.', 'error')
            return redirect(url_for('login'))

        users[email] = {
            'name': name,
            'email': email,
            'password': generate_password_hash(password),
            'phone': request.form.get('phone', '').strip(),
            'security_question': security_question,
            'security_answer': security_answer.lower()  # Store in lowercase for case-insensitive comparison
        }
        save_users(users)
        session['email'] = email
        flash('Registration successful. Logged in.', 'success')
        return redirect(url_for('home'))

    return render_template('register.html', user=current_user())


@app.route('/logout')
def logout():
    session.pop('email', None)
    flash('Logged out.', 'success')
    return redirect(url_for('home'))


def compute_bmi(weight_kg, height_cm):
    height_m = height_cm / 100.0
    if height_m <= 0:
        return None
    return round(weight_kg / (height_m * height_m), 2)


def bmi_category(bmi):
    if bmi is None:
        return 'Unknown'
    if bmi < 18.5:
        return 'Underweight'
    if bmi < 25:
        return 'Normal weight'
    if bmi < 30:
        return 'Overweight'
    return 'Obese'


def recommendation_by_bmi_and_condition(bmi, condition):
    condition_lower = condition.lower() if condition else ''
    if 'diabetes' in condition_lower:
        return 'Low-glycemic foods, whole grains, vegetables, lean proteins, avoid sweets and processed carbs.'
    if 'hypertension' in condition_lower or 'blood pressure' in condition_lower:
        return 'Low sodium diet, leafy greens, fruits, lean protein, minimal processed foods.'
    if 'pcos' in condition_lower:
        return 'High fiber, low simple carbs, lean protein, healthy fats, regular exercise.'
    if bmi is None:
        return 'Balance diet with vegetables, lean protein, and exercise.'

    if bmi < 18.5:
        return 'Increase calorie intake with nutrient-dense foods: nuts, avocados, dairy, lean meats.'
    if bmi < 25:
        return 'Maintain with balanced diet: whole grains, vegetables, fruits, lean protein.'
    if bmi < 30:
        return 'Reduce calories slightly, more vegetables, lean protein, avoid sugary drinks.'
    return 'Reduce calories, focus on high fiber and protein, avoid processed foods and sugars.'


def food_recommendations_by_health(condition, bmi):
    """
    Generate food recommendations based on both disease/condition AND BMI.
    Combines condition-specific foods with BMI-appropriate portion/type suggestions.
    """
    condition_lower = condition.lower() if condition else ''
    recommendations = []

    # Base recommendations from disease/condition
    diabetes_foods = ['Leafy greens', 'Whole grain oats', 'Berries', 'Nuts', 'Legumes', 'Broccoli', 'Cauliflower']
    hypertension_foods = ['Bananas', 'Sweet potatoes', 'Spinach', 'Fatty fish', 'Beets', 'Garlic', 'Low-sodium options']
    pcos_foods = ['Avocado', 'Berries', 'Broccoli', 'Fatty fish', 'Whole grains', 'Nuts', 'Seeds']
    
    # BMI-specific modifiers
    underweight_boost = ['Nuts', 'Avocado', 'Greek yogurt', 'Olive oil', 'Whole milk', 'Healthy smoothies']
    normal_weight_foods = ['Balanced vegetables', 'Lean proteins', 'Whole grains', 'Fruits', 'Berries']
    overweight_light = ['More vegetables', 'Lean proteins', 'Low-fat options', 'Fiber-rich foods']
    obese_light = ['Leafy greens', 'Kale', 'Spinach', 'Broccoli', 'Salmon', 'Lentils', 'Water']

    # If condition is specified, start with condition-based foods
    if 'diabetes' in condition_lower:
        recommendations = diabetes_foods.copy()
        # Adjust based on BMI
        if bmi and bmi < 18.5:
            recommendations.extend(['Greek yogurt', 'Nuts', 'Seeds'])
        elif bmi and bmi > 30:
            recommendations.extend(['More fiber', 'Green tea', 'Water'])
    elif 'hypertension' in condition_lower or 'blood pressure' in condition_lower:
        recommendations = hypertension_foods.copy()
        # Adjust based on BMI
        if bmi and bmi < 18.5:
            recommendations.extend(['Nuts', 'Seeds', 'Salmon fillets'])
        elif bmi and bmi > 30:
            recommendations.extend(['Kale', 'Spinach', 'Low-sodium soups'])
    elif 'pcos' in condition_lower:
        recommendations = pcos_foods.copy()
        # Adjust based on BMI
        if bmi and bmi < 18.5:
            recommendations.extend(['More nuts', 'Nut butters', 'Oily fish'])
        elif bmi and bmi > 30:
            recommendations.extend(['More vegetables', 'Lean meats', 'Low-fat dairy'])
    elif condition_lower:
        # For any other condition mentioned, start broad and add BMI-specific advice
        recommendations = ['Whole grains', 'Lean proteins', 'Fresh vegetables', 'Fruits', 'Water']
        if bmi and bmi < 18.5:
            recommendations.extend(underweight_boost)
        elif bmi and 18.5 <= bmi < 25:
            recommendations.extend(normal_weight_foods)
        elif bmi and 25 <= bmi < 30:
            recommendations.extend(overweight_light)
        elif bmi and bmi >= 30:
            recommendations.extend(obese_light)
    else:
        # No condition specified, recommend based solely on BMI
        if bmi is None:
            recommendations = ['Apples', 'Bananas', 'Oranges', 'Leafy greens', 'Nuts', 'Water']
        elif bmi < 18.5:
            recommendations = ['Bananas', 'Nuts', 'Avocado', 'Greek yogurt', 'Healthy smoothies', 'Whole milk']
        elif bmi < 25:
            recommendations = ['Apples', 'Berries', 'Broccoli', 'Quinoa', 'Lean proteins', 'Whole grains']
        elif bmi < 30:
            recommendations = ['Leafy greens', 'Cauliflower', 'Beans', 'Oats', 'Green tea', 'Lean chicken']
        else:
            recommendations = ['Kale', 'Chia seeds', 'Salmon', 'Lentils', 'Walnuts', 'Spinach', 'Broccoli']

    # Remove duplicates while preserving order
    seen = set()
    unique_recommendations = []
    for item in recommendations:
        if item not in seen:
            seen.add(item)
            unique_recommendations.append(item)
    
    return unique_recommendations[:10]  # Return top 10 recommendations


def calculate_daily_calorie_target(weight_kg, height_cm, bmi, activity_level='moderate'):
    """Calculate daily calorie target using Harris-Benedict equation."""
    if not weight_kg or not height_cm or not bmi:
        return 2000  # Default target
    
    # Using simplified calculation based on BMI
    base_calories = weight_kg * 25  # Approximate baseline
    
    if bmi < 18.5:
        base_calories *= 1.1  # Add 10% for underweight
    elif bmi >= 30:
        base_calories *= 0.9  # Reduce 10% for obese
    
    # Activity multiplier
    activity_multipliers = {
        'sedentary': 1.2,
        'light': 1.375,
        'moderate': 1.55,
        'active': 1.725,
        'very active': 1.9
    }
    
    return int(base_calories * activity_multipliers.get(activity_level, 1.55))


def get_weekly_nutrition_summary(user_profile):
    """Get nutrition data for the last 7 days."""
    if not user_profile or 'food_classifications' not in user_profile:
        return {
            'labels': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
            'calories': [0] * 7,
            'carbs': [0] * 7,
            'protein': [0] * 7
        }
    
    classifications = user_profile['food_classifications']
    daily_stats = defaultdict(lambda: {'calories': 0, 'carbs': 0, 'protein': 0})
    
    # Process last 7 days of data
    for classification in classifications:
        try:
            date_str = classification['timestamp'].split(' ')[0]
            nutrition = classification.get('nutrition', {})
            
            daily_stats[date_str]['calories'] += nutrition.get('calories', 0)
            daily_stats[date_str]['carbs'] += nutrition.get('carbohydrates_total_g', 0)
            daily_stats[date_str]['protein'] += nutrition.get('fat_total_g', 0)  # Simplified
        except:
            pass
    
    # Get last 7 days
    labels = []
    calories_data = []
    carbs_data = []
    protein_data = []
    
    for i in range(6, -1, -1):
        date = (datetime.datetime.now() - datetime.timedelta(days=i)).strftime('%Y-%m-%d')
        labels.append((datetime.datetime.now() - datetime.timedelta(days=i)).strftime('%a'))
        stats = daily_stats.get(date, {'calories': 0, 'carbs': 0, 'protein': 0})
        calories_data.append(stats['calories'])
        carbs_data.append(stats['carbs'])
        protein_data.append(stats['protein'])
    
    return {
        'labels': labels,
        'calories': calories_data,
        'carbs': carbs_data,
        'protein': protein_data
    }


def generate_meal_plan(condition, bmi, target_calories):
    """Generate a simple meal plan based on condition and BMI."""
    meal_plans = {
        'diabetes': {
            'breakfast': ['Oatmeal with berries', 'Whole grain toast with avocado', 'Scrambled eggs with spinach'],
            'lunch': ['Grilled chicken with broccoli', 'Tuna salad', 'Turkey sandwich on whole grain'],
            'dinner': ['Baked salmon with green beans', 'Lean beef with sweet potato', 'Grilled chicken breast with quinoa'],
            'snacks': ['Apple with almond butter', 'Nuts', 'Greek yogurt']
        },
        'hypertension': {
            'breakfast': ['Banana with oatmeal', 'Low-sodium toast', 'Smoothie with spinach'],
            'lunch': ['Grilled fish with potatoes', 'Vegetable soup', 'Lean meat sandwich'],
            'dinner': ['Baked white fish', 'Vegetable stir-fry', 'Grilled chicken'],
            'snacks': ['Banana', 'Berries', 'Almonds']
        },
        'pcos': {
            'breakfast': ['Eggs with vegetables', 'Greek yogurt with nuts', 'Whole grain toast with egg'],
            'lunch': ['Salad with grilled chicken', 'Fish tacos with whole grain tortillas', 'Vegetable and protein bowl'],
            'dinner': ['Grilled salmon', 'Turkey meatballs', 'Lean beef stir-fry'],
            'snacks': ['Nuts', 'Cheese', 'Berries']
        },
        'default': {
            'breakfast': ['Whole grain cereal', 'Eggs', 'Oatmeal with fruit'],
            'lunch': ['Grilled chicken', 'Vegetable salad', 'Lean meat sandwich'],
            'dinner': ['Fish', 'Lean beef', 'Vegetable pasta'],
            'snacks': ['Fruits', 'Nuts', 'Yogurt']
        }
    }
    
    condition_lower = condition.lower() if condition else 'default'
    for key in meal_plans:
        if key in condition_lower:
            return meal_plans[key]
    
    return meal_plans['default']


def generate_api_token():
    """Generate a secure API token for mobile app sync."""
    return secrets.token_urlsafe(32)


def verify_api_token(token, user_email):
    """Verify if API token belongs to user."""
    users = load_users()
    user = users.get(user_email)
    if not user:
        return False
    
    tokens = user.get('api_tokens', [])
    for t in tokens:
        if t.get('token') == token:
            return True
    return False


def add_user_to_social_index(user_email, user_name):
    """Add user to social sharing index (public list)."""
    SOCIAL_FILE = os.path.join(os.path.dirname(__file__), 'social_users.json')
    social_data = {}
    
    if os.path.exists(SOCIAL_FILE):
        with open(SOCIAL_FILE, 'r', encoding='utf-8') as f:
            social_data = json.load(f)
    
    if user_email not in social_data:
        social_data[user_email] = {
            'name': user_name,
            'joined': datetime.datetime.now().strftime('%Y-%m-%d'),
            'shared_meals': [],
            'followers': [],
            'following': []
        }
    
    with open(SOCIAL_FILE, 'w', encoding='utf-8') as f:
        json.dump(social_data, f, indent=2)


def share_meal(user_email, food_name, nutrition, visibility='public'):
    """Create a shareable meal entry."""
    SOCIAL_FILE = os.path.join(os.path.dirname(__file__), 'social_users.json')
    social_data = {}
    
    if os.path.exists(SOCIAL_FILE):
        with open(SOCIAL_FILE, 'r', encoding='utf-8') as f:
            social_data = json.load(f)
    
    if user_email in social_data:
        share_id = str(uuid.uuid4())[:8]
        shared_meal = {
            'id': share_id,
            'food': food_name,
            'nutrition': nutrition,
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'likes': 0,
            'comments': [],
            'visibility': visibility
        }
        
        if 'shared_meals' not in social_data[user_email]:
            social_data[user_email]['shared_meals'] = []
        
        social_data[user_email]['shared_meals'].append(shared_meal)
        
        with open(SOCIAL_FILE, 'w', encoding='utf-8') as f:
            json.dump(social_data, f, indent=2)
        
        return share_id
    return None


def get_social_feed(limit=20):
    """Get public shared meals from all users."""
    SOCIAL_FILE = os.path.join(os.path.dirname(__file__), 'social_users.json')
    
    if not os.path.exists(SOCIAL_FILE):
        return []
    
    with open(SOCIAL_FILE, 'r', encoding='utf-8') as f:
        social_data = json.load(f)
    
    feed = []
    for user_email, user_data in social_data.items():
        user_name = user_data.get('name', 'User')
        for meal in user_data.get('shared_meals', []):
            if meal.get('visibility') == 'public':
                feed.append({
                    'user_email': user_email,
                    'user_name': user_name,
                    'meal': meal
                })
    
    # Sort by timestamp descending
    feed.sort(key=lambda x: x['meal']['timestamp'], reverse=True)
    return feed[:limit]


@app.route('/profile', methods=['GET', 'POST'])
def profile():
    user = current_user()
    if not user:
        return redirect(url_for('login'))

    profile_data = user.get('profile', {})

    if request.method == 'POST':
        condition = request.form.get('condition', '').strip()
        target_foods = request.form.get('target_foods', '').strip()
        height_cm = request.form.get('height_cm', '').strip()
        weight_kg = request.form.get('weight_kg', '').strip()

        try:
            h = float(height_cm) if height_cm else None
            w = float(weight_kg) if weight_kg else None
        except ValueError:
            flash('Height and weight must be numeric values.', 'error')
            return render_template('profile.html', user=user, profile=profile_data)

        bmi_val = compute_bmi(w, h) if h and w else None
        bmi_text = bmi_category(bmi_val)
        recommended = recommendation_by_bmi_and_condition(bmi_val, condition)

        profile_data = {
            'condition': condition,
            'target_foods': target_foods,
            'height_cm': h,
            'weight_kg': w,
            'bmi': bmi_val,
            'bmi_category': bmi_text,
            'recommendation': recommended,
            'note': 'This profile data is stored with your user account and can help personalize your nutrition advice.',
            'food_classifications': user.get('profile', {}).get('food_classifications', [])
        }

        users = load_users()
        users[user['email']]['profile'] = profile_data
        save_users(users)

        flash('Profile saved successfully.', 'success')
        user = users[user['email']]

    return render_template('profile.html', user=user, profile=profile_data)


@app.route('/weekly-nutrition')
def weekly_nutrition():
    """API endpoint for weekly nutrition data."""
    if not current_user():
        return jsonify({'error': 'Not authenticated'}), 401
    
    user = current_user()
    profile = user.get('profile', {})
    summary = get_weekly_nutrition_summary(profile)
    
    return jsonify(summary)


@app.route('/meal-plan')
def meal_plan():
    """Display personalized meal plan."""
    if not current_user():
        return redirect(url_for('login'))
    
    user = current_user()
    profile = user.get('profile', {})
    
    bmi = profile.get('bmi')
    condition = profile.get('condition', '')
    weight = profile.get('weight_kg')
    height = profile.get('height_cm')
    
    daily_target = calculate_daily_calorie_target(weight, height, bmi)
    meals = generate_meal_plan(condition, bmi, daily_target)
    
    return render_template('meal_plan.html', 
                         user=user, 
                         meals=meals, 
                         daily_target=daily_target,
                         condition=condition,
                         bmi=bmi)


@app.route('/export-pdf')
def export_pdf():
    """Export nutrition report as PDF."""
    if not current_user():
        return jsonify({'error': 'Not authenticated'}), 401
    
    if not PDF_AVAILABLE:
        flash('PDF export requires reportlab. Install with: pip install reportlab', 'error')
        return redirect(url_for('profile'))
    
    try:
        user = current_user()
        profile = user.get('profile', {})
        
        # Create PDF in memory
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        elements = []
        styles = getSampleStyleSheet()
        
        # Title
        title = Paragraph(f"<b>Nutrition Report - {user.get('name', 'User')}</b>", styles['Heading1'])
        elements.append(title)
        elements.append(Spacer(1, 0.3 * 1.02))
        
        # Profile Summary
        summary_data = [
            ['BMI', str(profile.get('bmi', 'N/A'))],
            ['Category', profile.get('bmi_category', 'N/A')],
            ['Health Condition', profile.get('condition', 'None')],
            ['Total Foods Classified', str(len(profile.get('food_classifications', [])))],
        ]
        
        summary_table = Table(summary_data, colWidths=[2 * 1.02, 2 * 1.02])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightblue),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, 0.3 * 1.02))
        
        # Recent Foods
        if profile.get('food_classifications'):
            foods_title = Paragraph("<b>Recent Foods Classified</b>", styles['Heading2'])
            elements.append(foods_title)
            
            foods_data = [['Food', 'Date', 'Calories']]
            for item in profile.get('food_classifications', [])[-10:]:
                foods_data.append([
                    item.get('food', 'N/A'),
                    item.get('timestamp', 'N/A').split(' ')[0],
                    str(item.get('nutrition', {}).get('calories', 'N/A'))
                ])
            
            foods_table = Table(foods_data, colWidths=[2.5 * 1.02, 2 * 1.02, 1.5 * 1.02])
            foods_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            elements.append(foods_table)
        
        # Build PDF
        doc.build(elements)
        buffer.seek(0)
        
        return send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"nutrition_report_{user['email']}.pdf"
        )
    except Exception as e:
        flash(f'Error generating PDF: {str(e)}', 'error')
        return redirect(url_for('profile'))


# ==================== MOBILE APP SYNC APIs ====================

@app.route('/api/generate-token')
def generate_token():
    """Generate API token for mobile app."""
    if not current_user():
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        users = load_users()
        user = current_user()
        email = user['email']
        
        # Initialize api_tokens if not exists
        if 'api_tokens' not in users[email]:
            users[email]['api_tokens'] = []
        
        # Create new token
        token = generate_api_token()
        users[email]['api_tokens'].append({
            'token': token,
            'created': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'device': request.args.get('device', 'Mobile App')
        })
        
        save_users(users)
        
        return jsonify({
            'success': True,
            'token': token,
            'message': 'API token generated. Use this to sync with mobile app.'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/user-data', methods=['GET'])
def api_user_data():
    """Fetch user data for mobile app (requires token)."""
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    
    if not token:
        return jsonify({'error': 'No token provided'}), 401
    
    users = load_users()
    user_email = None
    
    # Find user by token
    for email, user_data in users.items():
        if verify_api_token(token, email):
            user_email = email
            break
    
    if not user_email:
        return jsonify({'error': 'Invalid token'}), 401
    
    user = users[user_email]
    profile = user.get('profile', {})
    
    # Return sanitized user data
    return jsonify({
        'email': user_email,
        'name': user.get('name'),
        'profile': {
            'bmi': profile.get('bmi'),
            'height_cm': profile.get('height_cm'),
            'weight_kg': profile.get('weight_kg'),
            'condition': profile.get('condition'),
            'bmi_category': profile.get('bmi_category'),
            'recommendation': profile.get('recommendation')
        },
        'recent_foods': profile.get('food_classifications', [])[-20:],
        'total_foods_classified': len(profile.get('food_classifications', []))
    })


@app.route('/api/sync-classification', methods=['POST'])
def api_sync_classification():
    """Sync food classification from mobile app."""
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    
    if not token:
        return jsonify({'error': 'No token provided'}), 401
    
    users = load_users()
    user_email = None
    
    # Find user by token
    for email, user_data in users.items():
        if verify_api_token(token, email):
            user_email = email
            break
    
    if not user_email:
        return jsonify({'error': 'Invalid token'}), 401
    
    try:
        data = request.get_json()
        food = data.get('food')
        nutrition = data.get('nutrition', {})
        
        if not food:
            return jsonify({'error': 'Food name required'}), 400
        
        # Add classification
        user = users[user_email]
        if 'profile' not in user:
            user['profile'] = {}
        if 'food_classifications' not in user['profile']:
            user['profile']['food_classifications'] = []
        
        classification = {
            'food': food,
            'nutrition': nutrition,
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'synced_from': 'mobile_app'
        }
        
        user['profile']['food_classifications'].append(classification)
        save_users(users)
        
        return jsonify({'success': True, 'message': 'Food synced successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== SOCIAL MEAL SHARING ====================

@app.route('/social')
def social():
    """View social feed with shared meals."""
    if not current_user():
        return redirect(url_for('login'))
    
    feed = get_social_feed()
    user = current_user()
    
    return render_template('social.html', user=user, feed=feed)


@app.route('/share-meal/<food_name>', methods=['GET', 'POST'])
def share_meal_page(food_name):
    """Share a classified meal on social."""
    if not current_user():
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        visibility = request.form.get('visibility', 'public')
        user = current_user()
        
        # Find the food in user's classifications
        profile = user.get('profile', {})
        nutrition_data = {}
        
        for item in profile.get('food_classifications', []):
            if item.get('food') == food_name:
                nutrition_data = item.get('nutrition', {})
                break
        
        # Add user to social index if not already there
        add_user_to_social_index(user['email'], user['name'])
        
        # Share the meal
        share_id = share_meal(user['email'], food_name, nutrition_data, visibility)
        
        if share_id:
            flash(f'✅ Meal shared successfully! Share ID: {share_id}', 'success')
            return redirect(url_for('social'))
        else:
            flash('❌ Error sharing meal. Please try again.', 'error')
            return redirect(url_for('profile'))
    
    return render_template('share_meal.html', user=current_user(), food_name=food_name)


@app.route('/follow/<user_email>', methods=['POST'])
def follow_user(user_email):
    """Follow another user to see their shared meals."""
    if not current_user():
        return jsonify({'error': 'Not authenticated'}), 401
    
    SOCIAL_FILE = os.path.join(os.path.dirname(__file__), 'social_users.json')
    
    try:
        with open(SOCIAL_FILE, 'r', encoding='utf-8') as f:
            social_data = json.load(f)
        
        current_email = current_user()['email']
        
        if user_email not in social_data:
            return jsonify({'error': 'User not found'}), 404
        
        if user_email == current_email:
            return jsonify({'error': 'Cannot follow yourself'}), 400
        
        # Add to following list
        if 'following' not in social_data[current_email]:
            social_data[current_email]['following'] = []
        
        if user_email not in social_data[current_email]['following']:
            social_data[current_email]['following'].append(user_email)
        
        # Add to followers list
        if 'followers' not in social_data[user_email]:
            social_data[user_email]['followers'] = []
        
        if current_email not in social_data[user_email]['followers']:
            social_data[user_email]['followers'].append(current_email)
        
        with open(SOCIAL_FILE, 'w', encoding='utf-8') as f:
            json.dump(social_data, f, indent=2)
        
        return jsonify({'success': True, 'message': f'Now following {user_email}'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/like-meal/<meal_id>', methods=['POST'])
def like_meal(meal_id):
    """Like a shared meal."""
    if not current_user():
        return jsonify({'error': 'Not authenticated'}), 401
    
    SOCIAL_FILE = os.path.join(os.path.dirname(__file__), 'social_users.json')
    
    try:
        with open(SOCIAL_FILE, 'r', encoding='utf-8') as f:
            social_data = json.load(f)
        
        # Find the meal and increment like count
        for user_email, user_data in social_data.items():
            for meal in user_data.get('shared_meals', []):
                if meal.get('id') == meal_id:
                    meal['likes'] = meal.get('likes', 0) + 1
                    
                    with open(SOCIAL_FILE, 'w', encoding='utf-8') as f:
                        json.dump(social_data, f, indent=2)
                    
                    return jsonify({'success': True, 'likes': meal['likes']})
        
        return jsonify({'error': 'Meal not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/image')
def image1():
    if not current_user():
        return redirect(url_for('login'))
    return render_template("image.html", user=current_user())

@app.route('/imageprediction')
def imageprediction():
    if not current_user():
        return redirect(url_for('login'))
    # template imageprediction.html does not exist in this project; fallback to image.html
    return render_template('image.html', user=current_user())


@app.route('/predict', methods=['POST'])
def launch():
    if not current_user():
        return jsonify({'error': 'Authentication required'}), 401

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    f = request.files['file']
    if f.filename == '':
        return jsonify({'error': 'Empty file name provided'}), 400

    try:
        basepath = os.path.dirname(__file__)
        filepath = os.path.join(basepath, f.filename)
        f.save(filepath)

        img = image.load_img(filepath, target_size=(64, 64))
        img = img.convert("RGB")
        x=image.img_to_array(img)

# normalize image
        x=x/255.0

        x=np.expand_dims(x,axis=0)
        
        predictions = []

        for i in range(5):
         prediction = model.predict(x)
         predictions.append(prediction)

        prediction = np.mean(predictions, axis=0)

        sorted_pred = np.sort(prediction[0])

        confidence = sorted_pred[-1]
        second_best = sorted_pred[-2]
        pred = np.argmax(prediction, axis=1)

        index=['APPLES','BANANA','ORANGE','PINEAPPLE','WATERMELON']

        if confidence < 0.90 or (confidence - second_best) < 0.20:
            result = "UNKNOWN FRUIT"
            apiResult = []
        else:
            result = str(index[pred[0]])
            apiResult = nutrition(result)

        # User health context for a more personalized recommendation
        user_profile = current_user().get('profile', {}) if current_user() else {}
        user_condition = user_profile.get('condition', '')
        user_bmi = user_profile.get('bmi')

        health_message = recommendation_by_bmi_and_condition(user_bmi, user_condition)
        food_recommendations = food_recommendations_by_health(user_condition, user_bmi)

        final_result = {
            "result" : result,
            "apiResult" : apiResult,
            "bmi": user_bmi,
            "health_message": health_message,
            "food_recommendations": food_recommendations,
            "is_pad": "good" if user_bmi and 18.5 <= user_bmi < 25 else "bad"
        }

        # Save classification to user's food history
        if current_user():
            import datetime
            users = load_users()
            user_email = current_user()['email']
            if 'profile' not in users[user_email]:
                users[user_email]['profile'] = {}
            if 'food_classifications' not in users[user_email]['profile']:
                users[user_email]['profile']['food_classifications'] = []
            
            # Add to history with timestamp
            classification_entry = {
                'food': result,
                'nutrition': apiResult[0] if apiResult else {},
                'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            users[user_email]['profile']['food_classifications'].append(classification_entry)
            
            # Keep only last 50 classifications to prevent file bloat
            if len(users[user_email]['profile']['food_classifications']) > 50:
                users[user_email]['profile']['food_classifications'] = users[user_email]['profile']['food_classifications'][-50:]
            
            save_users(users)

        print(final_result)
        return jsonify(final_result)
    except Exception as e:
        app.logger.exception('Error during prediction')
        return jsonify({'error': str(e)}), 500


def nutrition(food):

    data = {
        "APPLES":{
            "calories":52,
            "carbohydrates_total_g":14,
            "fat_total_g":0.2,
            "fiber_g":2.4,
            "sugar_g":10,
            "potassium_mg":107,
            "sodium_mg":1
        },

        "BANANA":{
            "calories":89,
            "carbohydrates_total_g":23,
            "fat_total_g":0.3,
            "fiber_g":2.6,
            "sugar_g":12,
            "potassium_mg":358,
            "sodium_mg":1
        },

        "ORANGE":{
            "calories":47,
            "carbohydrates_total_g":12,
            "fat_total_g":0.1,
            "fiber_g":2.4,
            "sugar_g":9,
            "potassium_mg":181,
            "sodium_mg":0
        },

        "PINEAPPLE":{
            "calories":50,
            "carbohydrates_total_g":13,
            "fat_total_g":0.1,
            "fiber_g":1.4,
            "sugar_g":10,
            "potassium_mg":109,
            "sodium_mg":1
        },

        "WATERMELON":{
            "calories":30,
            "carbohydrates_total_g":8,
            "fat_total_g":0.2,
            "fiber_g":0.4,
            "sugar_g":6,
            "potassium_mg":112,
            "sodium_mg":1
        }
    }

    return [data.get(food)]

if __name__== "__main__":
    app.run(debug=False)
    
        
        
        