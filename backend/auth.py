"""
Authentication module for the Real-Time Chat Application.
Handles registration, password hashing/verification, session management, and access control.
"""

import re
import random
from functools import wraps
from flask import session, jsonify, request, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from database import (
    create_user,
    get_user_by_username,
    get_user_by_email,
    get_user_by_id,
    update_user_status
)

# Vibrant palette for user avatars
AVATAR_PALETTE = [
    "#6366f1",  # Indigo
    "#8b5cf6",  # Violet
    "#ec4899",  # Pink
    "#f43f5e",  # Rose
    "#f97316",  # Orange
    "#10b981",  # Emerald
    "#06b6d4",  # Cyan
    "#3b82f6",  # Blue
    "#eab308",  # Amber
    "#14b8a6"   # Teal
]


def validate_registration(username, email, password, display_name):
    """Validate registration parameters. Returns (is_valid, error_message)."""
    if not username or len(username.strip()) < 3:
        return False, "Username must be at least 3 characters long."
    if len(username.strip()) > 25:
        return False, "Username cannot exceed 25 characters."
    if not re.match(r"^[a-zA-Z0-9_]+$", username.strip()):
        return False, "Username can only contain letters, numbers, and underscores."

    if not email or not re.match(r"^[^@]+@[^@]+\.[^@]+$", email.strip()):
        return False, "Please enter a valid email address."

    if not password or len(password) < 6:
        return False, "Password must be at least 6 characters long."

    if get_user_by_username(username):
        return False, "Username is already taken. Please choose another."

    if get_user_by_email(email):
        return False, "An account with this email already exists."

    return True, None


def register_user_account(username, email, password, display_name=None, bio=""):
    """Register a new user in the database."""
    valid, err = validate_registration(username, email, password, display_name)
    if not valid:
        return False, err

    display_name = display_name.strip() if display_name and display_name.strip() else username.capitalize()
    avatar_color = random.choice(AVATAR_PALETTE)
    password_hash = generate_password_hash(password)

    new_user = create_user(
        username=username.strip(),
        email=email.strip(),
        password_hash=password_hash,
        display_name=display_name,
        avatar_color=avatar_color,
        bio=bio.strip()
    )

    if not new_user:
        return False, "Failed to create user account. Please try again."

    return True, new_user


def authenticate_user(identifier, password):
    """Authenticate by username or email. Returns (success, user_dict_or_error_msg)."""
    if not identifier or not password:
        return False, "Please enter both username/email and password."

    identifier = identifier.strip()
    # Check if identifier is email or username
    user = get_user_by_email(identifier) if "@" in identifier else get_user_by_username(identifier)

    if not user:
        return False, "Invalid credentials. No user found."

    if not check_password_hash(user["password_hash"], password):
        return False, "Invalid credentials. Password does not match."

    # Return safe user dictionary
    safe_user = {
        "id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "display_name": user["display_name"],
        "avatar_color": user["avatar_color"],
        "bio": user["bio"],
        "status": user["status"]
    }
    return True, safe_user


def login_user_session(user_dict):
    """Store user info in Flask session."""
    session["user_id"] = user_dict["id"]
    session["username"] = user_dict["username"]
    session["display_name"] = user_dict["display_name"]
    session.permanent = True


def logout_user_session():
    """Clear user session and update status to offline."""
    user_id = session.get("user_id")
    if user_id:
        update_user_status(user_id, "offline")
    session.clear()


def get_current_user():
    """Fetch currently authenticated user from session, or None."""
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_user_by_id(user_id)


def login_required(f):
    """Decorator to require login for HTTP routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized", "message": "Please log in first."}), 401
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated_function
