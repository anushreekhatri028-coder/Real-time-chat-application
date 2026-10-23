"""
Database operations for the Real-Time Chat Application.
Manages SQLite connection, schema migrations, and queries for users, rooms, and messages.
"""

import os
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash

# Path to chat.db in the parent root directory of backend/ (i.e., real-time-chat-app/chat.db)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "chat.db")


def get_db_connection():
    """Create and return a SQLite database connection with row factory enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    """Initialize database tables and seed with initial default channels and demo users."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL,
            avatar_color TEXT DEFAULT '#6366f1',
            bio TEXT DEFAULT '',
            status TEXT DEFAULT 'offline',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 2. Rooms / Channels table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT DEFAULT '',
            icon TEXT DEFAULT '#',
            is_private INTEGER DEFAULT 0,
            dm_user1_id INTEGER,
            dm_user2_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (dm_user1_id) REFERENCES users(id),
            FOREIGN KEY (dm_user2_id) REFERENCES users(id)
        );
    """)

    # 3. Messages table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER NOT NULL,
            sender_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            message_type TEXT DEFAULT 'text',
            file_url TEXT DEFAULT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE,
            FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE
        );
    """)

    # 4. Reactions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            emoji TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(message_id, user_id, emoji),
            FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
    """)

    conn.commit()

    # Seed default rooms if empty
    cursor.execute("SELECT COUNT(*) FROM rooms WHERE is_private = 0")
    if cursor.fetchone()[0] == 0:
        default_rooms = [
            ("general", "Welcome lobby! Say hi and talk about anything.", "💬", 0),
            ("tech-talk", "Code snippets, system architecture, and tech news.", "💻", 0),
            ("random", "Casual chatter, funny memes, and lunch recommendations.", "☕", 0),
            ("announcements", "Release notes, project roadmap, and updates.", "📢", 0)
        ]
        cursor.executemany(
            "INSERT INTO rooms (name, description, icon, is_private) VALUES (?, ?, ?, ?)",
            default_rooms
        )
        conn.commit()

    # Seed demo users if empty
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        demo_password = generate_password_hash("password123")
        demo_users = [
            ("alex", "alex@demo.chat", demo_password, "Alex Rivers", "#6366f1", "Full-stack dev & WebSocket enthusiast 🚀"),
            ("sarah", "sarah@demo.chat", demo_password, "Sarah Chen", "#ec4899", "UI/UX Designer & Real-time app builder ✨"),
            ("nova_bot", "nova@demo.chat", demo_password, "Nova Bot", "#10b981", "Automated friendly assistant 🤖")
        ]
        cursor.executemany(
            "INSERT INTO users (username, email, password_hash, display_name, avatar_color, bio) VALUES (?, ?, ?, ?, ?, ?)",
            demo_users
        )
        conn.commit()

        # Seed welcome messages in general channel
        cursor.execute("SELECT id FROM rooms WHERE name = 'general'")
        general_room = cursor.fetchone()
        cursor.execute("SELECT id FROM users WHERE username = 'nova_bot'")
        bot_user = cursor.fetchone()
        cursor.execute("SELECT id FROM users WHERE username = 'alex'")
        alex_user = cursor.fetchone()

        if general_room and bot_user and alex_user:
            welcome_msgs = [
                (general_room["id"], bot_user["id"], "👋 Welcome to **NexusChat**! Real-time messaging powered by Flask & WebSockets. Try switching channels or typing `/help`!", "text"),
                (general_room["id"], alex_user["id"], "Hey everyone! Socket latency is looking silky smooth today. ⚡", "text")
            ]
            cursor.executemany(
                "INSERT INTO messages (room_id, sender_id, content, message_type) VALUES (?, ?, ?, ?)",
                welcome_msgs
            )
            conn.commit()

    conn.close()


# --- User Queries ---

def create_user(username, email, password_hash, display_name=None, avatar_color="#6366f1", bio=""):
    """Insert a new user record into the database."""
    if not display_name:
        display_name = username.capitalize()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO users (username, email, password_hash, display_name, avatar_color, bio)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (username.lower().strip(), email.lower().strip(), password_hash, display_name.strip(), avatar_color, bio.strip())
        )
        conn.commit()
        user_id = cursor.lastrowid
        return get_user_by_id(user_id)
    except sqlite3.IntegrityError as e:
        return None
    finally:
        conn.close()


def get_user_by_id(user_id):
    """Retrieve user dictionary by user ID (without password hash)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, username, email, display_name, avatar_color, bio, status, created_at, last_seen FROM users WHERE id = ?",
        (user_id,)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_username(username):
    """Retrieve full user row by username, including password hash for auth."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (username.strip(),))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_email(email):
    """Retrieve full user row by email, including password hash for auth."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE LOWER(email) = LOWER(?)", (email.strip(),))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_users():
    """Retrieve all users with basic profile data for the active directory."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, username, email, display_name, avatar_color, bio, status, last_seen FROM users ORDER BY display_name ASC"
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_user_status(user_id, status):
    """Update user online/offline/away status and touch last_seen timestamp."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET status = ?, last_seen = CURRENT_TIMESTAMP WHERE id = ?",
        (status, user_id)
    )
    conn.commit()
    conn.close()


