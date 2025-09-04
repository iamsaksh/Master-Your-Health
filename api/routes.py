import pyodbc
import os
import openai
from flask import Flask, request, jsonify,session,Blueprint
from flask_cors import CORS
import bcrypt  # For password hashing
import base64
import matplotlib
matplotlib.use('Agg')
import pandas as pd
import io
from PIL import Image
from supabase import create_client


supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")

supabase = create_client(supabase_url, supabase_key)

def encode_image_to_base64(image_binary):
    """Encodes image binary data to a base64 string."""
    return base64.b64encode(image_binary).decode('utf-8')
# Get OpenAI API Key from environment
openai.api_key = os.getenv("OPENAI_API_KEY")
if not openai.api_key:
    raise ValueError("❌ OpenAI API Key not found! Set the 'OPENAI_API_KEY' environment variable.")

app = Blueprint('api', __name__)
CORS(app)

app.secret_key = 'your_secret_key'  # Use a strong, random string

# Detect environment (LOCAL or AZURE)
ENV = os.getenv("ENVIRONMENT", "LOCAL")

if ENV == "LOCAL":
    # Local SQL Server using Windows Auth
    DB_SERVER = r'localhost\SQLEXPRESS'
    DB_DATABASE = 'UserDatabase'
    conn_str = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={DB_SERVER};DATABASE={DB_DATABASE};Trusted_Connection=yes;"
    )
else:
    # Azure SQL Server - use full credentials from environment
    DB_SERVER = os.getenv("AZURE_SQL_SERVER")  # e.g. my-sqlserver.database.windows.net
    DB_DATABASE = os.getenv("AZURE_SQL_DB")    # e.g. HealthPackageDB
    DB_USER = os.getenv("AZURE_SQL_USER")      # e.g. sqladmin
    DB_PASS = os.getenv("AZURE_SQL_PASS")      # Strong password

    conn_str = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={DB_SERVER};DATABASE={DB_DATABASE};"
        f"UID={DB_USER};PWD={DB_PASS};Encrypt=yes;TrustServerCertificate=no;"
    )


# Function to connect to SQL Server
def get_db_connection():
    try:
        conn = pyodbc.connect(conn_str, autocommit=True)
        return conn
    except Exception as e:
        print("Database Connection Error:", str(e))
        return None
    
#function get openai response
def get_openai_response(prompt):
    """Fetch response from OpenAI API (Safe version with logging)."""
    try:
        # Get API key
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("❌ API key not found. Please check .env file.")

        # Initialize client
        client = openai.OpenAI(api_key=api_key)

        # Send request
        print("📡 Sending request to OpenAI...")
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a medical expert."},
                {"role": "user", "content": prompt}
            ]
        )
        print("✅ Response received!")
        return response.choices[0].message.content

    except Exception as e:
        print("❌ OpenAI API Error:", str(e))
        # Log it to file for the .exe version
        with open("log.txt", "a") as f:
            f.write("OpenAI API Error:\n")
            f.write(str(e) + "\n\n")
        return None
    
# Hash password function
def hash_password(password):
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

# Function to generate sequential PatientID
def generate_patient_id(cursor):
    cursor.execute("SELECT TOP 1 patient_id FROM Users WHERE patient_id LIKE 'MYH%' ORDER BY patient_id DESC")
    last_id = cursor.fetchone()
    
    if last_id and last_id[0]:
        last_num = int(last_id[0][3:])  # Extract number from 'MYHXXXXX'
        new_num = last_num + 1
    else:
        new_num = 239  # Start from MYH00239
    
    return f"MYH{new_num:05d}"  # Ensures 5-digit format

