"""
Database operations for the Real-Time Chat Application (NexusChat).
Manages SQLite connection, schema migrations, and queries for users, rooms,
messages, groups, read receipts, notifications, moderation, and reports.
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


def _column_exists(cursor, table_name, column_name):
    """Check if a column exists in a given table."""
    cursor.execute(f"PRAGMA table_info({table_name});")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns


def init_db():
    """
    Initialize database tables and run safe migrations.
    Preserves all existing data, adds required tables and columns,
    and sets up performance indexes.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Base Users table
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

    # Safe migration: Add role and is_suspended to users if missing
    if not _column_exists(cursor, "users", "role"):
        cursor.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user';")
    if not _column_exists(cursor, "users", "is_suspended"):
        cursor.execute("ALTER TABLE users ADD COLUMN is_suspended INTEGER DEFAULT 0;")

    # 2. Base Rooms table
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

    # Safe migration: Add room_type, creator_id, avatar_url to rooms if missing
    if not _column_exists(cursor, "rooms", "room_type"):
        cursor.execute("ALTER TABLE rooms ADD COLUMN room_type TEXT DEFAULT 'channel';")
        # Update existing DMs
        cursor.execute("UPDATE rooms SET room_type = 'dm' WHERE is_private = 1;")
    if not _column_exists(cursor, "rooms", "creator_id"):
        cursor.execute("ALTER TABLE rooms ADD COLUMN creator_id INTEGER REFERENCES users(id);")
    if not _column_exists(cursor, "rooms", "avatar_url"):
        cursor.execute("ALTER TABLE rooms ADD COLUMN avatar_url TEXT DEFAULT NULL;")

    # 3. Base Messages table
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

    # Safe migration: Add editing, deleting, reply, and forward columns to messages
    if not _column_exists(cursor, "messages", "is_edited"):
        cursor.execute("ALTER TABLE messages ADD COLUMN is_edited INTEGER DEFAULT 0;")
    if not _column_exists(cursor, "messages", "edited_at"):
        cursor.execute("ALTER TABLE messages ADD COLUMN edited_at TIMESTAMP DEFAULT NULL;")
    if not _column_exists(cursor, "messages", "is_deleted"):
        cursor.execute("ALTER TABLE messages ADD COLUMN is_deleted INTEGER DEFAULT 0;")
    if not _column_exists(cursor, "messages", "reply_to_id"):
        cursor.execute("ALTER TABLE messages ADD COLUMN reply_to_id INTEGER REFERENCES messages(id);")
    if not _column_exists(cursor, "messages", "forwarded_from_id"):
        cursor.execute("ALTER TABLE messages ADD COLUMN forwarded_from_id INTEGER REFERENCES messages(id);")
    if not _column_exists(cursor, "messages", "forwarded_from_sender"):
        cursor.execute("ALTER TABLE messages ADD COLUMN forwarded_from_sender TEXT DEFAULT NULL;")

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

    # 5. Group Members table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS group_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            role TEXT DEFAULT 'member', -- 'admin' or 'member'
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(room_id, user_id),
            FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
    """)

    # 6. Message Deliveries table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS message_deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            delivered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(message_id, user_id),
            FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
    """)

    # 7. Message Reads table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS message_reads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            read_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(message_id, user_id),
            FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
    """)

    # 8. Notifications table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            actor_id INTEGER,
            type TEXT NOT NULL, -- 'dm', 'group_message', 'mention', 'reply', 'group_invite', 'reaction', 'admin'
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            room_id INTEGER,
            message_id INTEGER,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (actor_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE,
            FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
        );
    """)

    # 9. Reports table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL,
            reporter_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            details TEXT DEFAULT '',
            status TEXT DEFAULT 'pending', -- 'pending', 'resolved', 'dismissed'
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP DEFAULT NULL,
            resolved_by INTEGER,
            UNIQUE(message_id, reporter_id),
            FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
            FOREIGN KEY (reporter_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (resolved_by) REFERENCES users(id) ON DELETE SET NULL
        );
    """)

    # 10. Moderation Logs table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS moderation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL,
            action TEXT NOT NULL, -- 'dismiss_report', 'delete_message', 'suspend_user', 'reactivate_user', 'warn_user'
            target_user_id INTEGER,
            message_id INTEGER,
            report_id INTEGER,
            details TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (admin_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (target_user_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE SET NULL,
            FOREIGN KEY (report_id) REFERENCES reports(id) ON DELETE SET NULL
        );
    """)

    # 11. Performance Indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_room_timestamp ON messages(room_id, timestamp);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_group_members_user ON group_members(user_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_group_members_room ON group_members(room_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_message_reads_user_msg ON message_reads(user_id, message_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_message_reads_msg ON message_reads(message_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_message_deliv_msg ON message_deliveries(message_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON notifications(user_id, is_read);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status);")

    conn.commit()

    # Seed default rooms if empty
    cursor.execute("SELECT COUNT(*) FROM rooms WHERE is_private = 0")
    if cursor.fetchone()[0] == 0:
        default_rooms = [
            ("general", "Welcome lobby! Say hi and talk about anything.", "💬", 0, "channel"),
            ("tech-talk", "Code snippets, system architecture, and tech news.", "💻", 0, "channel"),
            ("random", "Casual chatter, funny memes, and lunch recommendations.", "☕", 0, "channel"),
            ("announcements", "Release notes, project roadmap, and updates.", "📢", 0, "channel")
        ]
        cursor.executemany(
            "INSERT INTO rooms (name, description, icon, is_private, room_type) VALUES (?, ?, ?, ?, ?)",
            default_rooms
        )
        conn.commit()

    # Seed demo users if empty
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        demo_password = generate_password_hash("password123")
        demo_users = [
            ("alex", "alex@demo.chat", demo_password, "Alex Rivers", "#6366f1", "Full-stack dev & WebSocket enthusiast 🚀", "admin"),
            ("sarah", "sarah@demo.chat", demo_password, "Sarah Chen", "#ec4899", "UI/UX Designer & Real-time app builder ✨", "user"),
            ("nova_bot", "nova@demo.chat", demo_password, "Nova Bot", "#10b981", "Automated friendly assistant 🤖", "user")
        ]
        cursor.executemany(
            "INSERT INTO users (username, email, password_hash, display_name, avatar_color, bio, role) VALUES (?, ?, ?, ?, ?, ?, ?)",
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

    # Ensure demo user alex has admin role for administrative dashboard access
    cursor.execute("UPDATE users SET role = 'admin' WHERE username = 'alex' AND (role IS NULL OR role = 'user')")
    conn.commit()

    conn.close()


# ==============================================================================
# User Queries
# ==============================================================================

def create_user(username, email, password_hash, display_name=None, avatar_color="#6366f1", bio="", role="user"):
    """Insert a new user record into the database."""
    if not display_name:
        display_name = username.capitalize()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO users (username, email, password_hash, display_name, avatar_color, bio, role)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (username.lower().strip(), email.lower().strip(), password_hash, display_name.strip(), avatar_color, bio.strip(), role)
        )
        conn.commit()
        user_id = cursor.lastrowid
        return get_user_by_id(user_id)
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def get_user_by_id(user_id):
    """Retrieve user dictionary by user ID (without password hash)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, username, email, display_name, avatar_color, bio, status, role, is_suspended, created_at, last_seen FROM users WHERE id = ?",
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
        "SELECT id, username, email, display_name, avatar_color, bio, status, role, is_suspended, last_seen FROM users ORDER BY display_name ASC"
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


# ==============================================================================
# Room / Channel Queries
# ==============================================================================

def get_all_rooms():
    """Retrieve all public channels."""
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


def create_room(name, description="", icon="#", is_private=0, room_type="channel", creator_id=None):
    """Create a new channel room."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO rooms (name, description, icon, is_private, room_type, creator_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name.lower().strip().replace(" ", "-"), description.strip(), icon.strip() or "#", is_private, room_type, creator_id)
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
        "SELECT * FROM rooms WHERE is_private = 1 AND room_type = 'dm' AND dm_user1_id = ? AND dm_user2_id = ?",
        (u1, u2)
    )
    row = cursor.fetchone()
    if row:
        conn.close()
        return dict(row)

    # Create DM room
    cursor.execute(
        """INSERT INTO rooms (name, description, icon, is_private, room_type, dm_user1_id, dm_user2_id)
           VALUES (?, ?, '🔒', 1, 'dm', ?, ?)""",
        (room_name, "Direct Message", u1, u2)
    )
    conn.commit()
    room_id = cursor.lastrowid
    cursor.execute("SELECT * FROM rooms WHERE id = ?", (room_id,))
    new_room = dict(cursor.fetchone())
    conn.close()
    return new_room