# --- Room / Channel Queries ---

def get_all_rooms():
    """Retrieve all public channels and room info."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM rooms WHERE is_private = 0 ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_room_by_id(room_id):
    """Retrieve a single room by its ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM rooms WHERE id = ?", (room_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_room_by_name(name):
    """Retrieve room by channel name."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM rooms WHERE LOWER(name) = LOWER(?) AND is_private = 0", (name,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def create_room(name, description="", icon="#", is_private=0):
    """Create a new channel room."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO rooms (name, description, icon, is_private) VALUES (?, ?, ?, ?)",
            (name.lower().strip().replace(" ", "-"), description.strip(), icon.strip() or "#", is_private)
        )
        conn.commit()
        room_id = cursor.lastrowid
        return get_room_by_id(room_id)
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def get_or_create_dm_room(user1_id, user2_id):
    """Get an existing 1-on-1 direct message room or create a new one."""
    u1, u2 = sorted([int(user1_id), int(user2_id)])
    room_name = f"dm_{u1}_{u2}"
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM rooms WHERE is_private = 1 AND dm_user1_id = ? AND dm_user2_id = ?",
        (u1, u2)
    )
    row = cursor.fetchone()
    if row:
        conn.close()
        return dict(row)

    # Create DM room
    cursor.execute(
        """INSERT INTO rooms (name, description, icon, is_private, dm_user1_id, dm_user2_id)
           VALUES (?, ?, '🔒', 1, ?, ?)""",
        (room_name, "Direct Message", u1, u2)
    )
    conn.commit()
    room_id = cursor.lastrowid
    cursor.execute("SELECT * FROM rooms WHERE id = ?", (room_id,))
    new_room = dict(cursor.fetchone())
    conn.close()
    return new_room


# --- Message Queries ---

def save_message(room_id, sender_id, content, message_type="text", file_url=None):
    """Insert a message record and return the populated message dictionary."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO messages (room_id, sender_id, content, message_type, file_url)
           VALUES (?, ?, ?, ?, ?)""",
        (room_id, sender_id, content, message_type, file_url)
    )
    conn.commit()
    msg_id = cursor.lastrowid
    conn.close()
    return get_message_by_id(msg_id)


def get_message_by_id(message_id):
    """Retrieve message details joined with sender information and reactions."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            m.id, m.room_id, m.sender_id, m.content, m.message_type, m.file_url, m.timestamp,
            u.username, u.display_name, u.avatar_color
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE m.id = ?
    """, (message_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
    msg = dict(row)
    msg["reactions"] = get_message_reactions(message_id, conn)
    conn.close()
    return msg


def get_room_messages(room_id, limit=60):
    """Retrieve recent messages for a room with sender details and reactions."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            m.id, m.room_id, m.sender_id, m.content, m.message_type, m.file_url, m.timestamp,
            u.username, u.display_name, u.avatar_color
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE m.room_id = ?
        ORDER BY m.timestamp ASC, m.id ASC
        LIMIT ?
    """, (room_id, limit))
    rows = cursor.fetchall()
    messages = []
    for r in rows:
        msg = dict(r)
        msg["reactions"] = get_message_reactions(msg["id"], conn)
        messages.append(msg)
    conn.close()
    return messages


# --- Reaction Queries ---

def get_message_reactions(message_id, conn=None):
    """Fetch grouped emoji reactions with user details for a given message."""
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True

    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.emoji, r.user_id, u.username, u.display_name
        FROM reactions r
        JOIN users u ON r.user_id = u.id
        WHERE r.message_id = ?
        ORDER BY r.created_at ASC
    """, (message_id,))
    rows = cursor.fetchall()
    if should_close:
        conn.close()

    # Group by emoji
    grouped = {}
    for row in rows:
        emoji = row["emoji"]
        if emoji not in grouped:
            grouped[emoji] = {
                "emoji": emoji,
                "count": 0,
                "users": []
            }
        grouped[emoji]["count"] += 1
        grouped[emoji]["users"].append({
            "id": row["user_id"],
            "username": row["username"],
            "display_name": row["display_name"]
        })
    return list(grouped.values())


def toggle_reaction(message_id, user_id, emoji):
    """Toggle reaction: if user already reacted with this emoji, remove it; else add it."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM reactions WHERE message_id = ? AND user_id = ? AND emoji = ?",
        (message_id, user_id, emoji)
    )
    existing = cursor.fetchone()
    if existing:
        cursor.execute(
            "DELETE FROM reactions WHERE message_id = ? AND user_id = ? AND emoji = ?",
            (message_id, user_id, emoji)
        )
        action = "removed"
    else:
        cursor.execute(
            "INSERT INTO reactions (message_id, user_id, emoji) VALUES (?, ?, ?)",
            (message_id, user_id, emoji)
        )
        action = "added"
    conn.commit()
    conn.close()
    return action, get_message_reactions(message_id)
