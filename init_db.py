import psycopg2

def get_db_connection():
    conn = psycopg2.connect(
        host="db.gdrohvorhlfwbleicuyn.supabase.co",
        port="5432",
        dbname="postgres",
        user="postgres",
        password="MYHSavita007@",  # <- replace with actual password
        sslmode="require"  # important for Supabase
    )
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS Users (
        patient_id VARCHAR(10) PRIMARY KEY,
        Name VARCHAR(100),
        PhoneNumber VARCHAR(15),
        Email VARCHAR(255),
        DOB DATE,
        Location VARCHAR(100),
        Occupation VARCHAR(100),
        Username VARCHAR(50),
        Password VARCHAR(255)
    );
    """)

    # PatientInformation table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS PatientInformation (
        patient_id VARCHAR(10) PRIMARY KEY,
        weight FLOAT,
        height FLOAT,
        blood_group VARCHAR(10),
        medical_history TEXT,
        medical_prescription TEXT,
        diet_prescription TEXT,
        structured_diet_chart TEXT,
        exercise_prescription TEXT,
        current_health_conditions TEXT,
        treatment_details TEXT,
        fitness_goal TEXT,
        allergies TEXT,
        smoking VARCHAR(10),
        drinking VARCHAR(10),
        sleep_pattern VARCHAR(50),
        analytics TEXT,
        graph_image BYTEA,
        table_image BYTEA,
        FOREIGN KEY (patient_id) REFERENCES Users(patient_id)
    );
    """)

    # PatientActivityData table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS PatientActivityData (
        patient_id VARCHAR(10) PRIMARY KEY,
        day1_meal TEXT,
        day2_meal TEXT,
        day3_meal TEXT,
        ipaQ_vigorous_met FLOAT,
        ipaQ_moderate_met FLOAT,
        ipaQ_walking_met FLOAT,
        ipaQ_total_met FLOAT,
        ipaQ_category VARCHAR(50),
        FOREIGN KEY (patient_id) REFERENCES Users(patient_id)
    );
    """)

    # PatientMealTracking table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS PatientMealTracking (
        patient_id VARCHAR(10),
        meal_date DATE,
        breakfast TEXT,
        lunch TEXT,
        dinner TEXT,
        snacks TEXT,
        PRIMARY KEY (patient_id, meal_date),
        FOREIGN KEY (patient_id) REFERENCES Users(patient_id)
    );
    """)

    # PatientExerciseTracking table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS PatientExerciseTracking (
        patient_id VARCHAR(10),
        exercise_name VARCHAR(100),
        duration_minutes INT,
        exercise_date DATE,
        PRIMARY KEY (patient_id, exercise_name, exercise_date),
        FOREIGN KEY (patient_id) REFERENCES Users(patient_id)
    );
    """)

    # DoctorBlogs table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS DoctorBlogs (
        id SERIAL PRIMARY KEY,
        title VARCHAR(200),
        content TEXT,
        date_written DATE DEFAULT CURRENT_DATE
    );
    """)

    # PatientVisits table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS PatientVisits (
        visit_id SERIAL PRIMARY KEY,
        patient_id VARCHAR(10),
        visit_date DATE DEFAULT CURRENT_DATE,
        weight FLOAT,
        height FLOAT,
        medical_prescription TEXT,
        diet_prescription TEXT,
        exercise_prescription TEXT,
        notes TEXT,
        FOREIGN KEY (patient_id) REFERENCES Users(patient_id)
    );
    """)

    conn.commit()
    cursor.close()
    conn.close()
    print("✅ Database initialized (Postgres / Supabase).")

if __name__ == "__main__":
    init_db()