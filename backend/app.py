"""
Flask application and WebSocket server for NexusChat.
Manages HTTP API routes, static asset delivery, and Socket.IO events.
"""

import os
import random
import time
import threading
from collections import defaultdict

from flask import (
    Flask,
    request,
    jsonify,
    session,
    send_from_directory,
    redirect,
)
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename

from moderation import sanitize_message

# Local modules
from database import (
    init_db,
    get_all_rooms,
    get_room_by_id,
    create_room,
    get_all_users,
    get_user_by_id,
    get_user_by_username,
    update_user_status,
    save_message,
    get_room_messages,
    toggle_reaction,
    get_or_create_dm_room,
)

from auth import (
    register_user_account,
    authenticate_user,
    login_user_session,
    logout_user_session,
    get_current_user,
    login_required,
)


# ==============================================================================
# Configuration
# ==============================================================================

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BACKEND_DIR)
FRONTEND_DIR = os.path.join(PROJECT_DIR, "frontend")
UPLOADS_DIR = os.path.join(PROJECT_DIR, "uploads")

os.makedirs(UPLOADS_DIR, exist_ok=True)

app = Flask(
    __name__,
    static_folder=FRONTEND_DIR,
    template_folder=FRONTEND_DIR,
)

# For production, set FLASK_SECRET_KEY in your environment.
app.config["SECRET_KEY"] = os.environ.get(
    "FLASK_SECRET_KEY",
    "dev-only-change-this-secret-key",
)

app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
app.config["UPLOAD_FOLDER"] = UPLOADS_DIR

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
)

# In-memory online-user tracking
online_users = defaultdict(set)
sid_to_user = {}

ALLOWED_EXTENSIONS = {
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp",
    "pdf",
    "txt",
    "zip",
}


def allowed_file(filename):
    """Check whether a file extension is permitted."""
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


# Initialize the database once.
init_db()


# ==============================================================================
# Page Routes
# ==============================================================================

@app.route("/")
def index():
    """Redirect to chat or login."""
    if session.get("user_id"):
        return redirect("/chat")

    return redirect("/login")


@app.route("/login")
def login_page():
    """Serve the login and registration page."""
    if session.get("user_id"):
        return redirect("/chat")

    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/chat")
@login_required
def chat_page():
    """Serve the main chat page."""
    return send_from_directory(FRONTEND_DIR, "chat.html")


@app.route("/frontend/<path:filename>")
def serve_frontend_assets(filename):
    """Serve frontend CSS, JavaScript, and other assets."""
    return send_from_directory(FRONTEND_DIR, filename)


@app.route("/uploads/<path:filename>")
def serve_uploaded_file(filename):
    """Serve uploaded attachments."""
    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        filename,
    )


# ==============================================================================
# Authentication API
# ==============================================================================

@app.route("/api/auth/register", methods=["POST"])
def api_register():
    """Register a new user account."""
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "success": False,
            "error": "Please send valid JSON data.",
        }), 400

    username = data.get("username", "")
    email = data.get("email", "")
    password = data.get("password", "")
    display_name = data.get("display_name", "")
    bio = data.get("bio", "")

    # Validate input types before passing them to the auth module.
    if not all(
        isinstance(value, str)
        for value in (username, email, password, display_name, bio)
    ):
        return jsonify({
            "success": False,
            "error": "All registration fields must contain text.",
        }), 400

    try:
        success, result = register_user_account(
            username,
            email,
            password,
            display_name,
            bio,
        )

        if not success:
            return jsonify({
                "success": False,
                "error": result,
            }), 400

        # Log in the user after successful registration.
        login_user_session(result)

        # Do not return the password or password hash to the browser.
        safe_user = {
            key: value
            for key, value in result.items()
            if key not in {"password", "password_hash"}
        }

        return jsonify({
            "success": True,
            "user": safe_user,
        }), 201

    except Exception:
        app.logger.exception("Registration failed")

        return jsonify({
            "success": False,
            "error": "Registration failed because of a server error.",
        }), 500


