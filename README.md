# ⚡ NexusChat — Real-Time Chat Application

A modern, high-performance **Real-Time Chat Application** built using **Python, Flask, and WebSockets (Flask-SocketIO)** with SQLite message and user persistence. Supports both a rich **Web GUI** and an interactive **Console / Terminal Client**.

---

## 📁 Project Structure

As specified in the design architecture:

```text
real-time-chat-app/
├── backend/
│   ├── app.py              # Flask server, REST APIs, and Socket.IO event handlers
│   ├── database.py         # SQLite connection, schema initialization & CRUD queries
│   ├── auth.py             # Registration, login, password hashing, and session management
│   ├── moderation.py       # Automated profanity filter & content sanitization logic
│   └── requirements.txt    # Python dependencies
├── frontend/
│   ├── index.html        # Authentication & landing page (Login / Register)
│   ├── chat.html         # Full-featured chat workspace interface
│   ├── style.css         # Modern Cyber/Dark glassmorphic styling
│   └── script.js         # WebSocket client logic, audio synthesizer & state
├── console_client.py     # Interactive terminal client with ANSI colors & WebSocket sync
├── run.py                # Server launcher script
└── chat.db               # SQLite database (automatically created and seeded)
```

---

## 🚀 Quick Start

### 1. Install Dependencies
```bash
cd real-time-chat-app
pip install -r backend/requirements.txt
```

### 2. Start the Server
Run the launcher script:
```bash
python run.py
```
*The server will start on `http://localhost:5000`.*

---

## 🌐 Running the Web GUI

Open your browser and navigate to:
```
http://localhost:5000
```

### 👥 Instant Demo Accounts
The database is pre-seeded with sample users for instant 1-click testing:
- **Alex Rivers**: `alex` / `password123`
- **Sarah Chen**: `sarah` / `password123`
*(You can also click the quick demo buttons on the login page or register a new custom account).*

> **Tip for Dual-Client Testing**: Open one tab in standard mode as **Alex**, and another tab in an **Incognito / Private Window** as **Sarah** to see real-time messaging, typing indicators, reactions, and online status updates live!

---

## 💻 Running the Terminal / Console Client

You can also chat directly from your terminal! The console client connects over WebSockets in real-time with browser users:

```bash
python console_client.py
```

### Console Commands:
- `/rooms` — List all available channels
- `/join <channel>` — Switch channels (e.g. `/join tech-talk`)
- `/users` — List all registered users and their online status
- `/help` — Ask Nova Bot for assistance
- `/quit` — Exit the client

---

## 🌟 Key Features

1. **Bidirectional Real-Time Communication**:
   - Powered by WebSockets with automatic fallback to long-polling via Flask-SocketIO.
   - Low latency message delivery, status updates, and reactions.

2. **Channels & 1-on-1 Direct Messaging (DMs)**:
   - Default channels: `#general`, `#tech-talk`, `#random`, `#announcements`.
   - Create custom channels dynamically with custom icons.
   - Click any user to start a private, persistent 1-on-1 Direct Message conversation.

3. **Message Enhancements**:
   - **Markdown Support**: Bold (`**bold**`), italics (`*italic*`), inline code (` `code` `), and syntax-highlighted code blocks (` ```code``` `).
   - **Emoji Picker & Reactions**: Inline quick reactions (`👍`, `❤️`, `😂`, `🔥`, `🚀`, `🎉`) with live counters.
   - **File & Media Attachments**: Upload and preview images directly in chat.
   - **Typing Indicators**: Real-time notifications when another user is composing a message.

4. **Zero-Dependency Sound Synthesizer**:
   - Custom Web Audio API sound effects for sent and received messages (no external audio files required, toggleable via bell icon).

5. **Built-in Automated Assistant (Nova Bot)**:
   - Mention `@nova` or type `/joke`, `/quote`, or `/help` in any channel to get instant automated responses.

6. **SQLite Persistence (`chat.db`)**:
   - Robust relational schema with foreign keys for `users`, `rooms`, `messages`, and `reactions`.
   
7. **Automated Content Moderation**:
   - Integrated custom profanity filter (`backend/moderation.py`) that intercepts incoming messages, checks against prohibited terms, and automatically censors bad words (`****`) before database storage and live broadcast.

8. **Real-Time Typing Indicator**:
   - Interactive typing state updates using client-side debouncing and WebSockets, rendering animated typing indicators (`[User] is typing...`) across online clients.
