
from flask import (
    Flask, request, jsonify, render_template,
    session, redirect, url_for
)
import joblib
import re
import os
import sqlite3

from database import get_connection, initialize_database
from werkzeug.security import generate_password_hash, check_password_hash

# Project paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE_DIR, "model")

# Flask configuration
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates")
)

app.secret_key = "reviewsense_secret_key_2026"

# Initialize database tables
initialize_database()

# Load trained ML model and TF-IDF vectorizer
model = joblib.load(os.path.join(MODEL_DIR, "sentiment_model.pkl"))
tfidf = joblib.load(os.path.join(MODEL_DIR, "tfidf_vectorizer.pkl"))


# Text preprocessing
def clean_text(text):
    text = text.lower()
    text = re.sub(r'[^a-z\s]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


# Authentication helper
def login_required():
    return "user_id" in session


# Introduction page
@app.route("/")
def home():
    return render_template("index.html")


# Registration
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not username or not email or not password:
        return jsonify({
            "error": "All fields are required."
        }), 400

    if len(password) < 8:
        return jsonify({
            "error": "Password must contain at least 8 characters."
        }), 400

    password_hash = generate_password_hash(password)

    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            INSERT INTO users (username, email, password_hash)
            VALUES (?, ?, ?)
            """,
            (username, email, password_hash)
        )

        connection.commit()

        return jsonify({
            "message": "Account created successfully!"
        })

    except sqlite3.IntegrityError:
        connection.rollback()

        return jsonify({
            "error": "This email is already registered."
        }), 409

    finally:
        connection.close()


# Login
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not email or not password:
        return jsonify({
            "error": "Please enter your email and password."
        }), 400

    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,)
        )

        user = cursor.fetchone()

    finally:
        connection.close()

    if user and check_password_hash(user["password_hash"], password):
        session.clear()
        session["user_id"] = user["id"]
        session["username"] = user["username"]

        return jsonify({
            "message": "Login successful!",
            "redirect": url_for("dashboard")
        })

    return jsonify({
        "error": "Invalid email or password."
    }), 401


# Logout
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# Dashboard with dynamic statistics
@app.route("/dashboard")
def dashboard():
    if not login_required():
        return redirect(url_for("login"))

    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN sentiment = 'Positive' THEN 1 ELSE 0 END) AS positive,
                SUM(CASE WHEN sentiment = 'Negative' THEN 1 ELSE 0 END) AS negative,
                SUM(CASE WHEN sentiment = 'Neutral' THEN 1 ELSE 0 END) AS neutral
            FROM analysis_history
            WHERE user_id = ?
            """,
            (session["user_id"],)
        )

        stats = cursor.fetchone()

    finally:
        connection.close()

    return render_template(
        "dashboard.html",
        stats=stats
    )


# Review analysis page
@app.route("/analysis")
def analysis():
    if not login_required():
        return redirect(url_for("login"))

    return render_template("analysis.html")


# Reports page
@app.route("/reports")
def reports():
    if not login_required():
        return redirect(url_for("login"))

    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT review, sentiment, created_at
            FROM analysis_history
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (session["user_id"],)
        )

        history = cursor.fetchall()

    finally:
        connection.close()

    return render_template(
        "reports.html",
        history=history
    )


# Sentiment prediction
@app.route("/predict", methods=["POST"])
def predict():
    if not login_required():
        return jsonify({
            "error": "Please log in first."
        }), 401

    data = request.get_json(silent=True) or {}
    review = data.get("review", "")

    if not isinstance(review, str) or not review.strip():
        return jsonify({
            "error": "Please enter a valid review."
        }), 400

    cleaned_review = clean_text(review)

    if not cleaned_review:
        return jsonify({
            "error": "Please enter a valid review."
        }), 400

    try:
        review_vector = tfidf.transform([cleaned_review])
        prediction = str(model.predict(review_vector)[0])

        connection = get_connection()

        try:
            cursor = connection.cursor()

            cursor.execute(
                """
                INSERT INTO analysis_history
                (user_id, review, sentiment)
                VALUES (?, ?, ?)
                """,
                (
                    session["user_id"],
                    review.strip(),
                    prediction
                )
            )

            connection.commit()

        finally:
            connection.close()

        return jsonify({
            "review": review,
            "sentiment": prediction,
            "message": "Review analysed successfully!"
        })

    except Exception:
        app.logger.exception("Prediction failed")

        return jsonify({
            "error": "Unable to analyse the review. Please try again."
        }), 500


# Run application
if __name__ == "__main__":
    app.run(debug=True)