@app.route("/api/auth/login", methods=["POST"])
def api_login():
    """Authenticate an existing user."""
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "success": False,
            "error": "Please send valid JSON data.",
        }), 400

    identifier = data.get("identifier", "")
    password = data.get("password", "")

    if not isinstance(identifier, str) or not isinstance(password, str):
        return jsonify({
            "success": False,
            "error": "Username/email and password must be text.",
        }), 400

    try:
        success, result = authenticate_user(identifier, password)

        if not success:
            return jsonify({
                "success": False,
                "error": result,
            }), 401

        login_user_session(result)

        safe_user = {
            key: value
            for key, value in result.items()
            if key not in {"password", "password_hash"}
        }

        return jsonify({
            "success": True,
            "user": safe_user,
        }), 200

    except Exception:
        app.logger.exception("Login failed")

        return jsonify({
            "success": False,
            "error": "Login failed because of a server error.",
        }), 500


@app.route("/api/auth/logout", methods=["POST"])
def api_logout():
    """Log out the current user."""
    logout_user_session()

    return jsonify({
        "success": True,
        "message": "Logged out successfully.",
    })


@app.route("/api/auth/me", methods=["GET"])
def api_me():
    """Return the currently authenticated user's information."""
    user = get_current_user()

    if not user:
        return jsonify({
            "authenticated": False,
        }), 401

    safe_user = {
        key: value
        for key, value in user.items()
        if key not in {"password", "password_hash"}
    }

    return jsonify({
        "authenticated": True,
        "user": safe_user,
    }), 200


# ==============================================================================
# Rooms / Channels API
# ==============================================================================

@app.route("/api/rooms", methods=["GET"])
@login_required
def api_get_rooms():
    """Return all available chat rooms."""
    rooms = get_all_rooms()

    return jsonify({
        "success": True,
        "rooms": rooms,
    })


@app.route("/api/rooms", methods=["POST"])
@login_required
def api_create_room():
    """Create a public chat channel."""
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "success": False,
            "error": "Please send valid JSON data.",
        }), 400

    name = data.get("name", "")
    description = data.get("description", "")
    icon = data.get("icon", "#")

    if not all(
        isinstance(value, str)
        for value in (name, description, icon)
    ):
        return jsonify({
            "success": False,
            "error": "Channel fields must contain text.",
        }), 400

    name = name.strip()
    description = description.strip()
    icon = icon.strip() or "#"

    if not name:
        return jsonify({
            "success": False,
            "error": "Channel name is required.",
        }), 400

    try:
        room = create_room(
            name,
            description,
            icon,
            is_private=0,
        )

        if not room:
            return jsonify({
                "success": False,
                "error": "Channel name already exists or is invalid.",
            }), 400

        socketio.emit("new_channel_created", room)

        return jsonify({
            "success": True,
            "room": room,
        }), 201

    except Exception:
        app.logger.exception("Channel creation failed")

        return jsonify({
            "success": False,
            "error": "Could not create the channel.",
        }), 500


# ==============================================================================
# Users API
# ==============================================================================

@app.route("/api/users", methods=["GET"])
@login_required
def api_get_users():
    """Return registered users with their current online status."""
    users = get_all_users()

    for user in users:
        if online_users.get(user["id"]):
            user["status"] = "online"
        else:
            user["status"] = "offline"

    return jsonify({
        "success": True,
        "users": users,
    })


# ==============================================================================
# Message History API
# ==============================================================================

@app.route("/api/messages/<int:room_id>", methods=["GET"])
@login_required
def api_get_messages(room_id):
    """Retrieve messages for a particular room."""
    limit = request.args.get("limit", 60, type=int)
    limit = max(1, min(limit, 100))

    room = get_room_by_id(room_id)

    if not room:
        return jsonify({
            "success": False,
            "error": "Room not found.",
        }), 404

    messages = get_room_messages(
        room_id,
        limit=limit,
    )

    return jsonify({
        "success": True,
        "room": room,
        "messages": messages,
    })


# ==============================================================================
# Direct Messages API
# ==============================================================================

@app.route("/api/dm/<int:target_user_id>", methods=["GET"])
@login_required
def api_get_or_create_dm(target_user_id):
    """Retrieve or create a private conversation."""
    current_user_id = session.get("user_id")

    if current_user_id == target_user_id:
        return jsonify({
            "success": False,
            "error": "You cannot open a DM with yourself.",
        }), 400

    target_user = get_user_by_id(target_user_id)

    if not target_user:
        return jsonify({
            "success": False,
            "error": "User not found.",
        }), 404

    try:
        room = get_or_create_dm_room(
            current_user_id,
            target_user_id,
        )

        if not room:
            return jsonify({
                "success": False,
                "error": "Could not open the conversation.",
            }), 500

        room["display_name"] = target_user.get(
            "display_name",
            target_user.get("username", "User"),
        )
        room["target_user"] = target_user

        messages = get_room_messages(
            room["id"],
            limit=60,
        )

        return jsonify({
            "success": True,
            "room": room,
            "messages": messages,
        })

    except Exception:
        app.logger.exception("Could not open direct message")

        return jsonify({
            "success": False,
            "error": "Could not open the conversation.",
        }), 500