# ==============================================================================
# Room Access Control
# ==============================================================================

def can_user_access_room(user_id, room_id):
    """
    Check if a user has authorized access to a room:
    - Public channels (is_private=0): accessible to all authenticated users.
    - Direct messages (room_type='dm'): only accessible to the two participants.
    - Group conversations (room_type='group'): only accessible to group members.
    """
    room = get_room_by_id(room_id)
    if not room:
        return False

    # Public room
    if not room.get("is_private"):
        return True

    user_id = int(user_id)
    room_type = room.get("room_type", "dm")

    if room_type == "dm":
        return user_id in (room.get("dm_user1_id"), room.get("dm_user2_id"))

    if room_type == "group":
        return is_user_in_group(room_id, user_id)

    return False


# ==============================================================================
# Group Chat Operations
# ==============================================================================

def create_group_room(name, description, creator_id, member_ids, avatar_color="#8b5cf6"):
    """
    Create a new group conversation with creator as admin and add initial members.
    Handles unique room name collision gracefully.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        base_name = name.strip()
        room_name = base_name
        counter = 1
        while True:
            cursor.execute("SELECT 1 FROM rooms WHERE LOWER(name) = LOWER(?)", (room_name,))
            if not cursor.fetchone():
                break
            room_name = f"{base_name}-{counter}"
            counter += 1

        # Create group room record
        cursor.execute(
            """INSERT INTO rooms (name, description, icon, is_private, room_type, creator_id)
               VALUES (?, ?, ?, 1, 'group', ?)""",
            (room_name, description.strip(), avatar_color, creator_id)
        )
        room_id = cursor.lastrowid

        # Add creator as admin
        cursor.execute(
            """INSERT INTO group_members (room_id, user_id, role)
               VALUES (?, ?, 'admin')""",
            (room_id, creator_id)
        )

        # Add selected members
        for mid in set(member_ids):
            if int(mid) != int(creator_id):
                cursor.execute(
                    """INSERT OR IGNORE INTO group_members (room_id, user_id, role)
                       VALUES (?, ?, 'member')""",
                    (room_id, int(mid))
                )

        conn.commit()
        cursor.execute("SELECT * FROM rooms WHERE id = ?", (room_id,))
        room = dict(cursor.fetchone())
        return room
    except Exception:
        conn.rollback()
        return None
    finally:
        conn.close()


def get_user_groups(user_id):
    """Retrieve all group conversations a user is currently a member of."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.*, gm.role as member_role,
               (SELECT COUNT(*) FROM group_members WHERE room_id = r.id) as member_count
        FROM rooms r
        JOIN group_members gm ON r.id = gm.room_id
        WHERE gm.user_id = ? AND r.room_type = 'group'
        ORDER BY r.id DESC
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_group_members(room_id):
    """Retrieve all members of a group with their roles and presence status."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.id, u.username, u.display_name, u.avatar_color, u.bio, u.status, u.last_seen, gm.role, gm.joined_at
        FROM group_members gm
        JOIN users u ON gm.user_id = u.id
        WHERE gm.room_id = ?
        ORDER BY CASE gm.role WHEN 'admin' THEN 1 ELSE 2 END, u.display_name ASC
    """, (room_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def is_user_in_group(room_id, user_id):
    """Check whether a user is an active member of a group."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT 1 FROM group_members WHERE room_id = ? AND user_id = ?",
        (room_id, user_id)
    )
    row = cursor.fetchone()
    conn.close()
    return bool(row)


def is_group_admin(room_id, user_id):
    """Check whether a user is an admin or creator of a group."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT role FROM group_members WHERE room_id = ? AND user_id = ?",
        (room_id, user_id)
    )
    row = cursor.fetchone()
    if row and row["role"] == "admin":
        conn.close()
        return True

    cursor.execute("SELECT creator_id FROM rooms WHERE id = ?", (room_id,))
    room_row = cursor.fetchone()
    conn.close()
    return bool(room_row and room_row["creator_id"] == user_id)


