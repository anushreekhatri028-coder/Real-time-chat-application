
"""
Authentication module for the Real-Time Chat Application.
Handles registration, password hashing/verification, session management,
and access control.
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
    update_user_status,
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
    "#14b8a6",  # Teal
]


def validate_registration(username, email, password, display_name):
    """
    Validate registration parameters.

    Returns:
        (True, None) if valid.
        (False, error_message) if invalid.
    """

    # Ensure inputs are strings before validating them
    if not isinstance(username, str):
        return False, "Username is required."

    if not isinstance(email, str):
        return False, "Email address is required."

    if not isinstance(password, str):
        return False, "Password is required."

    if display_name is not None and not isinstance(display_name, str):
        return False, "Display name must be text."

    username = username.strip()
    email = email.strip()

    # Validate username
    if not username or len(username) < 3:
        return False, "Username must be at least 3 characters long."

    if len(username) > 25:
        return False, "Username cannot exceed 25 characters."

    if not re.fullmatch(r"[a-zA-Z0-9_]+", username):
        return False, (
            "Username can only contain letters, numbers, and underscores."
        )

    # Validate email
    # Example valid email: alex@example.com
    email_pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

    if not email or not re.fullmatch(email_pattern, email):
        return False, "Please enter a valid email address."

    # Validate password
    if not password or len(password) < 6:
        return False, "Password must be at least 6 characters long."

    # Check whether username already exists
    if get_user_by_username(username):
        return False, "Username is already taken. Please choose another."

    # Check whether email already exists
    if get_user_by_email(email):
        return False, "An account with this email already exists."

    return True, None


def register_user_account(username, email, password, display_name=None, bio=""):
    """Register a new user in the database."""

    valid, error_message = validate_registration(
        username, email, password, display_name
    )

    if not valid:
        return False, error_message

    username = username.strip()
    email = email.strip()

    # Use username as display name if none was provided
    if display_name and display_name.strip():
        display_name = display_name.strip()
    else:
        display_name = username.capitalize()

    # Ensure bio is a string
    if not isinstance(bio, str):
        bio = ""

    bio = bio.strip()

    # Generate avatar color and securely hash the password
    avatar_color = random.choice(AVATAR_PALETTE)
    password_hash = generate_password_hash(password)

    try:
        new_user = create_user(
            username=username,
            email=email,
            password_hash=password_hash,
            display_name=display_name,
            avatar_color=avatar_color,
            bio=bio,
        )
    except Exception:
        # Keep internal database errors out of the API response.
        # Check the backend terminal for the actual exception.
        return False, "Unable to create account. Please try again."

    if not new_user:
        return False, "Failed to create user account. Please try again."

    return True, new_user


def authenticate_user(identifier, password):
    """
    Authenticate a user by username or email.

    Returns:
        (True, safe_user_dict) if authentication succeeds.
        (False, error_message) otherwise.
    """

    if not isinstance(identifier, str) or not isinstance(password, str):
        return False, "Please enter both username/email and password."

    identifier = identifier.strip()

    if not identifier or not password:
        return False, "Please enter both username/email and password."

    # Look up user by email or username
    if "@" in identifier:
        user = get_user_by_email(identifier)
    else:
        user = get_user_by_username(identifier)

    if not user:
        return False, "Invalid credentials. No user found."

    stored_password_hash = user.get("password_hash")

    if not stored_password_hash or not check_password_hash(
        stored_password_hash, password
    ):
        return False, "Invalid credentials. Password does not match."

    # Never return the password hash to the frontend
    safe_user = {
        "id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "display_name": user["display_name"],
        "avatar_color": user["avatar_color"],
        "bio": user["bio"],
        "status": user["status"],
    }

    return True, safe_user


def login_user_session(user_dict):
    """Store authenticated user information in the Flask session."""

    session.clear()

    session["user_id"] = user_dict["id"]
    session["username"] = user_dict["username"]
    session["display_name"] = user_dict["display_name"]
    session.permanent = True


def logout_user_session():
    """Clear the user session and update their status to offline."""

    user_id = session.get("user_id")

    if user_id:
        update_user_status(user_id, "offline")

    session.clear()


def get_current_user():
    """Fetch the currently authenticated user from the session."""

    user_id = session.get("user_id")

    if not user_id:
        return None

    return get_user_by_id(user_id)


def login_required(f):
    """Decorator that protects routes requiring authentication."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({
                    "success": False,
                    "error": "Unauthorized",
                    "message": "Please log in first.",
                }), 401

            return redirect(url_for("login_page"))

        return f(*args, **kwargs)

    return decorated_function