# ==============================================================================
# File Upload API
# ==============================================================================

@app.route("/api/upload", methods=["POST"])
@login_required
def api_upload_file():
    """Upload an attachment for a chat message."""
    if "file" not in request.files:
        return jsonify({
            "success": False,
            "error": "No file uploaded.",
        }), 400

    file = request.files["file"]

    if not file or not file.filename:
        return jsonify({
            "success": False,
            "error": "Please select a file.",
        }), 400

    if not allowed_file(file.filename):
        return jsonify({
            "success": False,
            "error": "File extension is not allowed.",
        }), 400

    filename = secure_filename(file.filename)

    if not filename:
        return jsonify({
            "success": False,
            "error": "Invalid filename.",
        }), 400

    timestamp_prefix = (
        f"{int(time.time())}_{random.randint(100, 999)}_"
    )
    saved_filename = timestamp_prefix + filename
    file_path = os.path.join(
        app.config["UPLOAD_FOLDER"],
        saved_filename,
    )

    try:
        file.save(file_path)

        extension = filename.rsplit(".", 1)[1].lower()
        is_image = extension in {
            "png",
            "jpg",
            "jpeg",
            "gif",
            "webp",
        }

        return jsonify({
            "success": True,
            "file_url": f"/uploads/{saved_filename}",
            "filename": filename,
            "is_image": is_image,
        }), 201

    except Exception:
        app.logger.exception("File upload failed")

        return jsonify({
            "success": False,
            "error": "Could not upload the file.",
        }), 500


# ==============================================================================
# Nova Bot Responses
# ==============================================================================

BOT_JOKES = [
    "Why do programmers prefer dark mode? Because light attracts bugs! 🐛",
    "There are only 10 types of people in the world: those who understand binary, and those who don't. 💻",
    "Why did the web developer leave the restaurant? Because of the table layout! 🍽️",
    "A SQL query walks into a bar, walks up to two tables and asks: 'Can I join you?' 🍻",
    "How do you comfort a JavaScript bug? You console it! 😄",
]

BOT_QUOTES = [
    "“Talk is cheap. Show me the code.” — Linus Torvalds",
    "“Programs must be written for people to read, and only incidentally for machines to execute.” — Harold Abelson",
    "“First, solve the problem. Then, write the code.” — John Johnson",
    "“Simplicity is prerequisite for reliability.” — Edsger W. Dijkstra",
]


def handle_bot_interaction(room_id, message_content):
    """Generate a Nova Bot response when a command is detected."""
    if not isinstance(message_content, str):
        return

    trigger_words = [
        "@nova",
        "/bot",
        "/help",
        "/joke",
        "/quote",
        "hello bot",
        "hey bot",
    ]

    lower_content = message_content.lower()

    if not any(
        trigger in lower_content
        for trigger in trigger_words
    ):
        return

    bot_user = get_user_by_username("nova_bot")

    if not bot_user:
        return

    response_text = ""

    if "/joke" in lower_content or "joke" in lower_content:
        response_text = (
            f"🤖 **Nova Joke**: {random.choice(BOT_JOKES)}"
        )

    elif "/quote" in lower_content or "quote" in lower_content:
        response_text = (
            f"🤖 **Tech Quote**: {random.choice(BOT_QUOTES)}"
        )

    elif "/help" in lower_content:
        response_text = (
            "🤖 **Nova Assistant Commands**:\n"
            "• `/joke` - Get a developer joke\n"
            "• `/quote` - Get a computer science quote\n"
            "• `/help` - Show this menu\n"
            "• Mention `@nova` for a friendly greeting!"
        )

    else:
        greetings = [
            "🤖 Beep boop! Hello there! I'm Nova. Type `/help` for commands!",
            "🤖 Greetings! Real-time WebSockets are ready! ⚡",
            "🤖 At your service! Type `/joke` or share some code!",
        ]
        response_text = random.choice(greetings)

    def send_bot_reply():
        time.sleep(0.6)

        try:
            saved_bot_msg = save_message(
                room_id=room_id,
                sender_id=bot_user["id"],
                content=response_text,
                message_type="bot",
            )

            socketio.emit(
                "new_message",
                saved_bot_msg,
                to=f"room_{room_id}",
            )

        except Exception:
            app.logger.exception("Nova Bot reply failed")

    threading.Thread(
        target=send_bot_reply,
        daemon=True,
    ).start()