def add_group_member(room_id, user_id, role="member"):
    """Add a user to a group room."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT OR IGNORE INTO group_members (room_id, user_id, role) VALUES (?, ?, ?)",
            (room_id, user_id, role)
        )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def remove_group_member(room_id, user_id):
    """Remove a user from a group room."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM group_members WHERE room_id = ? AND user_id = ?",
            (room_id, user_id)
        )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def update_group_info(room_id, name, description):
    """Update name and description of a group."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE rooms SET name = ?, description = ? WHERE id = ? AND room_type = 'group'",
            (name.strip(), description.strip(), room_id)
        )
        conn.commit()
        return get_room_by_id(room_id)
    except Exception:
        return None
    finally:
        conn.close()


# ==============================================================================
# Message Queries (with Reply, Forward, Edit, Delete, Read Status)
# ==============================================================================

def save_message(room_id, sender_id, content, message_type="text", file_url=None,
                 reply_to_id=None, forwarded_from_id=None, forwarded_from_sender=None):
    """Insert a message record and return the fully populated message dictionary."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO messages (room_id, sender_id, content, message_type, file_url,
                                 reply_to_id, forwarded_from_id, forwarded_from_sender)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (room_id, sender_id, content, message_type, file_url,
         reply_to_id, forwarded_from_id, forwarded_from_sender)
    )
    conn.commit()
    msg_id = cursor.lastrowid
    conn.close()
    return get_message_by_id(msg_id)


