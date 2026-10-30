# ⚡ NexusChat — Advanced Real-Time Chat Application

An enterprise-grade, high-performance **Real-Time Messaging Platform** built using **Python, Flask, Flask-SocketIO (WebSockets), and SQLite**. Supports rich Web GUI interactions, mobile responsive cyber/dark glassmorphism design, interactive Terminal Client, Group Chats, Message Management (Edit, Delete, Reply, Forward), Read Receipts (ticks & unread badges), Notification Center, Profanity Filtering & Content Moderation, and a comprehensive Admin Dashboard with Chart.js analytics.

---

## 📁 Enhanced Project Structure

```text
NexusChat/
├── backend/
│   ├── app.py              # Flask server, REST APIs, Socket.IO handlers, authorization & routing
│   ├── auth.py             # Auth module, password hashing, session RBAC & access control decorators
│   ├── database.py         # SQLite connection, schema migrations, CRUD & relational queries
│   ├── moderation.py       # Robust regex-based profanity filtering & structure preservation
│   └── requirements.txt    # Python dependencies
│
├── frontend/
│   ├── index.html          # Authentication portal (Sign In / Register & 1-click Demo accounts)
│   ├── chat.html           # Full-featured chat workspace (Channels, Groups, DMs, Modals)
│   ├── admin.html          # Administrative Dashboard & Analytics (Chart.js, Moderation, User Control)
│   ├── style.css           # Modern Cyber/Dark glassmorphic styling, responsive layout
│   └── script.js           # Real-time WebSocket client logic, audio synthesizer & state machine
│
├── tests/
│   └── test_nexuschat.py   # Comprehensive automated test suite (15 end-to-end integration tests)
│
├── uploads/                # User uploaded attachments and media
├── chat.db                 # SQLite database (auto-migrating, schema-preserving)
├── console_client.py       # Interactive terminal client with ANSI colors & WebSocket sync
├── run.py                  # Server launcher
└── README.md               # Complete platform documentation
```

---

## 🚀 Quick Start & Installation

### 1. Prerequisites
- Python 3.10+ installed
- Virtual environment recommended

### 2. Install Dependencies
From the repository root or `real-time-chat-app/`:
```bash
pip install -r backend/requirements.txt
```

### 3. Start the NexusChat Server
From the root directory:
```bash
python run.py
```
*(Or: `cd real-time-chat-app && python run.py`)*

The server starts at **`http://localhost:5000`**.

---

## 🌐 Accessing the Application

1. Open your browser and navigate to:
   ```
   http://localhost:5000
   ```
2. **Demo Accounts**:
   - **Alex Rivers (Administrator)**:
     - Username: `alex` | Password: `password123`
     - Role: `admin` (Has access to `/admin` dashboard and full moderation privileges)
   - **Sarah Chen (Standard User)**:
     - Username: `sarah` | Password: `password123`
     - Role: `user` (Standard member)
3. **Dual-User Testing**:
   - Tab 1 (Normal Window): Log in as **Alex**
   - Tab 2 (Incognito / Private Window): Log in as **Sarah**
   - Test real-time group chat, direct messages, message editing, soft-deletes, replies, forward modals, and live read receipts!

---

## 💻 Running the Terminal / Console Client

Chat simultaneously from your terminal with browser users over WebSockets:
```bash
python console_client.py
```

Commands in terminal:
- `/rooms` — List all channels
- `/join <channel>` — Switch channels (e.g. `/join general`)
- `/users` — List registered users and presence
- `/help` — Nova Bot assistant menu
- `/quit` — Exit client

---

## 🧪 Automated Testing Suite

Run the full end-to-end integration and security test suite:
```bash
python ../tests/test_nexuschat.py
```
*(or `python tests/test_nexuschat.py` from root)*

---

## 🌟 Implemented Features

### Feature 1: Advanced Message Management
- **Edit Messages**: Users can edit only their own messages. Displays a pencil `✏️` icon in the message actions bar. Broadcasts `message_edited` via WebSockets and marks message with `(edited)`.
- **Delete Messages**: Users can delete their own messages (and admins can remove any message). Prompts for confirmation. Implements soft-deletion in SQLite (`is_deleted = 1`), broadcasts `message_deleted`, and ensures deleted messages never reappear upon refreshing.
- **Reply to Messages**: Click `↩️` on any message to trigger a quoted preview above the textarea. Saves `reply_to_id` in the database. Clicking the quoted preview inside any message card scrolls smoothly to the parent message and flashes a pulse highlight animation.
- **Forward Messages**: Click `↪️` to open the Forward Modal. Users can pick any channel, group, or DM conversation. Preserves original author attribution with a `↪ Forwarded from [Sender]` banner.

### Feature 2: Read Receipts & Unread Message Counters
- **Three-Tier Status Indicators**:
  - `✓` (Grey single tick): Message sent to server.
  - `✓✓` (Grey double tick): Message delivered to recipient client session.
  - `✓✓` (Cyan/blue double tick): Message read by recipient.
- **Unread Counters**: Dynamic unread badges beside channels, groups, and direct messages in the sidebar. Automatically marks messages as read when opening a conversation and pushes real-time updates via `messages_read` Socket.IO events.

### Feature 3: Group Chat
- **Group Creation**: Create group modal with group name, description, avatar color picker, and user multi-select checklist. Group creator automatically becomes group admin.
- **Group Management**: Group admin can add and remove members, and edit group info. Members can leave groups.
- **Group Details Panel**: View members and their online status in the right sidebar panel.
- **Security**: Strictly prevents unauthorized users from joining or reading private group rooms.

### Feature 4: Notification Center
- **Bell Icon with Unread Badge**: Located in the top header.
- **Notification Types**: Direct messages, group messages, user mentions (`@username`), replies to user messages, group additions, and emoji reactions.
- **Features**: Mark individual notification as read, "Mark all as read" button, and clicking a notification automatically opens the relevant channel/group/DM and scrolls to the message.

### Feature 5: Admin Dashboard & Analytics
- **Secure Access**: Protected on backend via `@admin_required` decorator (returns 403 Forbidden to non-admin accounts). Accessible via `/admin` or the shield `🛡️` button in the sidebar footer for admin users.
- **Metrics Overview**: Total users, active users, total messages, public channels, group chats, and pending reports.
- **Visual Analytics**: Responsive Chart.js visualizations for daily message volume (last 7 days) and most active channels.
- **User Management**: Live user search, suspend / reactivate accounts, and promote / demote administrative roles.
- **Moderation Log**: Full audit log of all administrative actions.

### Feature 6: Advanced Moderation & Message Reporting
- **Message Reporting**: Users can report messages by clicking the flag `🚩` icon. Supports reasons (`spam`, `harassment`, `abuse`, `inappropriate`, `other`) and optional details. Enforces unique constraints to prevent duplicate reports by the same user.
- **Admin Review**: Admins can review pending reports from the dashboard and execute actions: Dismiss Report, Delete Inappropriate Message, Warn User, or Suspend Account.
- **Profanity Filter**: Regex-based tokenization that preserves original message casing, structure, and punctuation while censoring prohibited words with asterisks matching word length.
