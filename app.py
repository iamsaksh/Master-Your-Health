import os
import sys
from flask import Flask
from flask_cors import CORS
from api.routes import app as api_blueprint
from html_routes.routes import app_html as html_blueprint
from init_db import initialize_database

# Detect base directory correctly
if getattr(sys, 'frozen', False):
    base_dir = sys._MEIPASS
else:
    base_dir = os.path.abspath(os.path.dirname(__file__))

# Optional: Print API key hint for debug
if os.getenv("OPENAI_API_KEY"):
    print("🔑 API Key loaded:", os.getenv("OPENAI_API_KEY")[:5] + "...")
else:
    print("🔑 API Key not found!")

# Set template/static folder paths
template_folder = os.path.join(base_dir, 'templates')
static_folder = os.path.join(base_dir, 'static')

# Initialize Flask app
app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
app.secret_key = os.getenv('SECRET_KEY') or 'fallback-secret-key'  # Optional fallback
CORS(app)

# Register blueprints
app.register_blueprint(api_blueprint)
app.register_blueprint(html_blueprint)

# 👇 Azure looks for this variable
application = app  # gunicorn will use this

# Local run only
if __name__ == "__main__":
    initialize_database()
    app.run(debug=True)