# ==============================================================================
# Socket.IO Authentication and Presence
# ==============================================================================

@socketio.on("connect")
def on_connect(auth=None):
    """Register an authenticated Socket.IO connection."""
    user_id = session.get("user_id")

    # Authentication relies on the Flask session.
    # Do not trust a user_id supplied by the browser.

    if not user_id:
        return

    sid = request.sid

    online_users[user_id].add(sid)
    sid_to_user[sid] = user_id

    update_user_status(user_id, "online")

    user_info = get_user_by_id(user_id)

    emit(
        "user_status_change",
        {
            "user_id": user_id,
            "status": "online",
            "user": user_info,
        },
        broadcast=True,
    )

    emit(
        "online_users_list",
        {
            "online_user_ids": list(online_users.keys()),
        },
    )


@socketio.on("disconnect")
def on_disconnect(reason=None):
    """Remove a disconnected socket from online tracking."""
    sid = request.sid
    user_id = sid_to_user.pop(sid, None)

    if user_id and user_id in online_users:
        online_users[user_id].discard(sid)

        # A user may have multiple tabs open.
        # Mark them offline only after the final connection closes.
        if not online_users[user_id]:
            del online_users[user_id]

            update_user_status(user_id, "offline")

            emit(
                "user_status_change",
                {
                    "user_id": user_id,
                    "status": "offline",
                },
                broadcast=True,
            )


# ==============================================================================
# Socket.IO Room Events
# ==============================================================================

@socketio.on("join_room")
def on_join_room(data):
    """Join a chat room."""
    if not isinstance(data, dict):
        emit("error", {"message": "Invalid room data."})
        return

    room_id = data.get("room_id")

    if (
        not isinstance(room_id, (int, str))
        or not str(room_id).isdigit()
    ):
        emit("error", {"message": "Invalid room ID."})
        return

    user_id = session.get("user_id") or sid_to_user.get(request.sid)

    if not user_id:
        emit("error", {"message": "Please log in first."})
        return

    room_id = int(room_id)
    room = get_room_by_id(room_id)

    if not room:
        emit("error", {"message": "Room not found."})
        return

    # NOTE: If your application uses private rooms, verify the
    # user's access to that room before allowing them to join.
    join_room(f"room_{room_id}")

    emit(
        "room_joined",
        {
            "room_id": room_id,
            "message": f"Successfully joined room {room_id}",
        },
    )


@socketio.on("leave_room")
def on_leave_room(data):
    """Leave a chat room."""
    if not isinstance(data, dict):
        return

    room_id = data.get("room_id")

    if (
        isinstance(room_id, (int, str))
        and str(room_id).isdigit()
    ):
        leave_room(f"room_{int(room_id)}")


# ==============================================================================
# Socket.IO Messaging
# ==============================================================================

@socketio.on("send_message")
def on_send_message(data):
    """Save and broadcast a new message."""
    if not isinstance(data, dict):
        emit("error", {"message": "Invalid message payload."})
        return

    room_id = data.get("room_id")
    content = data.get("content", "")
    message_type = data.get("message_type", "text")
    file_url = data.get("file_url")

    if (
        not isinstance(room_id, (int, str))
        or not str(room_id).isdigit()
    ):
        emit("error", {"message": "Invalid room ID."})
        return

    room_id = int(room_id)

    if not isinstance(content, str):
        content = ""

    content = content.strip()

    if len(content) > 5000:
        emit(
            "error",
            {
                "message": (
                    "Message is too long. "
                    "Maximum length is 5000 characters."
                )
            },
        )
        return

    if not isinstance(message_type, str):
        message_type = "text"

    if file_url is not None and not isinstance(file_url, str):
        emit("error", {"message": "Invalid file attachment."})
        return

    user_id = session.get("user_id") or sid_to_user.get(request.sid)

    if not user_id:
        emit(
            "error",
            {"message": "You must be logged in to send messages."},
        )
        return

    if not content and not file_url:
        return

    room = get_room_by_id(room_id)

    if not room:
        emit("error", {"message": "Room not found."})
        return

    # Sanitize message content before saving.
    try:
        if content:
            content = sanitize_message(content)

        saved_msg = save_message(
            room_id=room_id,
            sender_id=user_id,
            content=content,
            message_type=message_type,
            file_url=file_url,
        )

        if not saved_msg:
            emit("error", {"message": "Message could not be saved."})
            return

        emit(
            "new_message",
            saved_msg,
            to=f"room_{room_id}",
        )

        if content:
            handle_bot_interaction(room_id, content)

    except Exception:
        app.logger.exception("Sending message failed")

        emit(
            "error",
            {"message": "Could not send the message."},
        )


