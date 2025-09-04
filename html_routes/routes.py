from flask import Flask, render_template,request,Blueprint
from flask_cors import CORS
from api.routes import app  # Importing the Flask app from api.py
from flask import send_from_directory
import os

app_html = Blueprint('html', __name__)
CORS(app_html)

@app_html.route("/home")
def home():
    return send_from_directory(directory=os.path.join(app.root_path, 'static_html'), filename='index.html')

@app_html.route("/")
def home_2():
    return send_from_directory(directory=os.path.join(app.root_path, 'static_html'), filename='index.html')

@app_html.route("/login")
def login():
    return render_template("LoginPage.html")

@app_html.route("/services")
def service():
    return render_template("ServicesPage.html")

@app_html.route("/about")
def about():
    return render_template("AboutPage.html")

@app_html.route("/registration")
def register():
    return render_template("RegistrationPage.html")

@app_html.route("/doctor_home")
def doctor_home():
    return render_template("Doctor_HomePage.html")

@app_html.route("/patient_dashboard")
def dashboard():
    return render_template("Patient_DashboardPage.html")

@app_html.route("/doctor_prescription")
def prescription():
    return render_template("PrescriptionPage.html")

@app_html.route("/test_prescription")
def test_prescription():
    return render_template("TestPrescriptionPage.html")

@app_html.route("/assisstant_home")
def assisstant_home():
    return render_template("Assisstant_HomePage.html")

@app_html.route("/assisstant_home/prescription")
def assisstant_prescription():
    return render_template("Assisstant_PrescriptionPage.html")

@app_html.route("/patients_view")
def patients_view():
    return render_template("PatientsViewPage.html")

@app_html.route("/3_day_recall")
def recall_page():
    patient_id = request.args.get("patient_id")  # Get patient_id from URL
    if not patient_id:
        return "Error: Patient ID is required", 400  # Handle missing patient_id

    return render_template("3DayRecallPage.html", patient_id=patient_id)

@app_html.route("/ipaq")
def ipaq_page():
    patient_id = request.args.get("patient_id")  # Get patient_id from URL
    if not patient_id:
        return "Error: Patient ID is required", 400  # Handle missing patient_id

    return render_template("IpaqPage.html", patient_id=patient_id)


@app_html.route("/tracking_options")
def tracking_options():
    patient_id = request.args.get("patient_id") or request.cookies.get("patient_id")

    if not patient_id:
        return "Error: Patient ID is missing!", 400  # Handle missing patient_id
    
    return render_template("Tracking_optionsPage.html", patient_id=patient_id)


@app_html.route("/tracking_food")
def patient_tracking():
    patient_id = request.args.get("patient_id") or request.cookies.get("patient_id")

    if not patient_id:
        return "Error: Patient ID is missing!", 400  # Handle missing patient_id
    
    return render_template("TrackingPage.html", patient_id=patient_id)


@app_html.route("/tracking_exercise")
def tracking_exercise():
    patient_id = request.args.get("patient_id") or request.cookies.get("patient_id")

    if not patient_id:
        return "Error: Patient ID is missing!", 400  # Handle missing patient_id
    
    return render_template("Tracking_exercisePage.html", patient_id=patient_id)

@app_html.route("/blogs")
def doctors_blogs():
    return render_template("Doctors_BlogsPage.html") 

@app_html.route("/doctor_blogs/write_blogs")
def write_blogs():
    return render_template("Write_BlogsPage.html") 

@app_html.route("/doctor_blogs/manage_blogs")
def manage_blogs():
    return render_template("Manage_BlogsPage.html") 

@app_html.route("/contact")
def contact():
    return render_template("ContactPage.html") 

if __name__ == "__main__":
    app_html.run(debug=True, port=5001)  # Run on a different port
