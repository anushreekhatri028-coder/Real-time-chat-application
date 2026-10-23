"""
Flask application and WebSocket server for the Real-Time Chat Application.
Manages HTTP API routes, static asset delivery, and Socket.IO events for live messaging.
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
    url_for
)
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename

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
    get_or_create_dm_room
)
from auth import (
    register_user_account,
    authenticate_user,
    login_user_session,
    logout_user_session,
    get_current_user,
    login_required
)

# Base directory paths
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BACKEND_DIR)
FRONTEND_DIR = os.path.join(PROJECT_DIR, "frontend")
UPLOADS_DIR = os.path.join(PROJECT_DIR, "uploads")

os.makedirs(UPLOADS_DIR, exist_ok=True)

# Initialize Flask app
app = Flask(
    __name__,
    static_folder=FRONTEND_DIR,
    template_folder=FRONTEND_DIR
)
app.config["SECRET_KEY"] = "super-secret-nexus-chat-key-2026-xyz!"
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB max upload
app.config["UPLOAD_FOLDER"] = UPLOADS_DIR

# Initialize SocketIO with threading async_mode (reliable across all Python versions)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# In-memory mapping of user_id -> set of active socket connection IDs (sids)
online_users = defaultdict(set)
# In-memory mapping of sid -> user_id
sid_to_user = {}

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "pdf", "txt", "zip"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# Initialize database on module load
init_db()


# ==============================================================================
# HTTP Routes (Pages and Static)
# ==============================================================================

@app.route("/")
def index():
    """Root route: redirect to /chat if authenticated, otherwise to /login."""
    if "user_id" in session:
        return redirect("/chat")
    return redirect("/login")


@app.route("/login")
def login_page():
    """Serve the authentication page (index.html)."""
    if "user_id" in session:
        return redirect("/chat")
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/chat")
@login_required
def chat_page():
    """Serve the main chat workspace (chat.html)."""
    return send_from_directory(FRONTEND_DIR, "chat.html")


@app.route("/frontend/<path:filename>")
def serve_frontend_assets(filename):
    """Serve static CSS, JS, and image assets from the frontend directory."""
    return send_from_directory(FRONTEND_DIR, filename)


@app.route("/uploads/<path:filename>")
def serve_uploaded_file(filename):
    """Serve user-uploaded files and image attachments."""
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


# ==============================================================================
# REST API Endpoints
# ==============================================================================

@app.route("/api/auth/register", methods=["POST"])
def api_register():
    """Handle new user registration."""
    data = request.get_json() or {}
    username = data.get("username", "")
    email = data.get("email", "")
    password = data.get("password", "")
    display_name = data.get("display_name", "")
    bio = data.get("bio", "")

    success, result = register_user_account(username, email, password, display_name, bio)
    if not success:
        return jsonify({"success": False, "error": result}), 400

    login_user_session(result)
    return jsonify({"success": True, "user": result}), 201


@app.route("/api/auth/login", methods=["POST"])
def api_login():
    """Handle user login."""
    data = request.get_json() or {}
    identifier = data.get("identifier", "")
    password = data.get("password", "")

    success, result = authenticate_user(identifier, password)
    if not success:
        return jsonify({"success": False, "error": result}), 401

    login_user_session(result)
    return jsonify({"success": True, "user": result})


@app.route("/api/auth/logout", methods=["POST"])
def api_logout():
    """Handle user logout."""
    logout_user_session()
    return jsonify({"success": True, "message": "Logged out successfully."})


@app.route("/api/auth/me", methods=["GET"])
def api_me():
    """Return currently logged-in user details."""
    user = get_current_user()
    if not user:
        return jsonify({"authenticated": False}), 401
    return jsonify({"authenticated": True, "user": user})


@app.route("/api/rooms", methods=["GET"])
@login_required
def api_get_rooms():
    """List all public channels."""
    rooms = get_all_rooms()
    return jsonify({"success": True, "rooms": rooms})


@app.route("/api/rooms", methods=["POST"])
@login_required
def api_create_room():
    """Create a new public channel."""
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    description = data.get("description", "").strip()
    icon = data.get("icon", "#").strip()

    if not name:
        return jsonify({"success": False, "error": "Channel name is required."}), 400

    room = create_room(name, description, icon, is_private=0)
    if not room:
        return jsonify({"success": False, "error": "Channel name already exists or is invalid."}), 400

    # Notify all users of new channel creation
    socketio.emit("new_channel_created", room)
    return jsonify({"success": True, "room": room}), 201


@app.route("/api/users", methods=["GET"])
@login_required
def api_get_users():
    """List all registered users along with their real-time presence status."""
    users = get_all_users()
    for u in users:
        # Check active socket connections for real-time presence
        if len(online_users.get(u["id"], set())) > 0:
            u["status"] = "online"
        else:
            u["status"] = "offline"
    return jsonify({"success": True, "users": users})


@app.route("/api/messages/<int:room_id>", methods=["GET"])
@login_required
def api_get_messages(room_id):
    """Retrieve message history for a specific room."""
    limit = request.args.get("limit", 60, type=int)
    room = get_room_by_id(room_id)
    if not room:
        return jsonify({"success": False, "error": "Room not found."}), 404

    messages = get_room_messages(room_id, limit=limit)
    return jsonify({"success": True, "room": room, "messages": messages})


@app.route("/api/dm/<int:target_user_id>", methods=["GET"])
@login_required
def api_get_or_create_dm(target_user_id):
    """Retrieve or create a 1-on-1 private direct message channel."""
    current_user_id = session.get("user_id")
    if current_user_id == target_user_id:
        return jsonify({"success": False, "error": "Cannot open DM with yourself."}), 400

    target_user = get_user_by_id(target_user_id)
    if not target_user:
        return jsonify({"success": False, "error": "User not found."}), 404

    room = get_or_create_dm_room(current_user_id, target_user_id)
    # Decorate with target user details for the UI
    room["display_name"] = target_user["display_name"]
    room["target_user"] = target_user
    messages = get_room_messages(room["id"], limit=60)
    return jsonify({"success": True, "room": room, "messages": messages})


@app.route("/api/upload", methods=["POST"])
@login_required
def api_upload_file():
    """Handle media and attachment uploads for chat messages."""
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file uploaded."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "error": "Empty filename."}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        timestamp_prefix = f"{int(time.time())}_{random.randint(100, 999)}_"
        saved_filename = timestamp_prefix + filename
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], saved_filename)
        file.save(file_path)

        file_url = f"/uploads/{saved_filename}"
        is_image = filename.lower().rsplit(".", 1)[1] in {"png", "jpg", "jpeg", "gif", "webp"}
        return jsonify({
            "success": True,
            "file_url": file_url,
            "filename": filename,
            "is_image": is_image
        })

    return jsonify({"success": False, "error": "File extension not allowed."}), 400


# ==============================================================================
# Bot Auto-Response Utilities
# ==============================================================================

BOT_JOKES = [
    "Why do programmers prefer dark mode? Because light attracts bugs! 🐛",
    "There are only 10 types of people in the world: those who understand binary, and those who don't. 💻",
    "Why did the web developer leave the restaurant? Because of the table layout! 🍽️",
    "A SQL query walks into a bar, walks up to two tables and asks: 'Can I join you?' 🍻",
    "How do you comfort a JavaScript bug? You console it! 😄"
]

BOT_QUOTES = [
    "“Talk is cheap. Show me the code.” — Linus Torvalds",
    "“Programs must be written for people to read, and only incidentally for machines to execute.” — Harold Abelson",
    "“First, solve the problem. Then, write the code.” — John Johnson",
    "“Simplicity is prerequisite for reliability.” — Edsger W. Dijkstra"
]


def handle_bot_interaction(room_id, message_content):
    """Analyze incoming message and emit simulated bot response if triggered."""
    trigger_words = ["@nova", "/bot", "/help", "/joke", "/quote", "hello bot", "hey bot"]
    lower_content = message_content.lower()

    if not any(t in lower_content for t in trigger_words):
        return

    # Look up Nova Bot user
    bot_user = get_user_by_username("nova_bot")
    if not bot_user:
        return

    response_text = ""
    if "/joke" in lower_content or "joke" in lower_content:
        response_text = f"🤖 **Nova Joke**: {random.choice(BOT_JOKES)}"
    elif "/quote" in lower_content or "quote" in lower_content:
        response_text = f"🤖 **Tech Quote**: {random.choice(BOT_QUOTES)}"
    elif "/help" in lower_content:
        response_text = (
            "🤖 **Nova Assistant Commands**:\n"
            "• `/joke` - Get a developer joke\n"
            "• `/quote` - Inspire yourself with computer science quotes\n"
            "• `/help` - Show this menu\n"
            "• Mention `@nova` in any message for a friendly greeting!"
        )
    else:
        greetings = [
            "🤖 Beep boop! Hello there! I'm Nova, your real-time assistant. Type `/help` for commands!",
            "🤖 Greetings! Real-time WebSockets are running smoothly with 0ms lag! ⚡",
            "🤖 At your service! Need a joke? Type `/joke` or try sharing some code snippets!"
        ]
        response_text = random.choice(greetings)

    def send_bot_reply():
        time.sleep(0.6)  # Simulate natural typing delay
        saved_bot_msg = save_message(
            room_id=room_id,
            sender_id=bot_user["id"],
            content=response_text,
            message_type="bot"
        )
        socketio.emit("new_message", saved_bot_msg, to=f"room_{room_id}")

    threading.Thread(target=send_bot_reply, daemon=True).start()


# ==============================================================================
# Socket.IO Event Handlers
# ==============================================================================

@socketio.on("connect")
def on_connect(auth=None):
    """Handle client connection over WebSocket or polling."""
    user_id = session.get("user_id")

    # Support console client passing user_id or credentials in auth dictionary
    if not user_id and isinstance(auth, dict):
        user_id = auth.get("user_id")

    if not user_id:
        # Guest or unauthenticated connection
        return

    sid = request.sid
    online_users[user_id].add(sid)
    sid_to_user[sid] = user_id

    # Update database status
    update_user_status(user_id, "online")

    user_info = get_user_by_id(user_id)
    # Broadcast status change to everyone
    emit("user_status_change", {
        "user_id": user_id,
        "status": "online",
        "user": user_info
    }, broadcast=True)

    # Send current online users list back to the newly connected socket
    emit("online_users_list", {
        "online_user_ids": list(online_users.keys())
    })


@socketio.on("disconnect")
def on_disconnect():
    """Handle client disconnect and update online presence."""
    sid = request.sid
    user_id = sid_to_user.pop(sid, None)

    if user_id and user_id in online_users:
        online_users[user_id].discard(sid)
        if len(online_users[user_id]) == 0:
            del online_users[user_id]
            update_user_status(user_id, "offline")
            emit("user_status_change", {
                "user_id": user_id,
                "status": "offline"
            }, broadcast=True)


@socketio.on("join_room")
def on_join_room(data):
    """Client joins a specific channel or DM room."""
    room_id = data.get("room_id")
    if not room_id:
        return

    room_channel = f"room_{room_id}"
    join_room(room_channel)

    user_id = session.get("user_id") or sid_to_user.get(request.sid)
    user = get_user_by_id(user_id) if user_id else None

    emit("room_joined", {
        "room_id": room_id,
        "message": f"Successfully joined room {room_id}"
    })


@socketio.on("leave_room")
def on_leave_room(data):
    """Client leaves a room."""
    room_id = data.get("room_id")
    if room_id:
        leave_room(f"room_{room_id}")


@socketio.on("send_message")
def on_send_message(data):
    """Handle incoming message broadcast and database persistence."""
    room_id = data.get("room_id")
    content = data.get("content", "").strip()
    message_type = data.get("message_type", "text")
    file_url = data.get("file_url", None)

    user_id = session.get("user_id") or sid_to_user.get(request.sid)
    if not user_id:
        emit("error", {"message": "You must be logged in to send messages."})
        return

    if not content and not file_url:
        return

    # Save to SQLite database
    saved_msg = save_message(
        room_id=room_id,
        sender_id=user_id,
        content=content,
        message_type=message_type,
        file_url=file_url
    )

    # Broadcast message to all clients currently in the room
    emit("new_message", saved_msg, to=f"room_{room_id}")

    # Check for bot trigger
    handle_bot_interaction(room_id, content)


@socketio.on("typing")
def on_typing(data):
    """Broadcast typing indicator to others in the room."""
    room_id = data.get("room_id")
    user_id = session.get("user_id") or sid_to_user.get(request.sid)
    if not room_id or not user_id:
        return

    user = get_user_by_id(user_id)
    if user:
        emit("user_typing", {
            "room_id": room_id,
            "user_id": user_id,
            "username": user["username"],
            "display_name": user["display_name"]
        }, to=f"room_{room_id}", include_self=False)


@socketio.on("stop_typing")
def on_stop_typing(data):
    """Stop typing indicator in the room."""
    room_id = data.get("room_id")
    user_id = session.get("user_id") or sid_to_user.get(request.sid)
    if not room_id or not user_id:
        return

    emit("user_stop_typing", {
        "room_id": room_id,
        "user_id": user_id
    }, to=f"room_{room_id}", include_self=False)


@socketio.on("reaction")
def on_reaction(data):
    """Handle emoji reactions on messages."""
    message_id = data.get("message_id")
    room_id = data.get("room_id")
    emoji = data.get("emoji")
    user_id = session.get("user_id") or sid_to_user.get(request.sid)

    if not message_id or not emoji or not user_id:
        return

    action, updated_reactions = toggle_reaction(message_id, user_id, emoji)

    emit("reaction_updated", {
        "message_id": message_id,
        "room_id": room_id,
        "reactions": updated_reactions,
        "action": action,
        "user_id": user_id
    }, to=f"room_{room_id}")


@socketio.on("status_update")
def on_status_update(data):
    """Allow user to explicitly set status (online, away, busy)."""
    status = data.get("status", "online")
    if status not in {"online", "away", "busy"}:
        status = "online"

    user_id = session.get("user_id") or sid_to_user.get(request.sid)
    if user_id:
        update_user_status(user_id, status)
        emit("user_status_change", {
            "user_id": user_id,
            "status": status
        }, broadcast=True)


# ==============================================================================
# Main Runner
# ==============================================================================

if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    print("=" * 60)
    print("  NexusChat Real-Time Server starting...")
    print("  Web Interface: http://localhost:5000")
    print("  Channels available: #general, #tech-talk, #random, #announcements")
    print("  Demo credentials:")
    print("     - alex / password123")
    print("     - sarah / password123")
    print("=" * 60)
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)