def edit_message(message_id, user_id, new_content):
    """Edit message content if user is the original author."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT sender_id, is_deleted FROM messages WHERE id = ?", (message_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False, "Message not found."
    if row["sender_id"] != user_id:
        conn.close()
        return False, "You can edit only your own messages."
    if row["is_deleted"]:
        conn.close()
        return False, "Deleted messages cannot be edited."

    cursor.execute(
        "UPDATE messages SET content = ?, is_edited = 1, edited_at = CURRENT_TIMESTAMP WHERE id = ?",
        (new_content, message_id)
    )
    conn.commit()
    conn.close()
    return True, get_message_by_id(message_id)


def delete_message(message_id, user_id, is_admin=False):
    """Soft-delete message content if user is author or administrator."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT sender_id, room_id FROM messages WHERE id = ?", (message_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False, "Message not found."
    if not is_admin and row["sender_id"] != user_id:
        conn.close()
        return False, "You can delete only your own messages."

    # Soft delete: wipe content and file_url, mark is_deleted = 1
    cursor.execute(
        "UPDATE messages SET is_deleted = 1, content = 'This message was deleted.', file_url = NULL WHERE id = ?",
        (message_id,)
    )
    conn.commit()
    conn.close()
    return True, get_message_by_id(message_id)


def get_message_by_id(message_id, conn=None):
    """Retrieve message details joined with sender, reply preview, reactions, and read receipt."""
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True

    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            m.id, m.room_id, m.sender_id, m.content, m.message_type, m.file_url, m.timestamp,
            m.is_edited, m.edited_at, m.is_deleted, m.reply_to_id, m.forwarded_from_id, m.forwarded_from_sender,
            u.username, u.display_name, u.avatar_color,
            p.content as reply_content,
            pu.display_name as reply_sender_display_name,
            pu.username as reply_sender_username
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        LEFT JOIN messages p ON m.reply_to_id = p.id
        LEFT JOIN users pu ON p.sender_id = pu.id
        WHERE m.id = ?
    """, (message_id,))
    row = cursor.fetchone()
    if not row:
        if should_close:
            conn.close()
        return None

    msg = dict(row)
    msg["reactions"] = get_message_reactions(message_id, conn)

    # Attach reply preview if message is a reply
    if msg.get("reply_to_id") and msg.get("reply_content") is not None:
        msg["reply_to"] = {
            "id": msg["reply_to_id"],
            "sender_name": msg["reply_sender_display_name"] or msg["reply_sender_username"] or "Unknown",
            "content": msg["reply_content"][:100]
        }
    else:
        msg["reply_to"] = None

    # Calculate read receipt status
    msg["read_status"] = _get_message_read_status(cursor, msg["id"], msg["sender_id"], msg["room_id"])

    if should_close:
        conn.close()
    return msg


def get_room_messages(room_id, limit=60, current_user_id=None):
    """Retrieve recent messages for a room with sender details, replies, reactions, and read receipts."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            m.id, m.room_id, m.sender_id, m.content, m.message_type, m.file_url, m.timestamp,
            m.is_edited, m.edited_at, m.is_deleted, m.reply_to_id, m.forwarded_from_id, m.forwarded_from_sender,
            u.username, u.display_name, u.avatar_color,
            p.content as reply_content,
            pu.display_name as reply_sender_display_name,
            pu.username as reply_sender_username
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        LEFT JOIN messages p ON m.reply_to_id = p.id
        LEFT JOIN users pu ON p.sender_id = pu.id
        WHERE m.room_id = ?
        ORDER BY m.timestamp ASC, m.id ASC
        LIMIT ?
    """, (room_id, limit))
    rows = cursor.fetchall()

    messages = []
    for r in rows:
        msg = dict(r)
        msg["reactions"] = get_message_reactions(msg["id"], conn)

        if msg.get("reply_to_id") and msg.get("reply_content") is not None:
            msg["reply_to"] = {
                "id": msg["reply_to_id"],
                "sender_name": msg["reply_sender_display_name"] or msg["reply_sender_username"] or "Unknown",
                "content": msg["reply_content"][:100]
            }
        else:
            msg["reply_to"] = None

        msg["read_status"] = _get_message_read_status(cursor, msg["id"], msg["sender_id"], msg["room_id"])
        messages.append(msg)

    conn.close()
    return messages


def forward_message(original_message_id, target_room_id, sender_id):
    """Forward an existing message to another room."""
    orig = get_message_by_id(original_message_id)
    if not orig:
        return None

    # Get original sender display name
    orig_sender = orig.get("display_name") or orig.get("username") or "User"
    return save_message(
        room_id=target_room_id,
        sender_id=sender_id,
        content=orig["content"],
        message_type=orig["message_type"],
        file_url=orig["file_url"],
        forwarded_from_id=orig["id"],
        forwarded_from_sender=orig_sender
    )


# ==============================================================================
# Read Receipts and Deliveries
# ==============================================================================

def _get_message_read_status(cursor, message_id, sender_id, room_id):
    """
    Compute read receipt status:
    - 'read' (blue double check) if read by other member(s)
    - 'delivered' (double check) if delivered to other member(s)
    - 'sent' (single check) if newly sent
    """
    # Check if any non-sender has read the message
    cursor.execute("""
        SELECT COUNT(*) FROM message_reads
        WHERE message_id = ? AND user_id != ?
    """, (message_id, sender_id))
    read_count = cursor.fetchone()[0]
    if read_count > 0:
        return "read"

    # Check if delivered to any non-sender
    cursor.execute("""
        SELECT COUNT(*) FROM message_deliveries
        WHERE message_id = ? AND user_id != ?
    """, (message_id, sender_id))
    delivery_count = cursor.fetchone()[0]
    if delivery_count > 0:
        return "delivered"

    return "sent"


def record_message_delivery(message_id, user_id):
    """Record that a message was delivered to a user's client."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT OR IGNORE INTO message_deliveries (message_id, user_id) VALUES (?, ?)",
            (message_id, user_id)
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def record_room_deliveries(room_id, user_id):
    """Mark all undelivered messages in a room as delivered to user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR IGNORE INTO message_deliveries (message_id, user_id)
            SELECT id, ? FROM messages
            WHERE room_id = ? AND sender_id != ?
        """, (user_id, room_id, user_id))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def mark_messages_as_read(room_id, user_id):
    """
    Mark all unread messages in a room as read by user.
    Returns list of message IDs that were marked as read.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Find messages not yet marked read by this user
        cursor.execute("""
            SELECT m.id FROM messages m
            LEFT JOIN message_reads mr ON m.id = mr.message_id AND mr.user_id = ?
            WHERE m.room_id = ? AND m.sender_id != ? AND mr.id IS NULL
        """, (user_id, room_id, user_id))
        unread_ids = [row["id"] for row in cursor.fetchall()]

        if unread_ids:
            # Insert read records
            cursor.executemany(
                "INSERT OR IGNORE INTO message_reads (message_id, user_id) VALUES (?, ?)",
                [(mid, user_id) for mid in unread_ids]
            )
            # Also ensure deliveries are recorded
            cursor.executemany(
                "INSERT OR IGNORE INTO message_deliveries (message_id, user_id) VALUES (?, ?)",
                [(mid, user_id) for mid in unread_ids]
            )
            conn.commit()

        return unread_ids
    except Exception:
        return []
    finally:
        conn.close()


def get_unread_counts(user_id):
    """
    Calculate unread message count for every room accessible to the user.
    Returns a dict {room_id: unread_count}.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.room_id, COUNT(m.id) as unread_count
        FROM messages m
        LEFT JOIN message_reads mr ON m.id = mr.message_id AND mr.user_id = ?
        WHERE m.sender_id != ? AND mr.id IS NULL
        GROUP BY m.room_id
    """, (user_id, user_id))
    rows = cursor.fetchall()
    conn.close()
    return {row["room_id"]: row["unread_count"] for row in rows}


# ==============================================================================
# Reactions
# ==============================================================================

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


# ==============================================================================
# Notification Queries
# ==============================================================================

def create_notification(user_id, actor_id, notif_type, title, content, room_id=None, message_id=None):
    """Insert a notification for a user (skips if actor is user)."""
    if int(user_id) == int(actor_id or 0):
        return None

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO notifications (user_id, actor_id, type, title, content, room_id, message_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, actor_id, notif_type, title, content, room_id, message_id))
        conn.commit()
        notif_id = cursor.lastrowid
        cursor.execute("""
            SELECT n.*, u.username as actor_username, u.display_name as actor_display_name, u.avatar_color as actor_avatar_color
            FROM notifications n
            LEFT JOIN users u ON n.actor_id = u.id
            WHERE n.id = ?
        """, (notif_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_notifications(user_id, limit=50):
    """Retrieve notifications for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT n.*, u.username as actor_username, u.display_name as actor_display_name, u.avatar_color as actor_avatar_color
        FROM notifications n
        LEFT JOIN users u ON n.actor_id = u.id
        WHERE n.user_id = ?
        ORDER BY n.created_at DESC
        LIMIT ?
    """, (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_unread_notification_count(user_id):
    """Count unread notifications for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0", (user_id,))
    count = cursor.fetchone()[0]
    conn.close()
    return count


