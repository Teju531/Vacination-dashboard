import os
import uuid
import venv
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
from flask_pymongo import PyMongo
from bson.objectid import ObjectId
from twilio.rest import Client
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

# Configuration
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Replace with a secure, random key
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure the upload folder exists
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# MongoDB Configuration
app.config["MONGO_URI"] = "mongodb://localhost:27017/Dashboard"
mongo = PyMongo(app)

users_collection = mongo.db.users
data_collection = mongo.db.data

# Twilio Configuration

import os
TWILIO_SECRET = os.getenv("TWILIO_SECRET")


TWILIO_ACCOUNT_SID = 'your twilio sid'
TWILIO_AUTH_TOKEN = 'your twilio token'
TWILIO_PHONE_NUMBER = 'your twilio phnoe number'
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Helper function to validate file type
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Scheduler Configuration
scheduler = BackgroundScheduler()

@scheduler.scheduled_job('cron', hour=9, minute=0)
def send_vaccine_reminder():
    """Check the database for records with today's date as the next dosage date."""
    today = datetime.today().strftime('%Y-%m-%d')
    persons_data = data_collection.find({'next_dosage_date': today})

    for person in persons_data:
        phone_number = person['phno']
        vaccine_name = person['vaccine_name']

        message = f"Reminder: Your next vaccine dose for {vaccine_name} is due today!"

        # Validate and format phone number
        if not phone_number.startswith('+'):
           phone_number = '+91' + phone_number  # Adjust default country code as needed

        try:
            twilio_client.messages.create(
                body=message,
                from_=TWILIO_PHONE_NUMBER,
                to=phone_number
            )
            print(f"Reminder sent to {phone_number}")
        except Exception as e:
            print(f"Error sending SMS to {phone_number}: {str(e)}")

scheduler.start()

@app.route('/')
def login_redirect():
    """Redirect to login or home based on session."""
    if 'phno' in session:
        return redirect(url_for('home'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login route."""
    if request.method == 'POST':
        phno = request.form['phno']
        pin = request.form['pin']

        user = users_collection.find_one({'phno': phno, 'pin': pin})
        if user:
            session['phno'] = phno
            session['name'] = user['name']
            return redirect(url_for('home'))
        return "Invalid login credentials"

    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    """Signup route."""
    if request.method == 'POST':
        name = request.form['name']
        phno = request.form['phno']
        pin = request.form['pin']

        if users_collection.find_one({'phno': phno}):
            return "Phone number already registered"

        users_collection.insert_one({'name': name, 'phno': phno, 'pin': pin})
        session['phno'] = phno
        session['name'] = name
        return redirect(url_for('home'))

    return render_template('signup.html')

@app.route('/home')
def home():
    """Home route displaying user's vaccine data."""
    if 'phno' not in session or 'name' not in session:
        return redirect(url_for('login'))

    persons_data = [
        {**person, '_id': str(person['_id'])} for person in data_collection.find({'phno': session['phno']})
    ]
    return render_template('home.html', name=session['name'], persons_data=persons_data)

@app.route('/update/<row_id>', methods=['GET', 'POST'])
def update(row_id):
    """Update a vaccine record."""
    if request.method == 'POST':
        updated_data = {
            'person_name': request.form['person_name'],
            'relation': request.form['relation'],
            'vaccine_name': request.form['vaccine_name'],
            'vaccination_date': request.form['vaccination_date'],
            'next_dosage_date': request.form['next_dosage_date'],
            'age': request.form['age']
        }
        data_collection.update_one({'_id': ObjectId(row_id)}, {'$set': updated_data})
        return redirect(url_for('home'))

    row = data_collection.find_one({'_id': ObjectId(row_id)})
    return render_template('update.html', row=row)

@app.route('/add_entry', methods=['POST'])
def add_entry():
    """Add a new vaccine record."""
    if 'phno' not in session:
        return redirect(url_for('login'))

    person_name = request.form['person_name']
    relation = request.form.get('relation')
    vaccine_name = request.form['vaccine_name']
    vaccination_date = request.form['vaccination_date']
    next_dosage_date = request.form.get('next_dosage_date')
    age = request.form['age']

    data_collection.insert_one({
        'phno': session['phno'],
        'person_name': person_name,
        'relation': relation,
        'vaccine_name': vaccine_name,
        'vaccination_date': vaccination_date,
        'next_dosage_date': next_dosage_date,
        'age': age
    })
    return redirect(url_for('home'))

@app.route('/delete_entry/<person_id>', methods=['POST'])
def delete_entry(person_id):
    """Delete a vaccine record."""
    if 'phno' not in session:
        return redirect(url_for('login'))
    data_collection.delete_one({'_id': ObjectId(person_id)})
    return redirect(url_for('home'))

@app.route('/upload/<person_id>', methods=['POST'])
def upload_document(person_id):
    """Upload a document for a vaccine record."""
    if 'phno' not in session:
        return redirect(url_for('login'))

    file = request.files.get('document')
    if file and allowed_file(file.filename):
        filename = f"{uuid.uuid4()}_{secure_filename(file.filename)}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        data_collection.update_one(
            {'_id': ObjectId(person_id)},
            {'$push': {'documents': filename}}
        )
        return redirect(url_for('home'))
    return "Invalid file type. Only PNG, JPG, JPEG, PDF allowed.", 400

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """Serve uploaded files."""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/send_reminder/<person_id>', methods=['POST'])
def send_reminder(person_id):
    """Send a reminder for the person with the given person_id."""
    person = data_collection.find_one({'_id': ObjectId(person_id)})

    if not person:
        return "Person not found", 404

    today = datetime.today().strftime('%Y-%m-%d')
    if person['next_dosage_date'] == today:
        message = f"Reminder: Your next vaccine dose for {person['vaccine_name']} is due today!"

        phone_number = person['phno']
        if not phone_number.startswith('+'):
            phone_number = '+1' + phone_number

        try:
            twilio_client.messages.create(
                body=message,
                from_=TWILIO_PHONE_NUMBER,
                to=phone_number
            )
            print(f"Reminder sent to {phone_number}")
            return f"Reminder sent to {phone_number}"
        except Exception as e:
            print(f"Error sending SMS: {str(e)}")
            return f"Error sending SMS: {str(e)}"
    else:
        return "No reminder needed today"

@app.route('/adult_vacine')
def adult_vacine():
    return render_template('adult_vacine.html')

@app.route('/what_are')
def what_are():
    return render_template('what_are.html')

@app.route('/infant_vaccine')
def infant_vaccine():
    return render_template('infant_vaccine.html')

@app.route('/mother_to_be')
def mother_to_be():
    return render_template('mother_to_be.html')


if __name__ == "__main__":
    app.run(debug=True, port=5002)
