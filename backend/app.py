"""
Flask application and WebSocket server for NexusChat.
Manages HTTP API routes, static asset delivery, Socket.IO events,
read receipts, group chats, notifications, moderation, and admin dashboard.
"""

import os
import re
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
    url_for,
)
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename

from moderation import sanitize_message

# Local database operations
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
    edit_message,
    delete_message,
    forward_message,
    get_room_messages,
    toggle_reaction,
    get_or_create_dm_room,
    can_user_access_room,
    # Groups
    create_group_room,
    get_user_groups,
    get_group_members,
    add_group_member,
    remove_group_member,
    update_group_info,
    is_group_admin,
    # Read receipts
    record_message_delivery,
    record_room_deliveries,
    mark_messages_as_read,
    get_unread_counts,
    # Notifications
    create_notification,
    get_user_notifications,
    get_unread_notification_count,
    mark_notification_as_read,
    mark_all_notifications_as_read,
    # Moderation & Reports
    create_report,
    get_reports,
    update_report_status,
    log_moderation_action,
    get_moderation_logs,
    # Admin
    get_admin_stats,
    search_users,
    set_user_suspension,
    set_user_role,
)

# Authentication & authorization
from auth import (
    register_user_account,
    authenticate_user,
    login_user_session,
    logout_user_session,
    get_current_user,
    login_required,
    admin_required,
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

# Secret key from environment or secure development fallback
app.config["SECRET_KEY"] = os.environ.get(
    "FLASK_SECRET_KEY",
    "dev-only-change-this-secret-key-nexuschat-2026",
)

app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
app.config["UPLOAD_FOLDER"] = UPLOADS_DIR

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
)

# In-memory online user tracking: user_id -> set of socket IDs
online_users = defaultdict(set)
sid_to_user = {}

ALLOWED_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif", "webp",
    "pdf", "txt", "zip", "doc", "docx", "mp3"
}


def allowed_file(filename):
    """Check whether a file extension is permitted."""
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


# Run database initialization and migrations once at startup
init_db()


# ==============================================================================
# Helper: Real-time Notifications & Delivery
# ==============================================================================

def send_user_notification(user_id, notif_dict):
    """Send a real-time notification to a specific user's private socket room."""
    if not notif_dict:
        return
    socketio.emit(
        "new_notification",
        notif_dict,
        to=f"user_{user_id}"
    )


def parse_and_notify_mentions(content, room_id, sender_id, sender_name, room_name):
    """Find @username in message content and notify mentioned users."""
    if not content:
        return

    matches = set(re.findall(r"@([a-zA-Z0-9_]+)", content))
    for username in matches:
        target = get_user_by_username(username)
        if target and target["id"] != sender_id:
            notif = create_notification(
                user_id=target["id"],
                actor_id=sender_id,
                notif_type="mention",
                title="You were mentioned",
                content=f"@{sender_name} mentioned you in #{room_name}: \"{content[:80]}\"",
                room_id=room_id
            )
            if notif:
                send_user_notification(target["id"], notif)


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
    """Serve the main chat workspace."""
    return send_from_directory(FRONTEND_DIR, "chat.html")


@app.route("/admin")
@admin_required
def admin_page():
    """Serve the administrative dashboard."""
    return send_from_directory(FRONTEND_DIR, "admin.html")