def mark_notification_as_read(notif_id, user_id):
    """Mark a single notification as read."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?",
        (notif_id, user_id)
    )
    conn.commit()
    conn.close()
    return True


def mark_all_notifications_as_read(user_id):
    """Mark all notifications for a user as read."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return True


# ==============================================================================
# Message Reporting & Moderation
# ==============================================================================

def create_report(message_id, reporter_id, reason, details=""):
    """
    File a report against a message. Prevents duplicate reports by same user.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """INSERT INTO reports (message_id, reporter_id, reason, details)
               VALUES (?, ?, ?, ?)""",
            (message_id, reporter_id, reason.strip(), details.strip())
        )
        conn.commit()
        report_id = cursor.lastrowid
        cursor.execute("SELECT * FROM reports WHERE id = ?", (report_id,))
        return True, dict(cursor.fetchone())
    except sqlite3.IntegrityError:
        return False, "You have already reported this message."
    finally:
        conn.close()


def get_reports(status=None):
    """Retrieve reported messages for moderation review."""
    conn = get_db_connection()
    cursor = conn.cursor()
    query = """
        SELECT 
            r.id, r.message_id, r.reporter_id, r.reason, r.details, r.status, r.created_at, r.resolved_at,
            m.content as message_content, m.sender_id as reported_user_id, m.room_id, m.is_deleted,
            reporter.username as reporter_username, reporter.display_name as reporter_display_name,
            author.username as author_username, author.display_name as author_display_name, author.avatar_color as author_avatar_color,
            author.is_suspended as author_is_suspended,
            rm.name as room_name
        FROM reports r
        JOIN messages m ON r.message_id = m.id
        JOIN users reporter ON r.reporter_id = reporter.id
        JOIN users author ON m.sender_id = author.id
        LEFT JOIN rooms rm ON m.room_id = rm.id
    """
    params = ()
    if status:
        query += " WHERE r.status = ?"
        params = (status,)
    query += " ORDER BY r.created_at DESC"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_report_status(report_id, status, admin_id):
    """Update report status ('resolved' or 'dismissed')."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE reports
        SET status = ?, resolved_at = CURRENT_TIMESTAMP, resolved_by = ?
        WHERE id = ?
    """, (status, admin_id, report_id))
    conn.commit()
    conn.close()
    return True


def log_moderation_action(admin_id, action, target_user_id=None, message_id=None, report_id=None, details=""):
    """Record an administrative or moderation action in audit log."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO moderation_logs (admin_id, action, target_user_id, message_id, report_id, details)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (admin_id, action, target_user_id, message_id, report_id, details))
    conn.commit()
    conn.close()