# API Endpoint: User Registration
@app.route('/register', methods=['POST'])
def register_user():
    data = request.json

    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    dob = data.get('dob', '').strip()
    location = data.get('location', '').strip()
    occupation = data.get('occupation', '').strip()
    phone_number = data.get('phone', '').strip()

    if not all([name, dob, location, occupation, email, phone_number]):
        return jsonify({"error": "All fields are required"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cursor = conn.cursor()
        
        # Check if user with same Name and Email exists
        cursor.execute("SELECT COUNT(*) FROM Users WHERE Name = ? AND Email = ?", (name, email))
        if cursor.fetchone()[0] > 0:
            return jsonify({"error": "User with this name and email already exists"}), 400

        # Generate sequential PatientID
        patient_id = generate_patient_id(cursor)
        
        # Generate Unique Username
        base_username = f"{name}{dob.replace('-', '')}".replace(" ", "").lower()
        username = base_username
        count = 1
        
        while True:
            cursor.execute("SELECT COUNT(*) FROM Users WHERE Username = ?", (username,))
            if cursor.fetchone()[0] == 0:
                break
            username = f"{base_username}{count}"
            count += 1

        # Generate & Hash Password
        raw_password = f"{location}{name}{dob.replace('-', '')}".replace(" ", "")
        hashed_password = hash_password(raw_password)
        
        # Insert into Database
        cursor.execute("""
            INSERT INTO Users (patient_id, Name, PhoneNumber, Email, DOB, Location, Occupation, Username, Password)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (patient_id, name, phone_number, email, dob, location, occupation, username, hashed_password))
        conn.commit()
        
        return jsonify({
            "message": "User registered successfully",
            "patient_id": patient_id,
            "username": username,
            "email": email,
            "password": raw_password  # Only for initial display
        })

    except Exception as e:
        print("Error in Registration:", str(e))
        return jsonify({"error": "Database error occurred"}), 500
    
    finally:
        conn.close()

# API Endpoint: Search Users by Name
@app.route('/search', methods=['GET'])
def search_users():
    query = request.args.get('query', '').strip()

    if not query:
        return jsonify({"error": "Query is required"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cursor = conn.cursor()

        # Try to match with Name, PhoneNumber, or patient_id
        sql = """
            SELECT patient_id, Name, PhoneNumber 
            FROM Users 
            WHERE Name LIKE ? 
               OR PhoneNumber LIKE ? 
               OR CAST(patient_id AS NVARCHAR) LIKE ?
        """
        params = (f"%{query}%", f"%{query}%", f"%{query}%")

        cursor.execute(sql, params)

        results = [
            {"patient_id": row.patient_id, "name": row.Name, "phone_number": row.PhoneNumber}
            for row in cursor.fetchall()
        ]

        return jsonify(results)

    except Exception as e:
        print("Error in Searching:", str(e))
        return jsonify({"error": "Database error occurred"}), 500

    finally:
        conn.close()


# API Endpoint: Get User Details
@app.route('/patients/<string:patient_id>', methods=['GET'])
def get_user_details(patient_id):
    print(f"🔍 Received patient_id: {repr(patient_id)}") # Debugging

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cursor = conn.cursor()
        query = "SELECT Name, DOB, Location, Occupation, PhoneNumber FROM Users WHERE patient_id = ?"
        print(f"Executing query: {query} with patient_id: {patient_id}")  # Debugging

        cursor.execute(query, (patient_id,))
        row = cursor.fetchone()

        print(f"Query Result: {row}")  # Debugging

        if not row:
            return jsonify({"error": "User not found"}), 404

        return jsonify({
            "name": row[0],
            "dob": row[1],
            "location": row[2],
            "occupation": row[3],
            "phone_number": row[4]
        })

    except Exception as e:
        print("Error Fetching User Details:", str(e))
        return jsonify({"error": "Database error occurred"}), 500

    finally:
        conn.close()
@app.route('/patients/<string:patient_id>', methods=['POST'])
def update_user_details(patient_id):
    try:
        updated_data = request.get_json()  # Get the updated data from the request body
        name = updated_data.get('name')
        dob = updated_data.get('dob')
        location = updated_data.get('location')
        occupation = updated_data.get('occupation')

        # Check if any required field is missing
        if not name or not dob or not location or not occupation:
            return jsonify({"error": "All fields are required"}), 400

        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500

        cursor = conn.cursor()
        update_query = """
            UPDATE Users
            SET Name = ?, DOB = ?, Location = ?, Occupation = ?
            WHERE patient_id = ?
        """
        cursor.execute(update_query, (name, dob, location, occupation, patient_id))
        conn.commit()

        return jsonify({"status": "success", "message": "Patient details updated successfully"})

    except Exception as e:
        print("Error Updating User Details:", str(e))
        return jsonify({"error": "Database error occurred"}), 500

    finally:
        conn.close()

# API Endpoint: Login
@app.route('/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    if not username or not password:
        return jsonify({"success": False, "message": "Username and password are required"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"success": False, "message": "Database connection failed"}), 500

    try:
        cursor = conn.cursor()
        
        # Fetch patient_id and password from the database
        cursor.execute("SELECT patient_id, password FROM Users WHERE username = ?", (username,))
        row = cursor.fetchone()

        if not row:
            return jsonify({"success": False, "message": "Invalid username or password"}), 401

        patient_id, stored_hashed_password = row  # Extract both patient_id and password

        # Verify password using bcrypt
        if bcrypt.checkpw(password.encode('utf-8'), stored_hashed_password.encode('utf-8')):
            session['user'] = username  # Store username in session
            session['patient_id'] = patient_id  # Store patient ID
            session.permanent = True  # Keep session active
            return jsonify({"success": True, "patient_id": patient_id, "message": "Login successful"})
        else:
            return jsonify({"success": False, "message": "Invalid username or password"}), 401

    except Exception as e:
        print("Login Error:", str(e))
        return jsonify({"success": False, "message": "Database error occurred"}), 500

    finally:
        conn.close()

# API Endpoint : Dashboard Session
@app.route('/dashboard', methods=['GET'])
def dashboard():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    return jsonify({"message": f"Welcome, {session['user']}!"})

# API Endpoint : Logout
@app.route('/logout', methods=['POST'])
def logout():
    session.clear()  # Clear session data
    return jsonify({"message": "Logged out successfully"})


# API Endpoint: Store or Update Patient Medical Information
@app.route('/patients/<string:patient_id>/info', methods=['POST'])
def store_patient_info(patient_id):  
    data = request.json
    print("Received data:", data)  # Debug log to check if data is received correctly.

    # Extract values from the data
    weight = data.get('weight')
    height = data.get('height')
    blood_group = data.get('blood_group', '').strip()
    medical_history = data.get('medical_history', '').strip()
    medical_prescription = data.get('medical_prescription', '').strip()
    structured_diet_chart = data.get('structured_diet_chart', '').strip()
    diet_prescription = data.get('diet_prescription', '').strip()
    exercise_prescription = data.get('exercise_prescription', '').strip()
    current_health_conditions = data.get('current_health_conditions', '').strip()
    treatment_details = data.get('treatment_details', '').strip()
    fitness_goal = data.get('fitness_goal', '').strip()
    allergies = data.get('allergies', '').strip()
    smoking = data.get('smoking', '').strip()
    drinking = data.get('drinking', '').strip()
    sleep_pattern = data.get('sleep_pattern', '').strip()

    if weight == '':
        weight = 0.0  # Or use a default value, e.g., 0.0
    if height == '':
        height = 0.0  # Or use a default value, e.g., 0.0
    if not patient_id:
        return jsonify({"error": "Patient ID is required"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cursor = conn.cursor()

        # Check if patient exists
        cursor.execute("SELECT 1 FROM Users WHERE patient_id = ?", (patient_id,))
        if not cursor.fetchone():
            return jsonify({"error": "Patient not found"}), 404

        # Check if medical info already exists
        cursor.execute("SELECT 1 FROM PatientInformation WHERE patient_id = ?", (patient_id,))
        existing_info = cursor.fetchone()

        if existing_info:
            # Update existing info while keeping old values if new ones are missing
            cursor.execute("""
                UPDATE PatientInformation
                SET 
                    weight = COALESCE(?, weight), 
                    height = COALESCE(?, height), 
                    blood_group = COALESCE(NULLIF(?, ''), blood_group), 
                    medical_history = COALESCE(NULLIF(?, ''), medical_history), 
                    medical_prescription = COALESCE(NULLIF(?, ''), medical_prescription), 
                    diet_prescription = COALESCE(NULLIF(?, ''), diet_prescription), 
                    structured_diet_chart = COALESCE(NULLIF(?, ''), structured_diet_chart),
                    exercise_prescription = COALESCE(NULLIF(?, ''), exercise_prescription),
                    current_health_conditions = COALESCE(NULLIF(?, ''), current_health_conditions),
                    treatment_details = COALESCE(NULLIF(?, ''), treatment_details),
                    fitness_goal = COALESCE(NULLIF(?, ''), fitness_goal),
                    allergies = COALESCE(NULLIF(?, ''), allergies),
                    smoking = COALESCE(NULLIF(?, ''), smoking),
                    drinking = COALESCE(NULLIF(?, ''), drinking),
                    sleep_pattern = COALESCE(NULLIF(?, ''), sleep_pattern)
                WHERE patient_id = ?
            """, (
                weight, height, blood_group, medical_history, medical_prescription, diet_prescription,structured_diet_chart, exercise_prescription, 
                current_health_conditions, treatment_details, fitness_goal, allergies, smoking, drinking, sleep_pattern, patient_id
            ))

        else:
            # Insert new record
           cursor.execute("""
                INSERT INTO PatientInformation (patient_id, weight, height, blood_group, 
                    medical_history, medical_prescription, diet_prescription,structured_diet_chart, exercise_prescription,
                    current_health_conditions, treatment_details, fitness_goal, allergies,
                    smoking, drinking, sleep_pattern)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,?)
            """, (
                patient_id, weight, height, blood_group, medical_history, medical_prescription, diet_prescription, structured_diet_chart,exercise_prescription,
                current_health_conditions, treatment_details, fitness_goal, allergies, smoking, drinking, sleep_pattern
            ))


        conn.commit()
        return jsonify({"message": "Patient information saved successfully"})

    except Exception as e:
        print("Error storing patient info:", str(e))
        return jsonify({"error": "Database error occurred"}), 500

    finally:
        conn.close()

@app.route('/patients/<string:patient_id>/visits', methods=['POST'])
def add_patient_visit(patient_id):
    data = request.json

    weight = data.get('weight')
    height = data.get('height')
    blood_pressure = data.get('blood_pressure', '').strip()
    medical_prescription = data.get('medical_prescription', '').strip()
    diet_prescription = data.get('diet_prescription', '').strip()
    exercise_prescription = data.get('exercise_prescription', '').strip()
    notes = data.get('notes', '').strip()

    if not patient_id:
        return jsonify({"error": "Patient ID is required"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cursor = conn.cursor()

        # Check if patient exists
        cursor.execute("SELECT 1 FROM Users WHERE patient_id = ?", (patient_id,))
        if not cursor.fetchone():
            return jsonify({"error": "Patient not found"}), 404

        # Insert visit record
        cursor.execute("""
            INSERT INTO PatientVisits (
                patient_id, weight, height, blood_pressure,
                medical_prescription, diet_prescription, exercise_prescription, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (patient_id, weight, height, blood_pressure,
              medical_prescription, diet_prescription, exercise_prescription, notes))

        conn.commit()
        return jsonify({"message": "Visit added successfully"})

    except Exception as e:
        print("Error adding patient visit:", str(e))
        return jsonify({"error": "Database error occurred"}), 500

    finally:
        conn.close()

@app.route('/patients/<string:patient_id>/visits', methods=['GET'])
def get_patient_visits(patient_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT visit_id, patient_id, visit_date, weight, height, blood_pressure,
                    medical_prescription, diet_prescription, exercise_prescription, notes
            FROM PatientVisits
            WHERE patient_id = ?
            ORDER BY visit_date DESC
        """, (patient_id,))

        columns = [column[0] for column in cursor.description]
        visits = [dict(zip(columns, row)) for row in cursor.fetchall()]

        if not visits:
            return jsonify({"error": "No visits found for this patient"}), 404

        return jsonify(visits)

    except Exception as e:
        print("Error fetching patient visits:", str(e))
        return jsonify({"error": "Database error occurred"}), 500

    finally:
        conn.close()

# API Endpoint: Get Patient Medical Information
@app.route('/patients/<string:patient_id>/info', methods=['GET'])
def get_patient_info(patient_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cursor = conn.cursor()

        # Fetch patient medical information
        cursor.execute("""
            SELECT weight, height, blood_group, medical_history, 
                   medical_prescription, diet_prescription, structured_diet_chart, exercise_prescription,current_health_conditions,treatment_details,fitness_goal,allergies,smoking,drinking,sleep_pattern
            FROM PatientInformation
            WHERE patient_id = ?
        """, (patient_id,))
        
        row = cursor.fetchone()

        if not row:
            return jsonify({"error": "No medical information found for this patient"}), 404

        return jsonify({
            "weight": row[0],
            "height": row[1],
            "blood_group": row[2],
            "medical_history": row[3],
            "medical_prescription": row[4],
            "diet_prescription": row[5],
            "structured_diet_chart":row[6],
            "exercise_prescription": row[7],
            "current_health_conditions": row[8],
            "treatment_details": row[9],
            "fitness_goal": row[10],
            "allergies": row[11],
            "smoking": row[12],
            "drinking": row[13],
            "sleep_pattern": row[14],
        })

    except Exception as e:
        print("Error fetching patient info:", str(e))
        return jsonify({"error": "Database error occurred"}), 500

    finally:
        conn.close()

# API Endpoint: Store 3-Day Recall Meal Data
@app.route('/patients/<string:patient_id>/recall', methods=['POST'])
def store_3_day_recall(patient_id):
    data = request.json

    # Combine all meals for each day into a single string
    day1_meal = " | ".join([
        data.get('day1_breakfast', ''), 
        data.get('day1_morning_snack', ''), 
        data.get('day1_lunch', ''), 
        data.get('day1_afternoon_snack', ''), 
        data.get('day1_dinner', ''), 
        data.get('day1_evening_snack', '')
    ]).strip()

    day2_meal = " | ".join([
        data.get('day2_breakfast', ''), 
        data.get('day2_morning_snack', ''), 
        data.get('day2_lunch', ''), 
        data.get('day2_afternoon_snack', ''), 
        data.get('day2_dinner', ''), 
        data.get('day2_evening_snack', '')
    ]).strip()

    day3_meal = " | ".join([
        data.get('day3_breakfast', ''), 
        data.get('day3_morning_snack', ''), 
        data.get('day3_lunch', ''), 
        data.get('day3_afternoon_snack', ''), 
        data.get('day3_dinner', ''), 
        data.get('day3_evening_snack', '')
    ]).strip()

    if not patient_id:
        return jsonify({"error": "Patient ID is required"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cursor = conn.cursor()

        # Check if patient exists
        cursor.execute("SELECT 1 FROM Users WHERE patient_id = ?", (patient_id,))
        if not cursor.fetchone():
            return jsonify({"error": "Patient not found"}), 404

        # Check if data already exists for the patient
        cursor.execute("SELECT 1 FROM PatientActivityData WHERE patient_id = ?", (patient_id,))
        existing_data = cursor.fetchone()

        if existing_data:
            # Update existing data
            cursor.execute("""
                UPDATE PatientActivityData 
                SET day1_meal = ?, day2_meal = ?, day3_meal = ?
                WHERE patient_id = ?
            """, (day1_meal, day2_meal, day3_meal, patient_id))
        else:
            # Insert new data
            cursor.execute("""
                INSERT INTO PatientActivityData 
                (patient_id, day1_meal, day2_meal, day3_meal)
                VALUES (?, ?, ?, ?)
            """, (patient_id, day1_meal, day2_meal, day3_meal))

        conn.commit()
        return jsonify({"message": "3-Day Recall data saved successfully"})

    except Exception as e:
        print("Error storing 3-Day Recall data:", str(e))
        return jsonify({"error": "Database error occurred"}), 500

    finally:
        conn.close()

#API Endpoint: Get 3 day recall
@app.route('/patients/<string:patient_id>/getDiet', methods=['GET'])
def get_3_day_recall(patient_id):
    print(f"🟢 Fetching Recall Data for: {repr(patient_id)}")  # Debugging

    conn = get_db_connection()
    if not conn:
        print("❌ Database connection failed")
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT day1_meal, day2_meal, day3_meal
            FROM PatientActivityData
            WHERE patient_id = ?
        """, (patient_id,))

        row = cursor.fetchone()
        print(f"🔍 Query Result: {row}")  # Debugging

        if row:
            print(f"✅ Found Data: Day 1: {row[0]}, Day 2: {row[1]}, Day 3: {row[2]}")
            return jsonify({
                "day1_meal": row[0].replace("\n", " ").strip() if row[0] else "",
                "day2_meal": row[1].replace("\n", " ").strip() if row[1] else "",
                "day3_meal": row[2].replace("\n", " ").strip() if row[2] else "",
            })

        else:
            print("❌ No recall data found for this patient")
            return jsonify({"day1_meal": "", "day2_meal": "", "day3_meal": ""}), 200

    except Exception as e:
        print("❌ Error fetching recall data:", str(e))
        return jsonify({"error": "Database error occurred"}), 500

    finally:
        conn.close()

# API Endpoint: Store IPAQ MET Data in PatientActivityData
@app.route('/patients/<string:patient_id>/ipaq', methods=['POST'])
def store_ipaq_data(patient_id):
    data = request.json
    print(f"🔍 Received IPAQ Data for {patient_id}: {data}")  # Debugging log
    total_met = data.get("ipaQ_total_met", 0)
    vigorous_met = data.get("ipaQ_vigorous_met", 0)
    moderate_met = data.get("ipaQ_moderate_met", 0)
    walking_met = data.get("ipaQ_walking_met", 0)
    activity_category = data.get("ipaQ_category", "").strip()

    if not patient_id:
        return jsonify({"error": "Patient ID is required"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cursor = conn.cursor()

        # Check if patient exists
        cursor.execute("SELECT 1 FROM Users WHERE patient_id = ?", (patient_id,))
        if not cursor.fetchone():
            return jsonify({"error": "Patient not found"}), 404

        # Check if an entry already exists for the patient
        cursor.execute("SELECT 1 FROM PatientActivityData WHERE patient_id = ?", (patient_id,))
        existing_data = cursor.fetchone()

        if existing_data:
            # Update existing IPAQ MET data
            cursor.execute("""
                UPDATE PatientActivityData 
                SET ipaQ_vigorous_met = ?, ipaQ_moderate_met = ?, ipaQ_walking_met = ?, ipaQ_total_met = ?, ipaQ_category = ?
                WHERE patient_id = ?
            """, (vigorous_met, moderate_met, walking_met, total_met, activity_category, patient_id))
        else:
            # Insert new record with IPAQ MET data
            cursor.execute("""
                INSERT INTO PatientActivityData 
                (patient_id, ipaQ_vigorous_met, ipaQ_moderate_met, ipaQ_walking_met, ipaQ_total_met, ipaQ_category)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (patient_id, vigorous_met, moderate_met, walking_met, total_met, activity_category))

        conn.commit()
        print("✅ IPAQ Data Successfully Stored")  # Debugging confirmation
        return jsonify({"message": "IPAQ data saved successfully"})

    except Exception as e:
        print("Error storing IPAQ data:", str(e))
        return jsonify({"error": "Database error occurred"}), 500

    finally:
        conn.close()

#API Endpoint : Generate Diet
@app.route('/patients/<string:patient_id>/generate-diet', methods=['POST'])
def generate_and_store_diet(patient_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cursor = conn.cursor()

        # Fetch patient details including 3-day recall data
        cursor.execute("""
            SELECT weight, height, medical_history, current_health_conditions, treatment_details,
                   fitness_goal, allergies, smoking, drinking, day1_meal, day2_meal, day3_meal
            FROM PatientInformation
            JOIN PatientActivityData ON PatientInformation.patient_id = PatientActivityData.patient_id
            WHERE PatientInformation.patient_id = ?
        """, (patient_id,))
        
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "Patient data not found"}), 404

        weight, height, medical_history, current_health_conditions, treatment_details, fitness_goal, \
        allergies, smoking, drinking, day1_meal, day2_meal, day3_meal = row

        # Prompt for Diet Plan (Analyzing 3-Day Recall)
        diet_prompt = f"""
        Based on the patient's 3-day meal recall, analyze their **food preferences** and recommend a **healthy meal plan**.

        **Patient Details:**
        - Weight: {weight} kg
        - Height: {height} cm
        - Medical History: {medical_history}
        - Current health conditions: {current_health_conditions}
        - Treatment Details: {treatment_details}
        - Fitness Goal: {fitness_goal}
        - Allergies: {allergies}
        - Smoking: {smoking}
        - Drinking: {drinking}

        **3-Day Meal Recall:**
        - **Day 1:** {day1_meal}
        - **Day 2:** {day2_meal}
        - **Day 3:** {day3_meal}

        **Analyze:**
        - Identify **common patterns** (e.g., high carb, protein-rich, vegetarian, fast food, home-cooked meals).
        - Consider the patient's **likes & dislikes**.
        - Suggest **healthier alternatives** based on their preferences.
        - Keep in mind their allergies and fitness goals.
        - Analyze the amout of calories intake done by patient. 

        **Recommend:**
        - **Breakfast:** Suggest meals that align with the patient's tastes but are healthier.
        - **Lunch:** Suggest balanced meals that match their dietary habits.
        - **Dinner:** Suggest meals that maintain variety while staying nutritious.
        - **Snacks:** Recommend healthy snacks similar to what they already eat.

        Keep the recommendations **realistic** and based on their existing eating habits.
        And mention calories the patient consumed(approximate is fine). 
        And reccomend how much the patient should consume for accomplishing their fitness goal.
        Take in note their medical history , health conditions etc.
        """

        # Get AI response for general diet p lan
        diet_plan = get_openai_response(diet_prompt)
        if not diet_plan:
            return jsonify({"error": "Failed to generate diet plan"}), 500

        print("\n🔍 Generated Diet Plan for Patient:", patient_id)
        print(diet_plan)

        # SECOND PROMPT – Generate Day-wise diet plan from previous output
        structured_diet_prompt = f"""
        Based on the following diet plan generated for the patient, convert it into a clear **day-wise diet chart** for one week (Day 1 to Day 7).I want each day meal(no responses like day 1 - day 3 or anything like that). Ensure that the chart includes:

        - **Breakfast**
        - **Mid-morning snack**
        - **Lunch**
        - **Evening snack**
        - **Dinner**
        *Note: You can even reccomend alternates for each food you reccomend. And try to stay true to the patients general diet(based on what type of food patient likes)

        The plan should be simple, practical, and in line with the recommendations. Include calories nutritional data and quantity too.
        In the end also give total calories consumed per day. I want each day's separate plan.Not genereic and try not be repetitive. Based on what cuisine and regional food patient likes only reccomend that.
        The point is to make the diet plan such that patient can eat healthy while not diverting from their normal eating habits.

        **Reference Diet Plan:**
        {diet_plan}
        """

        # Get AI response for structured, day-wise plan
        structured_diet_chart = get_openai_response(structured_diet_prompt)
        if not structured_diet_chart:
            return jsonify({"error": "Failed to generate structured diet chart"}), 500

        print("\n📅 Structured Day-wise Diet Plan:")
        print(structured_diet_chart)

        # Store both in database
        cursor.execute("""
            UPDATE PatientInformation
            SET diet_prescription = ?, structured_diet_chart = ?
            WHERE patient_id = ?
        """, (diet_plan, structured_diet_chart, patient_id))

        conn.commit()

        # Return both to frontend
        return jsonify({
            "diet_prescription": diet_plan,
            "structured_diet_chart": structured_diet_chart
        })

    except Exception as e:
        print("❌ Error generating diet plan:", str(e))
        return jsonify({"error": "Error generating diet plan"}), 500

    finally:
        conn.close()

#API Endppint: Exercise
@app.route('/patients/<string:patient_id>/generate-exercise', methods=['POST'])
def generate_and_store_exercise(patient_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cursor = conn.cursor()
        
        # Fetch patient details
        cursor.execute("""
            SELECT weight, height, medical_history,fitness_goal,smoking,drinking,sleep_pattern, ipaQ_total_met, ipaQ_category,ipaQ_walking_met
            FROM PatientInformation
            JOIN PatientActivityData ON PatientInformation.patient_id = PatientActivityData.patient_id
            WHERE PatientInformation.patient_id = ?
        """, (patient_id,))
        
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "Patient data not found"}), 404

        weight, height, medical_history,fitness_goal,smoking,drinking,sleep_pattern, total_met, activity_category,walking_met = row

        # Prompt for Exercise Plan
        exercise_prompt = f"""
        Generate a **personalized exercise plan** for a patient with the following details:
        - Weight: {weight} kg
        - Height: {height} cm
        - Medical History: {medical_history}
        - Physical Activity Level: {activity_category} (MET Score: {total_met})
        - Walking MET : {walking_met}
        - Fitness Goal : {fitness_goal}
        - Smoking : {smoking}
        - Drinking : {drinking}
        - Sleep Pattern : {sleep_pattern}

        Please suggest a **weekly exercise routine**, including:
        - **Cardio Recommendations** (walking, jogging, cycling, etc.)
        - **Strength Training** (weight lifting, resistance exercises)
        - **Flexibility & Mobility Exercises**
        - **Duration and Frequency per Week**
        - Talk about reps and sets.
        
        Ensure the plan is **safe and suitable** based on their health condition, fitness goal,met values, health history and their bmi(height and weight).
        """

        # Fetch AI-generated response
        exercise_plan = get_openai_response(exercise_prompt)

        if not exercise_plan:
            return jsonify({"error": "Failed to generate exercise plan"}), 500

        # Debugging: Print in terminal
        print("\n🔍 Generated Exercise Plan for Patient:", patient_id)
        print(exercise_plan)

        # Store in database
        cursor.execute("""
            UPDATE PatientInformation
            SET exercise_prescription = ?
            WHERE patient_id = ?
        """, (exercise_plan, patient_id))
        
        conn.commit()

        # Return generated exercise plan immediately
        return jsonify({"exercise_prescription": exercise_plan})

    except Exception as e:
        print("❌ Error generating exercise plan:", str(e))
        return jsonify({"error": "Error generating exercise plan"}), 500

    finally:
        conn.close()

# API Endpoint: Store Patient Meal Tracking Data (Date-wise)
@app.route('/patients/<string:patient_id>/track_meals', methods=['POST'])
def store_patient_meals(patient_id):
    data = request.json
    
    # 🔹 Debugging: Log received request payload
    print("📥 Received Request Data:", data)
    meal_date = data.get("meal_date")
    breakfast = data.get("breakfast", "").strip()
    lunch = data.get("lunch", "").strip()
    dinner = data.get("dinner", "").strip()
    snacks = data.get("snacks", "").strip()

    if not patient_id or not meal_date:
        return jsonify({"error": "Patient ID and meal date are required"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cursor = conn.cursor()

        # Check if patient exists
        cursor.execute("SELECT 1 FROM Users WHERE patient_id = ?", (patient_id,))
        if not cursor.fetchone():
            return jsonify({"error": "Patient not found"}), 404

        # Check if meal data already exists for this date
        cursor.execute("""
            SELECT 1 FROM PatientMealTracking WHERE patient_id = ? AND meal_date = ?
        """, (patient_id, meal_date))
        existing_entry = cursor.fetchone()

        if existing_entry:
            # Update meal entry
            cursor.execute("""
                UPDATE PatientMealTracking
                SET breakfast = ?, lunch = ?, dinner = ?, snacks = ?
                WHERE patient_id = ? AND meal_date = ?
            """, (breakfast, lunch, dinner, snacks, patient_id, meal_date))
        else:
            # Insert new meal entry
            cursor.execute("""
                INSERT INTO PatientMealTracking (patient_id, meal_date, breakfast, lunch, dinner, snacks)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (patient_id, meal_date, breakfast, lunch, dinner, snacks))

        conn.commit()
        return jsonify({"message": "Meal tracking data saved successfully"})

    except Exception as e:
        print("❌ Error storing meal data:", str(e))
        return jsonify({"error": "Database error occurred"}), 500

    finally:
        conn.close()

#API-Endpoint : Tracking exercise
@app.route('/patients/<string:patient_id>/track_exercise', methods=['POST'])
def track_or_update_exercise(patient_id):
    data = request.json
    exercises = data.get("exercises")

    if not exercises or not isinstance(exercises, list):
        return jsonify({"error": "List of exercises is required"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cursor = conn.cursor()

        # Validate patient exists
        cursor.execute("SELECT 1 FROM Users WHERE patient_id = ?", (patient_id,))
        if not cursor.fetchone():
            return jsonify({"error": "Patient not found"}), 404

        for ex in exercises:
            name = ex.get("exercise_name", "").strip()
            duration = ex.get("duration_minutes")
            date = ex.get("exercise_date")

            if not name or not duration or not date:
                continue  # skip invalid

            # Check if entry exists
            cursor.execute("""
                SELECT 1 FROM PatientExerciseTracking 
                WHERE patient_id = ? AND exercise_name = ? AND exercise_date = ?
            """, (patient_id, name, date))
            exists = cursor.fetchone()

            if exists:
                # Update
                cursor.execute("""
                    UPDATE PatientExerciseTracking
                    SET duration_minutes = ?
                    WHERE patient_id = ? AND exercise_name = ? AND exercise_date = ?
                """, (duration, patient_id, name, date))
            else:
                # Insert
                cursor.execute("""
                    INSERT INTO PatientExerciseTracking 
                    (patient_id, exercise_name, duration_minutes, exercise_date)
                    VALUES (?, ?, ?, ?)
                """, (patient_id, name, duration, date))

        conn.commit()
        return jsonify({"message": "Exercise data stored/updated successfully"})

    except Exception as e:
        print("❌ Error:", e)
        return jsonify({"error": "Database error"}), 500

    finally:
        conn.close()

import matplotlib
matplotlib.use('Agg')  # Ensure the use of a non-GUI backend for Matplotlib

@app.route('/patients/<patient_id>/analyze_meals', methods=['POST'])
def analyze_meals(patient_id):
    try:
        import matplotlib.pyplot as plt
        import pandas as pd
        import io
        from PIL import Image
        import base64

        # Establish DB connection
        conn = get_db_connection()
        cursor = conn.cursor()

        # 1. Fetch diet prescription
        cursor.execute("SELECT diet_prescription FROM PatientInformation WHERE patient_id = ?", (patient_id,))
        diet_prescription = cursor.fetchone()

        if not diet_prescription:
            return jsonify({"error": "No diet prescription found for this patient."}), 404

        diet_prescription = diet_prescription[0]

        # 2. Fetch meal tracking data
        cursor.execute("SELECT meal_date, breakfast, lunch, dinner, snacks FROM PatientMealTracking WHERE patient_id = ?", (patient_id,))
        meal_logs = cursor.fetchall()

        if not meal_logs:
            return jsonify({"error": "No meal tracking data found for this patient."}), 404

        meal_data = []
        for meal in meal_logs:
            meal_date, breakfast, lunch, dinner, snacks = meal
            meal_data.append({
                "meal_date": meal_date,
                "breakfast": breakfast,
                "lunch": lunch,
                "dinner": dinner,
                "snacks": snacks
            })

        # 3. Prompt 1: Text Analysis
        analysis_prompt = f"""
        The patient has a diet prescription as follows:
        {diet_prescription}

        The patient ate the following meals on different days:
        {meal_data}

        Also based on the {meal_data} first understand what kind of food the patient eats , like understand the cuisine first. Once you understand that then generate the analysis.
        Analyze the meals compared to the diet prescription and determine if the patient ate appropriately. 
        Highlight if they consumed too much, too little, or the right amount. Suggest necessary dietary changes.
        """

        analysis = get_openai_response(analysis_prompt)
        if not analysis:
            return jsonify({"error": "Failed to generate analysis."}), 500

        # 4. Prompt 2: Get graph data
        graph_prompt = f"""
        Based on this analysis:
        {analysis}

        Generate nutritional summary data to be plotted in a bar chart with values for: Calories, Carbs, Protein, Fats — both prescribed and actual. 
        Return JSON like: 
        {{
          "Nutrient": ["Calories", "Carbs", "Protein", "Fats"],
          "Prescribed": [2000, 300, 100, 70],
          "Actual": [2500, 400, 90, 110]
        }}

        return only json no text before or after it.
        """
        graph_data = get_openai_response(graph_prompt)
        graph_data = eval(graph_data)  # parse JSON-like text to dict

        # Generate graph image
        df_graph = pd.DataFrame(graph_data)
        fig1, ax1 = plt.subplots()
        df_graph.set_index('Nutrient').plot(kind='bar', ax=ax1)
        ax1.set_title("Prescribed vs Actual Nutrient Intake")
        ax1.set_ylabel("Grams / Calories")
        ax1.legend()

        buf1 = io.BytesIO()
        plt.savefig(buf1, format='png')
        buf1.seek(0)
        graph_image = buf1.read()
        plt.close(fig1)

        # 5. Prompt 3: Get table data
        table_prompt = f"""
        Based on this analysis:
        {analysis}

        Generate a table with columns: Nutrient | Prescribed | Actual | Deviation | Analysis.
        Return JSON like:
        [
          ["Calories", 2000, 2500, 500, "Too much"],
          ["Carbs", 300, 400, 100, "Excess carbs"],
          ...
        ]
        return only json no text before or after it
        """
        table_data = get_openai_response(table_prompt)
        table_data = eval(table_data)

        # Generate table image
        df_table = pd.DataFrame(table_data, columns=["Nutrient", "Prescribed", "Actual", "Deviation", "Analysis"])
        fig2, ax2 = plt.subplots(figsize=(6, 4))
        ax2.axis('off')
        tbl = ax2.table(cellText=df_table.values, colLabels=df_table.columns, loc='center')
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(10)
        tbl.scale(1.2, 1.5)

        buf2 = io.BytesIO()
        plt.savefig(buf2, format='png')
        buf2.seek(0)
        table_image = buf2.read()
        plt.close(fig2)

        # 6. Store everything in DB
        cursor.execute("""
            UPDATE PatientInformation
            SET analytics = ?, graph_image = ?, table_image = ?
            WHERE patient_id = ?
        """, (analysis, graph_image, table_image, patient_id))
        conn.commit()

        # 7. Close and return
        cursor.close()
        conn.close()

        # Encode the images to base64 for easier display on the client side
        graph_image_base64 = encode_image_to_base64(graph_image)
        table_image_base64 = encode_image_to_base64(table_image)

        return jsonify({
            "patient_id": patient_id,
            "analysis": analysis,
            "graph_image": graph_image_base64,
            "table_image": table_image_base64,
            "graph_data": graph_data,
            "table_data": table_data
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/patients/<patient_id>/analytics_images', methods=['GET'])
def get_analytics_images(patient_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT graph_image, table_image FROM PatientInformation WHERE patient_id = ?", (patient_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if not result:
            return jsonify({"error": "Images not found."}), 404

        graph_image = base64.b64encode(result[0]).decode('utf-8')
        table_image = base64.b64encode(result[1]).decode('utf-8')

        return jsonify({
            "graph_image_base64": graph_image,
            "table_image_base64": table_image
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


#API Endpoint: Retrieve doctor's blogs
@app.route('/doctor_blogs', methods=['GET'])
def get_all_blogs():
    """Fetch all blogs (for homepage)."""
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, content, date_written FROM DoctorBlogs ORDER BY date_written DESC")
        blogs = [{"id": row[0], "title": row[1], "content": row[2], "date_written": row[3]} for row in cursor.fetchall()]
        return jsonify(blogs)  # ✅ Returns a list of all blogs
    except Exception as e:
        print("Error fetching blogs:", str(e))
        return jsonify({"error": "Database error occurred"}), 500
    finally:
        conn.close()

#API Endpoint: Retrieve one doctor's blogs
@app.route('/doctor_blogs/<int:blog_id>', methods=['GET'])
def get_blog(blog_id):
    """Fetch a single blog (for editing)."""
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, content, date_written FROM DoctorBlogs WHERE id = ?", (blog_id,))
        row = cursor.fetchone()

        if not row:
            return jsonify({"error": "Blog not found"}), 404
        
        blog = {"id": row[0], "title": row[1], "content": row[2], "date_written": row[3]}
        return jsonify(blog)  # ✅ Returns one specific blog
    except Exception as e:
        print("Error fetching blog:", str(e))
        return jsonify({"error": "Database error occurred"}), 500
    finally:
        conn.close()

#API Endpoint: Update doctor's blogs
@app.route('/doctor_blogs/<int:id>', methods=['PUT'])
def update_blog(id):
    """Update an existing blog by id."""
    data = request.get_json()
    title = data.get('title')
    content = data.get('content')
    date_written = data.get('date_written')

    if not title or not content or not date_written:
        return jsonify({"error": "Title, content, and date are required"}), 400
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cursor = conn.cursor()
        
        # Update the blog with the given ID
        cursor.execute("""
            UPDATE DoctorBlogs
            SET title = ?, content = ?, date_written = ?
            WHERE id = ?
        """, (title, content, date_written, id))

        conn.commit()
        return jsonify({"message": "Blog successfully updated!"})
    except Exception as e:
        print("Error updating blog:", str(e))
        return jsonify({"error": "Database error occurred"}), 500
    finally:
        conn.close()

#API Endpoint: Delete doctor's blogs
@app.route('/doctor_blogs/<int:id>', methods=['DELETE'])
def delete_blog(id):
    """Delete a blog by id."""
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cursor = conn.cursor()
        
        # Delete the blog with the given ID
        cursor.execute("DELETE FROM DoctorBlogs WHERE id = ?", (id,))
        
        conn.commit()
        return jsonify({"message": "Blog successfully deleted!"})
    except Exception as e:
        print("Error deleting blog:", str(e))
        return jsonify({"error": "Database error occurred"}), 500
    finally:
        conn.close()

#API Endpoint : Post doctor's blogs
@app.route('/doctor_blogs', methods=['POST'])
def create_blog():
    """Create a new blog."""
    data = request.get_json()
    title = data.get('title')
    content = data.get('content')
    date_written = data.get('date_written')

    if not title or not content or not date_written:
        return jsonify({"error": "Title, content, and date are required"}), 400
    
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        cursor = conn.cursor()
        
        # Insert new blog without deleting previous ones
        cursor.execute("""
            INSERT INTO DoctorBlogs (title, content, date_written)
            VALUES (?, ?, ?)
        """, (title, content, date_written))

        conn.commit()
        return jsonify({"message": "Blog successfully saved!"})
    except Exception as e:
        print("Error saving blog:", str(e))
        return jsonify({"error": "Database error occurred"}), 500
    finally:
        conn.close()
        
if __name__ == "__main__":
    app.run(debug=True)