@app.route("/frontend/<path:filename>")
def serve_frontend_assets(filename):
    """Serve frontend CSS, JavaScript, and other static assets."""
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

    if not all(
        isinstance(val, str) for val in (username, email, password, display_name, bio)
    ):
        return jsonify({
            "success": False,
            "error": "All registration fields must contain text.",
        }), 400

    try:
        success, result = register_user_account(
            username=username,
            email=email,
            password=password,
            display_name=display_name,
            bio=bio,
        )

        if not success:
            return jsonify({
                "success": False,
                "error": result,
            }), 400

        login_user_session(result)

        safe_user = {
            k: v for k, v in result.items()
            if k not in {"password", "password_hash"}
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
            k: v for k, v in result.items()
            if k not in {"password", "password_hash"}
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
    """Log out the current user session."""
    logout_user_session()
    return jsonify({
        "success": True,
        "message": "Logged out successfully.",
    })


@app.route("/api/auth/me", methods=["GET"])
def api_me():
    """Return the currently authenticated user's profile."""
    user = get_current_user()
    if not user:
        return jsonify({
            "authenticated": False,
        }), 401

    safe_user = {
        k: v for k, v in user.items()
        if k not in {"password", "password_hash"}
    }

    return jsonify({
        "authenticated": True,
        "user": safe_user,
    }), 200


# ==============================================================================
# Channels / Rooms API
# ==============================================================================

@app.route("/api/rooms", methods=["GET"])
@login_required
def api_get_rooms():
    """Return all available public chat channels."""
    rooms = get_all_rooms()
    return jsonify({
        "success": True,
        "rooms": rooms,
    })


@app.route("/api/rooms", methods=["POST"])
@login_required
def api_create_room():
    """Create a new public chat channel."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({
            "success": False,
            "error": "Please send valid JSON data.",
        }), 400

    name = data.get("name", "")
    description = data.get("description", "")
    icon = data.get("icon", "#")

    if not all(isinstance(v, str) for v in (name, description, icon)):
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

    current_user_id = session.get("user_id")

    try:
        room = create_room(
            name=name,
            description=description,
            icon=icon,
            is_private=0,
            room_type="channel",
            creator_id=current_user_id,
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
    """Return registered users with their current online presence."""
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
# Message History API (Secured)
# ==============================================================================

@app.route("/api/messages/<int:room_id>", methods=["GET"])
@login_required
def api_get_messages(room_id):
    """Retrieve messages for a particular room with security access verification."""
    user_id = session.get("user_id")
    limit = request.args.get("limit", 60, type=int)
    limit = max(1, min(limit, 100))

    room = get_room_by_id(room_id)
    if not room:
        return jsonify({
            "success": False,
            "error": "Room not found.",
        }), 404

    # Security check: verify user has permission to view this room's messages
    if not can_user_access_room(user_id, room_id):
        return jsonify({
            "success": False,
            "error": "Forbidden: You do not have access to this conversation.",
        }), 403

    messages = get_room_messages(
        room_id,
        limit=limit,
        current_user_id=user_id
    )

    # Automatically mark room messages as delivered/read for this user
    record_room_deliveries(room_id, user_id)
    mark_messages_as_read(room_id, user_id)

    return jsonify({
        "success": True,
        "room": room,
        "messages": messages,
    })


# ==============================================================================
# Message Management API (Edit, Delete, Forward)
# ==============================================================================

@app.route("/api/messages/<int:message_id>", methods=["PUT"])
@login_required
def api_edit_message(message_id):
    """Edit an existing message (user can only edit own messages)."""
    user_id = session.get("user_id")
    data = request.get_json(silent=True) or {}
    new_content = data.get("content", "").strip()

    if not new_content:
        return jsonify({"success": False, "error": "Message content cannot be empty."}), 400
    if len(new_content) > 5000:
        return jsonify({"success": False, "error": "Message exceeds maximum length."}), 400

    # Sanitize content
    cleaned_content, _ = sanitize_message(new_content)

    success, result = edit_message(message_id, user_id, cleaned_content)
    if not success:
        return jsonify({"success": False, "error": result}), 403

    # Broadcast edit to all room members
    socketio.emit(
        "message_edited",
        result,
        to=f"room_{result['room_id']}"
    )

    return jsonify({"success": True, "message": result})


@app.route("/api/messages/<int:message_id>", methods=["DELETE"])
@login_required
def api_delete_message(message_id):
    """Delete a message (soft delete, author or admin only)."""
    user = get_current_user()
    is_admin = (user.get("role") == "admin")

    success, result = delete_message(message_id, user["id"], is_admin=is_admin)
    if not success:
        return jsonify({"success": False, "error": result}), 403

    # Broadcast deletion to all room members
    socketio.emit(
        "message_deleted",
        {
            "message_id": message_id,
            "room_id": result["room_id"],
            "message": result
        },
        to=f"room_{result['room_id']}"
    )

    return jsonify({"success": True, "message_id": message_id})


@app.route("/api/messages/forward", methods=["POST"])
@login_required
def api_forward_message():
    """Forward a message to another room/conversation."""
    user_id = session.get("user_id")
    data = request.get_json(silent=True) or {}
    message_id = data.get("message_id")
    target_room_id = data.get("target_room_id")

    if not message_id or not target_room_id:
        return jsonify({"success": False, "error": "message_id and target_room_id are required."}), 400

    # Verify user has access to target room
    if not can_user_access_room(user_id, target_room_id):
        return jsonify({"success": False, "error": "Forbidden: Cannot forward to this room."}), 403

    forwarded = forward_message(message_id, target_room_id, user_id)
    if not forwarded:
        return jsonify({"success": False, "error": "Failed to forward message."}), 500

    socketio.emit(
        "new_message",
        forwarded,
        to=f"room_{target_room_id}"
    )

    return jsonify({"success": True, "message": forwarded}), 201


# ==============================================================================
# Read Receipts and Unread Counts API
# ==============================================================================

@app.route("/api/unread-counts", methods=["GET"])
@login_required
def api_get_unread_counts():
    """Retrieve unread message counts for all conversations for the current user."""
    user_id = session.get("user_id")
    counts = get_unread_counts(user_id)
    return jsonify({
        "success": True,
        "unread_counts": counts,
    })


@app.route("/api/rooms/<int:room_id>/read", methods=["POST"])
@login_required
def api_mark_room_read(room_id):
    """Mark all unread messages in a room as read by current user."""
    user_id = session.get("user_id")
    read_ids = mark_messages_as_read(room_id, user_id)

    if read_ids:
        socketio.emit(
            "messages_read",
            {
                "room_id": room_id,
                "user_id": user_id,
                "message_ids": read_ids,
            },
            to=f"room_{room_id}"
        )

    return jsonify({"success": True, "read_ids": read_ids})


# ==============================================================================
# Direct Messages API
# ==============================================================================

@app.route("/api/dm/<int:target_user_id>", methods=["GET"])
@login_required
def api_get_or_create_dm(target_user_id):
    """Retrieve or create a private direct message conversation."""
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

        room["display_name"] = target_user.get(
            "display_name",
            target_user.get("username", "User"),
        )
        room["target_user"] = target_user

        messages = get_room_messages(
            room["id"],
            limit=60,
            current_user_id=current_user_id
        )

        # Mark read
        record_room_deliveries(room["id"], current_user_id)
        mark_messages_as_read(room["id"], current_user_id)

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
# Group Chat API
# ==============================================================================

@app.route("/api/groups", methods=["GET"])
@login_required
def api_get_groups():
    """Retrieve all group chats the current user belongs to."""
    user_id = session.get("user_id")
    groups = get_user_groups(user_id)
    return jsonify({
        "success": True,
        "groups": groups,
    })


@app.route("/api/groups", methods=["POST"])
@login_required
def api_create_group():
    """Create a new group conversation."""
    user = get_current_user()
    data = request.get_json(silent=True) or {}

    name = data.get("name", "").strip()
    description = data.get("description", "").strip()
    member_ids = data.get("member_ids", [])
    avatar_color = data.get("avatar_color", "#8b5cf6")

    if not name:
        return jsonify({"success": False, "error": "Group name is required."}), 400

    group_room = create_group_room(
        name=name,
        description=description,
        creator_id=user["id"],
        member_ids=member_ids,
        avatar_color=avatar_color,
    )

    if not group_room:
        return jsonify({"success": False, "error": "Failed to create group."}), 500

    # Notify all added members
    for mid in member_ids:
        if int(mid) != user["id"]:
            notif = create_notification(
                user_id=mid,
                actor_id=user["id"],
                notif_type="group_invite",
                title="Added to Group",
                content=f"You were added to '{name}' by {user.get('display_name') or user.get('username')}",
                room_id=group_room["id"]
            )
            if notif:
                send_user_notification(mid, notif)
            # Emit socket event so their group list updates
            socketio.emit("group_added", group_room, to=f"user_{mid}")

    return jsonify({"success": True, "group": group_room}), 201


@app.route("/api/groups/<int:room_id>/members", methods=["GET"])
@login_required
def api_get_group_members(room_id):
    """Retrieve members of a group with roles and online status."""
    user_id = session.get("user_id")
    if not can_user_access_room(user_id, room_id):
        return jsonify({"success": False, "error": "Forbidden: Not a member of this group."}), 403

    members = get_group_members(room_id)
    for m in members:
        m["status"] = "online" if online_users.get(m["id"]) else "offline"

    return jsonify({"success": True, "members": members})


@app.route("/api/groups/<int:room_id>/members", methods=["POST"])
@login_required
def api_add_group_member(room_id):
    """Add a user to a group (Group admin only)."""
    current_user = get_current_user()
    if not is_group_admin(room_id, current_user["id"]):
        return jsonify({"success": False, "error": "Only group admins can add members."}), 403

    data = request.get_json(silent=True) or {}
    new_user_id = data.get("user_id")
    if not new_user_id:
        return jsonify({"success": False, "error": "user_id is required."}), 400

    target = get_user_by_id(new_user_id)
    if not target:
        return jsonify({"success": False, "error": "User not found."}), 404

    success = add_group_member(room_id, new_user_id)
    if not success:
        return jsonify({"success": False, "error": "Could not add member."}), 500

    room = get_room_by_id(room_id)

    # Notify new member
    notif = create_notification(
        user_id=new_user_id,
        actor_id=current_user["id"],
        notif_type="group_invite",
        title="Added to Group",
        content=f"You were added to '{room.get('name')}' by {current_user.get('display_name')}",
        room_id=room_id
    )
    if notif:
        send_user_notification(new_user_id, notif)
    socketio.emit("group_added", room, to=f"user_{new_user_id}")

    # Broadcast member joined to group room
    socketio.emit(
        "group_member_change",
        {
            "room_id": room_id,
            "action": "joined",
            "user": target
        },
        to=f"room_{room_id}"
    )

    return jsonify({"success": True, "message": "Member added successfully."})


@app.route("/api/groups/<int:room_id>/members/<int:target_user_id>", methods=["DELETE"])
@login_required
def api_remove_group_member(room_id, target_user_id):
    """Remove a user from group (Admin can remove; member can leave)."""
    current_user_id = session.get("user_id")

    # Member leaving group or Admin removing member
    if current_user_id != target_user_id and not is_group_admin(room_id, current_user_id):
        return jsonify({"success": False, "error": "Forbidden: Only admins can remove other members."}), 403

    success = remove_group_member(room_id, target_user_id)
    if not success:
        return jsonify({"success": False, "error": "Could not remove member."}), 500

    socketio.emit(
        "group_member_change",
        {
            "room_id": room_id,
            "action": "left",
            "user_id": target_user_id
        },
        to=f"room_{room_id}"
    )

    return jsonify({"success": True, "message": "Member removed."})


@app.route("/api/groups/<int:room_id>", methods=["PUT"])
@login_required
def api_update_group_info(room_id):
    """Update group name and topic (Admin only)."""
    current_user_id = session.get("user_id")
    if not is_group_admin(room_id, current_user_id):
        return jsonify({"success": False, "error": "Only group admins can update group info."}), 403

    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    description = data.get("description", "").strip()

    if not name:
        return jsonify({"success": False, "error": "Group name is required."}), 400

    updated = update_group_info(room_id, name, description)
    if not updated:
        return jsonify({"success": False, "error": "Failed to update group."}), 500

    socketio.emit(
        "group_updated",
        updated,
        to=f"room_{room_id}"
    )

    return jsonify({"success": True, "group": updated})


# ==============================================================================
# Notification Center API
# ==============================================================================

@app.route("/api/notifications", methods=["GET"])
@login_required
def api_get_notifications():
    """Retrieve notifications and unread badge count for current user."""
    user_id = session.get("user_id")
    limit = request.args.get("limit", 50, type=int)

    notifs = get_user_notifications(user_id, limit=limit)
    unread_count = get_unread_notification_count(user_id)

    return jsonify({
        "success": True,
        "notifications": notifs,
        "unread_count": unread_count,
    })


@app.route("/api/notifications/<int:notif_id>/read", methods=["POST"])
@login_required
def api_mark_notification_read(notif_id):
    """Mark a single notification as read."""
    user_id = session.get("user_id")
    mark_notification_as_read(notif_id, user_id)
    return jsonify({"success": True})


@app.route("/api/notifications/read-all", methods=["POST"])
@login_required
def api_mark_all_notifications_read():
    """Mark all notifications as read."""
    user_id = session.get("user_id")
    mark_all_notifications_as_read(user_id)
    return jsonify({"success": True})


# ==============================================================================
# Message Reporting API (User Facing)
# ==============================================================================

@app.route("/api/reports", methods=["POST"])
@login_required
def api_report_message():
    """Submit a report against an inappropriate message."""
    user_id = session.get("user_id")
    data = request.get_json(silent=True) or {}

    message_id = data.get("message_id")
    reason = data.get("reason", "").strip()
    details = data.get("details", "").strip()

    if not message_id or not reason:
        return jsonify({"success": False, "error": "Message ID and reason are required."}), 400

    success, result = create_report(message_id, user_id, reason, details)
    if not success:
        return jsonify({"success": False, "error": result}), 400

    return jsonify({
        "success": True,
        "message": "Report submitted successfully. A moderator will review it.",
        "report": result
    }), 201


# ==============================================================================
# Admin Dashboard & Moderation API
# ==============================================================================

@app.route("/api/admin/stats", methods=["GET"])
@admin_required
def api_admin_stats():
    """Return dashboard analytics and platform metrics."""
    stats = get_admin_stats()
    return jsonify({"success": True, "stats": stats})


@app.route("/api/admin/users", methods=["GET"])
@admin_required
def api_admin_users():
    """Search and list registered users."""
    q = request.args.get("q", "")
    users = search_users(q)
    return jsonify({"success": True, "users": users})


@app.route("/api/admin/users/<int:user_id>/suspend", methods=["POST"])
@admin_required
def api_admin_suspend_user(user_id):
    """Suspend or reactivate a user account."""
    admin_user = get_current_user()
    data = request.get_json(silent=True) or {}
    suspend = bool(data.get("suspend", True))

    if user_id == admin_user["id"]:
        return jsonify({"success": False, "error": "Administrators cannot suspend themselves."}), 400

    set_user_suspension(user_id, suspend)

    action_label = "suspend_user" if suspend else "reactivate_user"
    log_moderation_action(
        admin_id=admin_user["id"],
        action=action_label,
        target_user_id=user_id,
        details=data.get("details", "")
    )

    # If suspended, force-disconnect active sockets of that user
    if suspend and user_id in online_users:
        socketio.emit(
            "account_suspended",
            {"message": "Your account has been suspended by an administrator."},
            to=f"user_{user_id}"
        )

    return jsonify({"success": True, "is_suspended": 1 if suspend else 0})


@app.route("/api/admin/users/<int:user_id>/role", methods=["POST"])
@admin_required
def api_admin_set_role(user_id):
    """Change user role (user/admin)."""
    admin_user = get_current_user()
    data = request.get_json(silent=True) or {}
    new_role = data.get("role")

    if new_role not in ("user", "admin"):
        return jsonify({"success": False, "error": "Invalid role."}), 400

    set_user_role(user_id, new_role)
    log_moderation_action(
        admin_id=admin_user["id"],
        action="change_role",
        target_user_id=user_id,
        details=f"Changed role to {new_role}"
    )

    return jsonify({"success": True, "role": new_role})


@app.route("/api/admin/reports", methods=["GET"])
@admin_required
def api_admin_reports():
    """View reported messages."""
    status = request.args.get("status")
    reports = get_reports(status)
    return jsonify({"success": True, "reports": reports})


@app.route("/api/admin/reports/<int:report_id>/action", methods=["POST"])
@admin_required
def api_admin_report_action(report_id):
    """Execute moderation action on a report (dismiss, delete_message, suspend_user)."""
    admin_user = get_current_user()
    data = request.get_json(silent=True) or {}
    action = data.get("action", "").strip()  # dismiss, delete_message, suspend_user, warn_user
    details = data.get("details", "").strip()

    conn_reports = get_reports()
    report = next((r for r in conn_reports if r["id"] == report_id), None)
    if not report:
        return jsonify({"success": False, "error": "Report not found."}), 404

    target_user_id = report["reported_user_id"]
    message_id = report["message_id"]

    if action == "dismiss":
        update_report_status(report_id, "dismissed", admin_user["id"])
        log_moderation_action(admin_user["id"], "dismiss_report", target_user_id, message_id, report_id, details)

    elif action == "delete_message":
        delete_message(message_id, admin_user["id"], is_admin=True)
        update_report_status(report_id, "resolved", admin_user["id"])
        log_moderation_action(admin_user["id"], "delete_message", target_user_id, message_id, report_id, details)

        socketio.emit(
            "message_deleted",
            {"message_id": message_id, "room_id": report["room_id"]},
            to=f"room_{report['room_id']}"
        )

    elif action == "suspend_user":
        set_user_suspension(target_user_id, True)
        update_report_status(report_id, "resolved", admin_user["id"])
        log_moderation_action(admin_user["id"], "suspend_user", target_user_id, message_id, report_id, details)

        socketio.emit(
            "account_suspended",
            {"message": "Your account has been suspended due to policy violations."},
            to=f"user_{target_user_id}"
        )

    elif action == "warn_user":
        update_report_status(report_id, "resolved", admin_user["id"])
        log_moderation_action(admin_user["id"], "warn_user", target_user_id, message_id, report_id, details)

        notif = create_notification(
            user_id=target_user_id,
            actor_id=admin_user["id"],
            notif_type="admin",
            title="Moderation Warning",
            content=f"Your message was reported and flagged. Reason: {details or 'Inappropriate content.'}",
            message_id=message_id
        )
        if notif:
            send_user_notification(target_user_id, notif)

    else:
        return jsonify({"success": False, "error": "Invalid action."}), 400

    return jsonify({"success": True, "action": action, "report_id": report_id})


@app.route("/api/admin/moderation-logs", methods=["GET"])
@admin_required
def api_admin_moderation_logs():
    """Retrieve moderation audit log history."""
    limit = request.args.get("limit", 100, type=int)
    logs = get_moderation_logs(limit)
    return jsonify({"success": True, "logs": logs})


@app.route("/api/admin/messages/<int:message_id>", methods=["DELETE"])
@admin_required
def api_admin_delete_message(message_id):
    """Admin endpoint to immediately delete inappropriate message."""
    admin_user = get_current_user()
    success, result = delete_message(message_id, admin_user["id"], is_admin=True)
    if not success:
        return jsonify({"success": False, "error": result}), 400

    log_moderation_action(
        admin_id=admin_user["id"],
        action="admin_delete_message",
        message_id=message_id,
        details="Removed by admin from dashboard"
    )

    socketio.emit(
        "message_deleted",
        {"message_id": message_id, "room_id": result["room_id"]},
        to=f"room_{result['room_id']}"
    )

    return jsonify({"success": True, "message_id": message_id})


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

    timestamp_prefix = f"{int(time.time())}_{random.randint(100, 999)}_"
    saved_filename = timestamp_prefix + filename
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], saved_filename)

    try:
        file.save(file_path)
        extension = filename.rsplit(".", 1)[1].lower()
        is_image = extension in {"png", "jpg", "jpeg", "gif", "webp"}

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
        "@nova", "/bot", "/help", "/joke", "/quote",
        "hello bot", "hey bot",
    ]

    lower_content = message_content.lower()
    if not any(trigger in lower_content for trigger in trigger_words):
        return

    bot_user = get_user_by_username("nova_bot")
    if not bot_user:
        return

    if "/joke" in lower_content or "joke" in lower_content:
        response_text = f"🤖 **Nova Joke**: {random.choice(BOT_JOKES)}"
    elif "/quote" in lower_content or "quote" in lower_content:
        response_text = f"🤖 **Tech Quote**: {random.choice(BOT_QUOTES)}"
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

    threading.Thread(target=send_bot_reply, daemon=True).start()


# ==============================================================================
# Socket.IO Authentication and Presence
# ==============================================================================

@socketio.on("connect")
def on_connect(auth=None):
    """Register an authenticated Socket.IO connection and join user-specific room."""
    user_id = session.get("user_id")
    if not user_id:
        return

    user = get_user_by_id(user_id)
    if not user or user.get("is_suspended"):
        return

    sid = request.sid
    online_users[user_id].add(sid)
    sid_to_user[sid] = user_id

    # Join user's private notification and direct message room
    join_room(f"user_{user_id}")

    update_user_status(user_id, "online")

    emit(
        "user_status_change",
        {
            "user_id": user_id,
            "status": "online",
            "user": user,
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

        # Mark user offline only after their final browser tab disconnects
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
# Socket.IO Room Management (Strictly Authorized)
# ==============================================================================

@socketio.on("join_room")
def on_join_room(data):
    """Join a chat room after strictly verifying user authorization."""
    if not isinstance(data, dict):
        emit("error", {"message": "Invalid room data."})
        return

    room_id = data.get("room_id")
    if not isinstance(room_id, (int, str)) or not str(room_id).isdigit():
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

    # Strict authorization: Verify user is permitted to join this room
    if not can_user_access_room(user_id, room_id):
        emit("error", {"message": "Forbidden: You are not authorized to join this room."})
        return

    join_room(f"room_{room_id}")

    # Mark room messages as delivered to this user
    record_room_deliveries(room_id, user_id)
    read_ids = mark_messages_as_read(room_id, user_id)

    if read_ids:
        emit(
            "messages_read",
            {
                "room_id": room_id,
                "user_id": user_id,
                "message_ids": read_ids,
            },
            to=f"room_{room_id}"
        )

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
    if isinstance(room_id, (int, str)) and str(room_id).isdigit():
        leave_room(f"room_{int(room_id)}")


# ==============================================================================
# Socket.IO Messaging & Events (Replies, Mentions, Read Receipts)
# ==============================================================================

@socketio.on("send_message")
def on_send_message(data):
    """Save and broadcast a new message with reply, mention, and profanity handling."""
    if not isinstance(data, dict):
        emit("error", {"message": "Invalid message payload."})
        return

    room_id = data.get("room_id")
    content = data.get("content", "")
    message_type = data.get("message_type", "text")
    file_url = data.get("file_url")
    reply_to_id = data.get("reply_to_id")

    if not isinstance(room_id, (int, str)) or not str(room_id).isdigit():
        emit("error", {"message": "Invalid room ID."})
        return

    room_id = int(room_id)

    if not isinstance(content, str):
        content = ""
    content = content.strip()

    if len(content) > 5000:
        emit("error", {"message": "Message exceeds maximum length of 5000 characters."})
        return

    if not isinstance(message_type, str):
        message_type = "text"

    if file_url is not None and not isinstance(file_url, str):
        emit("error", {"message": "Invalid file attachment."})
        return

    user_id = session.get("user_id") or sid_to_user.get(request.sid)
    if not user_id:
        emit("error", {"message": "You must be logged in to send messages."})
        return

    user = get_user_by_id(user_id)
    if not user or user.get("is_suspended"):
        emit("error", {"message": "Your account is suspended."})
        return

    if not content and not file_url:
        return

    # Verify authorization
    if not can_user_access_room(user_id, room_id):
        emit("error", {"message": "Forbidden: You cannot send messages in this room."})
        return

    room = get_room_by_id(room_id)
    if not room:
        emit("error", {"message": "Room not found."})
        return

    try:
        # Sanitize message content for profanity, returning string and boolean
        cleaned_content = content
        if content:
            cleaned_content, _ = sanitize_message(content)

        saved_msg = save_message(
            room_id=room_id,
            sender_id=user_id,
            content=cleaned_content,
            message_type=message_type,
            file_url=file_url,
            reply_to_id=reply_to_id,
        )

        if not saved_msg:
            emit("error", {"message": "Message could not be saved."})
            return

        # Broadcast new message to the room
        emit(
            "new_message",
            saved_msg,
            to=f"room_{room_id}",
        )

        # Notify recipient(s)
        sender_name = user.get("display_name") or user.get("username")
        room_name = room.get("name") or "chat"

        # 1. Reply notification
        if reply_to_id and saved_msg.get("reply_to"):
            parent_msg = get_message_by_id(reply_to_id)
            if parent_msg and parent_msg["sender_id"] != user_id:
                notif = create_notification(
                    user_id=parent_msg["sender_id"],
                    actor_id=user_id,
                    notif_type="reply",
                    title="Reply to your message",
                    content=f"{sender_name} replied: \"{cleaned_content[:80]}\"",
                    room_id=room_id,
                    message_id=saved_msg["id"]
                )
                if notif:
                    send_user_notification(parent_msg["sender_id"], notif)

        # 2. Direct message notification
        if room.get("is_private") and room.get("room_type") == "dm":
            other_user_id = room["dm_user2_id"] if room["dm_user1_id"] == user_id else room["dm_user1_id"]
            if other_user_id:
                record_message_delivery(saved_msg["id"], other_user_id)
                notif = create_notification(
                    user_id=other_user_id,
                    actor_id=user_id,
                    notif_type="dm",
                    title=f"New Message from {sender_name}",
                    content=cleaned_content[:80] or "Sent an attachment.",
                    room_id=room_id,
                    message_id=saved_msg["id"]
                )
                if notif:
                    send_user_notification(other_user_id, notif)

        # 3. Group message notifications
        elif room.get("room_type") == "group":
            members = get_group_members(room_id)
            for m in members:
                if m["id"] != user_id:
                    record_message_delivery(saved_msg["id"], m["id"])
                    notif = create_notification(
                        user_id=m["id"],
                        actor_id=user_id,
                        notif_type="group_message",
                        title=f"New message in {room_name}",
                        content=f"{sender_name}: {cleaned_content[:80] or 'Sent an attachment'}",
                        room_id=room_id,
                        message_id=saved_msg["id"]
                    )
                    if notif:
                        send_user_notification(m["id"], notif)

        # 4. User mentions (@username)
        parse_and_notify_mentions(cleaned_content, room_id, user_id, sender_name, room_name)

        # Trigger Nova Bot if active
        if cleaned_content:
            handle_bot_interaction(room_id, cleaned_content)

    except Exception:
        app.logger.exception("Sending message failed")
        emit("error", {"message": "Could not send the message."})


@socketio.on("edit_message")
def on_socket_edit_message(data):
    """Socket event for editing a message."""
    if not isinstance(data, dict):
        return

    message_id = data.get("message_id")
    new_content = data.get("content", "").strip()
    user_id = session.get("user_id") or sid_to_user.get(request.sid)

    if not user_id or not message_id or not new_content:
        return

    cleaned_content, _ = sanitize_message(new_content)
    success, result = edit_message(message_id, user_id, cleaned_content)
    if success:
        emit("message_edited", result, to=f"room_{result['room_id']}")


@socketio.on("delete_message")
def on_socket_delete_message(data):
    """Socket event for deleting a message."""
    if not isinstance(data, dict):
        return

    message_id = data.get("message_id")
    user_id = session.get("user_id") or sid_to_user.get(request.sid)
    if not user_id or not message_id:
        return

    user = get_user_by_id(user_id)
    is_admin = (user.get("role") == "admin") if user else False

    success, result = delete_message(message_id, user_id, is_admin=is_admin)
    if success:
        emit(
            "message_deleted",
            {"message_id": message_id, "room_id": result["room_id"], "message": result},
            to=f"room_{result['room_id']}"
        )


@socketio.on("mark_read")
def on_socket_mark_read(data):
    """Socket event to mark messages in a room as read."""
    if not isinstance(data, dict):
        return

    room_id = data.get("room_id")
    user_id = session.get("user_id") or sid_to_user.get(request.sid)
    if not user_id or not room_id:
        return

    read_ids = mark_messages_as_read(int(room_id), user_id)
    if read_ids:
        emit(
            "messages_read",
            {
                "room_id": int(room_id),
                "user_id": user_id,
                "message_ids": read_ids,
            },
            to=f"room_{int(room_id)}"
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
    if not can_user_access_room(user_id, room_id):
        return

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
    """Add or remove an emoji reaction on a message and notify author."""
    if not isinstance(data, dict):
        return

    message_id = data.get("message_id")
    room_id = data.get("room_id")
    emoji = data.get("emoji")
    user_id = session.get("user_id") or sid_to_user.get(request.sid)

    if not all((message_id, room_id, emoji, user_id)):
        return

    if not isinstance(room_id, (int, str)) or not str(room_id).isdigit():
        return

    room_id = int(room_id)
    if not can_user_access_room(user_id, room_id):
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
                "room_id": room_id,
                "reactions": updated_reactions,
                "action": action,
                "user_id": user_id,
            },
            to=f"room_{room_id}",
        )

        # Notify message author if a new reaction was added by another user
        if action == "added":
            msg = get_message_by_id(message_id)
            if msg and msg["sender_id"] != user_id:
                actor = get_user_by_id(user_id)
                actor_name = actor.get("display_name") or actor.get("username")
                notif = create_notification(
                    user_id=msg["sender_id"],
                    actor_id=user_id,
                    notif_type="reaction",
                    title="Reaction on your message",
                    content=f"{actor_name} reacted {emoji} to: \"{msg['content'][:60]}\"",
                    room_id=room_id,
                    message_id=message_id
                )
                if notif:
                    send_user_notification(msg["sender_id"], notif)

    except Exception:
        app.logger.exception("Reaction update failed")
        emit("error", {"message": "Could not update reaction."})


# ==============================================================================
# Socket.IO Presence Status Updates
# ==============================================================================

@socketio.on("status_update")
def on_status_update(data):
    """Update a user's presence status (online/away/busy)."""
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
# Main Server Runner
# ==============================================================================

if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(
            encoding="utf-8",
            errors="replace",
        )

    print("=" * 65)
    print("  NexusChat Advanced Real-Time Server running...")
    print("  Web Interface   : http://localhost:5000")
    print("  Admin Dashboard : http://localhost:5000/admin")
    print("=" * 65)

    socketio.run(
        app,
        host="0.0.0.0",
        port=5000,
        debug=True,
        allow_unsafe_werkzeug=True,
    )