def get_moderation_logs(limit=100):
    """Retrieve recent moderation audit logs."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ml.*,
               admin.username as admin_username, admin.display_name as admin_display_name,
               target.username as target_username, target.display_name as target_display_name
        FROM moderation_logs ml
        JOIN users admin ON ml.admin_id = admin.id
        LEFT JOIN users target ON ml.target_user_id = target.id
        ORDER BY ml.created_at DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ==============================================================================
# Admin Dashboard Analytics and Management
# ==============================================================================

def get_admin_stats():
    """Retrieve overview statistics and analytics for the admin dashboard."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Total registered users
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    # 2. Total active users (online or last seen today)
    cursor.execute("SELECT COUNT(*) FROM users WHERE status != 'offline'")
    active_users = cursor.fetchone()[0]

    # 3. Total messages
    cursor.execute("SELECT COUNT(*) FROM messages WHERE is_deleted = 0")
    total_messages = cursor.fetchone()[0]

    # 4. Total public channels
    cursor.execute("SELECT COUNT(*) FROM rooms WHERE is_private = 0")
    total_channels = cursor.fetchone()[0]

    # 5. Total group conversations
    cursor.execute("SELECT COUNT(*) FROM rooms WHERE room_type = 'group'")
    total_groups = cursor.fetchone()[0]

    # 6. Total pending reports
    cursor.execute("SELECT COUNT(*) FROM reports WHERE status = 'pending'")
    pending_reports = cursor.fetchone()[0]

    # 7. Most active users (top 5 by message count)
    cursor.execute("""
        SELECT u.id, u.username, u.display_name, u.avatar_color, COUNT(m.id) as message_count
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE m.is_deleted = 0
        GROUP BY u.id
        ORDER BY message_count DESC
        LIMIT 5
    """)
    most_active_users = [dict(r) for r in cursor.fetchall()]

    # 8. Most active channels (top 5 by message count)
    cursor.execute("""
        SELECT r.id, r.name, r.icon, r.room_type, COUNT(m.id) as message_count
        FROM messages m
        JOIN rooms r ON m.room_id = r.id
        WHERE m.is_deleted = 0
        GROUP BY r.id
        ORDER BY message_count DESC
        LIMIT 5
    """)
    most_active_channels = [dict(r) for r in cursor.fetchall()]

    # 9. Daily message statistics for the past 7 days
    cursor.execute("""
        SELECT date(timestamp) as msg_date, COUNT(*) as count
        FROM messages
        WHERE timestamp >= datetime('now', '-7 days')
        GROUP BY date(timestamp)
        ORDER BY msg_date ASC
    """)
    daily_stats = [dict(r) for r in cursor.fetchall()]

    conn.close()

    return {
        "total_users": total_users,
        "active_users": active_users,
        "total_messages": total_messages,
        "total_channels": total_channels,
        "total_groups": total_groups,
        "pending_reports": pending_reports,
        "most_active_users": most_active_users,
        "most_active_channels": most_active_channels,
        "daily_stats": daily_stats
    }


def search_users(query=""):
    """Search or list registered users with their status, role, and message count."""
    conn = get_db_connection()
    cursor = conn.cursor()
    query_str = f"%{query.strip().lower()}%"
    cursor.execute("""
        SELECT u.id, u.username, u.email, u.display_name, u.avatar_color, u.status, u.role, u.is_suspended, u.created_at, u.last_seen,
               (SELECT COUNT(*) FROM messages WHERE sender_id = u.id) as total_messages
        FROM users u
        WHERE LOWER(u.username) LIKE ? OR LOWER(u.display_name) LIKE ? OR LOWER(u.email) LIKE ?
        ORDER BY u.id ASC
    """, (query_str, query_str, query_str))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_user_suspension(user_id, is_suspended):
    """Suspend or reactivate a user account."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET is_suspended = ? WHERE id = ?",
        (1 if is_suspended else 0, user_id)
    )
    conn.commit()
    conn.close()
    return True


def set_user_role(user_id, role):
    """Update user role ('user' or 'admin')."""
    if role not in ("user", "admin"):
        return False
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET role = ? WHERE id = ?",
        (role, user_id)
    )
    conn.commit()
    conn.close()
    return True