# ==============================================================================
# Socket.IO Typing Indicators
# ==============================================================================

@socketio.on("typing")
def on_typing(data):
    """Notify other room members that a user is typing."""
    if not isinstance(data, dict):
        return

    room_id = data.get("room_id")
    user_id = session.get("user_id") or sid_to_user.get(request.sid)

    if (
        not user_id
        or not isinstance(room_id, (int, str))
        or not str(room_id).isdigit()
    ):
        return

    room_id = int(room_id)
    user = get_user_by_id(user_id)

    if user:
        emit(
            "user_typing",
            {
                "room_id": room_id,
                "user_id": user_id,
                "username": user.get("username", ""),
                "display_name": user.get("display_name", ""),
            },
            to=f"room_{room_id}",
            include_self=False,
        )


@socketio.on("stop_typing")
def on_stop_typing(data):
    """Notify other room members that typing has stopped."""
    if not isinstance(data, dict):
        return

    room_id = data.get("room_id")
    user_id = session.get("user_id") or sid_to_user.get(request.sid)

    if (
        not user_id
        or not isinstance(room_id, (int, str))
        or not str(room_id).isdigit()
    ):
        return

    room_id = int(room_id)

    emit(
        "user_stop_typing",
        {
            "room_id": room_id,
            "user_id": user_id,
        },
        to=f"room_{room_id}",
        include_self=False,
    )


# ==============================================================================
# Socket.IO Reactions
# ==============================================================================

@socketio.on("reaction")
def on_reaction(data):
    """Add or remove a reaction from a message."""
    if not isinstance(data, dict):
        return

    message_id = data.get("message_id")
    room_id = data.get("room_id")
    emoji = data.get("emoji")
    user_id = session.get("user_id") or sid_to_user.get(request.sid)

    if not all((message_id, room_id, emoji, user_id)):
        return

    if (
        not isinstance(room_id, (int, str))
        or not str(room_id).isdigit()
    ):
        return

    if not isinstance(emoji, str) or len(emoji) > 32:
        return

    try:
        action, updated_reactions = toggle_reaction(
            message_id,
            user_id,
            emoji,
        )

        emit(
            "reaction_updated",
            {
                "message_id": message_id,
                "room_id": int(room_id),
                "reactions": updated_reactions,
                "action": action,
                "user_id": user_id,
            },
            to=f"room_{int(room_id)}",
        )

    except Exception:
        app.logger.exception("Reaction update failed")
        emit("error", {"message": "Could not update reaction."})


# ==============================================================================
# Socket.IO Status Updates
# ==============================================================================

@socketio.on("status_update")
def on_status_update(data):
    """Update a user's presence status."""
    if not isinstance(data, dict):
        return

    status = data.get("status", "online")

    if status not in {"online", "away", "busy"}:
        status = "online"

    user_id = session.get("user_id") or sid_to_user.get(request.sid)

    if user_id:
        update_user_status(user_id, status)

        emit(
            "user_status_change",
            {
                "user_id": user_id,
                "status": status,
            },
            broadcast=True,
        )


# ==============================================================================
# Main Runner
# ==============================================================================

if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(
            encoding="utf-8",
            errors="replace",
        )

    print("=" * 60)
    print("  NexusChat Real-Time Server starting...")
    print("  Web Interface: http://localhost:5000")
    print("  Channels available: #general, #tech-talk, #random, #announcements")
    print("=" * 60)

    socketio.run(
        app,
        host="0.0.0.0",
        port=5000,
        debug=True,
        allow_unsafe_werkzeug=True,
    )