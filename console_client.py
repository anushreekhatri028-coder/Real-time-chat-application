import sys
import time
import requests
import socketio

# Configure UTF-8 stdout for Windows consoles
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Color formatting helpers for terminal
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
MAGENTA = "\033[95m"
BLUE = "\033[94m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

SERVER_URL = "http://localhost:5000"

sio = socketio.Client()
session_http = requests.Session()

current_user = None
current_room = None
all_rooms = []


# ==============================================================================
# Socket.IO Client Event Handlers
# ==============================================================================

@sio.event
def connect():
    print(f"{GREEN}✓ Connected to NexusChat WebSocket server!{RESET}\n")


@sio.event
def disconnect():
    print(f"\n{RED}Disconnected from server.{RESET}")


@sio.on("new_message")
def on_new_message(data):
    if not current_room or data.get("room_id") != current_room.get("id"):
        return

    sender = data.get("display_name") or data.get("username", "Unknown")
    content = data.get("content", "")
    is_bot = data.get("username") == "nova_bot" or data.get("message_type") == "bot"
    timestamp = data.get("timestamp", "")[-8:]

    if is_bot:
        print(f"\n{CYAN}{BOLD}[BOT] {sender}{RESET} {DIM}({timestamp}){RESET}: {content}")
    elif current_user and data.get("sender_id") == current_user.get("id"):
        # Own message echo
        print(f"\n{GREEN}{BOLD}[You]{RESET} {DIM}({timestamp}){RESET}: {content}")
    else:
        print(f"\n{MAGENTA}{BOLD}[{sender}]{RESET} {DIM}({timestamp}){RESET}: {content}")

    # Re-prompt
    print(f"{BLUE}#{current_room.get('name', 'chat')}>{RESET} ", end="", flush=True)


@sio.on("user_typing")
def on_user_typing(data):
    if current_room and data.get("room_id") == current_room.get("id"):
        name = data.get("display_name") or data.get("username")
        # Print subtle indicator without disturbing input
        # sys.stdout.write(f"\r{DIM}* {name} is typing...{RESET}\r")


# ==============================================================================
# REST API Helpers
# ==============================================================================

def api_login(identifier, password):
    try:
        res = session_http.post(f"{SERVER_URL}/api/auth/login", json={
            "identifier": identifier,
            "password": password
        })
        data = res.json()
        if data.get("success"):
            return data["user"]
        else:
            print(f"{RED}Login failed: {data.get('error')}{RESET}")
            return None
    except Exception as e:
        print(f"{RED}Error connecting to server: {e}{RESET}")
        return None


def api_register(username, email, password, display_name):
    try:
        res = session_http.post(f"{SERVER_URL}/api/auth/register", json={
            "username": username,
            "email": email,
            "password": password,
            "display_name": display_name
        })
        data = res.json()
        if data.get("success"):
            return data["user"]
        else:
            print(f"{RED}Registration failed: {data.get('error')}{RESET}")
            return None
    except Exception as e:
        print(f"{RED}Error connecting to server: {e}{RESET}")
        return None


def fetch_rooms():
    global all_rooms
    try:
        res = session_http.get(f"{SERVER_URL}/api/rooms")
        data = res.json()
        if data.get("success"):
            all_rooms = data["rooms"]
            return all_rooms
    except Exception as e:
        print(f"{RED}Failed to fetch rooms: {e}{RESET}")
    return []


def fetch_users():
    try:
        res = session_http.get(f"{SERVER_URL}/api/users")
        data = res.json()
        if data.get("success"):
            return data["users"]
    except Exception as e:
        print(f"{RED}Failed to fetch users: {e}{RESET}")
    return []


def join_channel(room_id):
    global current_room
    if current_room:
        sio.emit("leave_room", {"room_id": current_room["id"]})

    room = next((r for r in all_rooms if r["id"] == room_id), None)
    if not room:
        print(f"{RED}Room ID {room_id} not found.{RESET}")
        return

    current_room = room
    sio.emit("join_room", {"room_id": room["id"]})
    print(f"\n{YELLOW}--- Switched to #{room['name']} ({room.get('description', '')}) ---{RESET}\n")

    # Fetch recent history
    try:
        res = session_http.get(f"{SERVER_URL}/api/messages/{room['id']}?limit=15")
        data = res.json()
        if data.get("success"):
            for m in data.get("messages", []):
                sender = m.get("display_name") or m.get("username")
                ts = m.get("timestamp", "")[-8:]
                is_bot = m.get("username") == "nova_bot" or m.get("message_type") == "bot"
                color = CYAN if is_bot else (GREEN if m.get("sender_id") == current_user["id"] else MAGENTA)
                print(f"{color}[{sender}]{RESET} {DIM}({ts}){RESET}: {m.get('content')}")
            print(f"{DIM}--- Recent message history above ---{RESET}\n")
    except Exception as e:
        pass


# ==============================================================================
# Main Interactive CLI Loop
# ==============================================================================

def main():
    global current_user

    print(f"""
{CYAN}{BOLD}=============================================================
       ⚡ NexusChat — Real-Time Terminal Console Client ⚡
============================================================={RESET}
""")

    # Check connection to server
    try:
        session_http.get(f"{SERVER_URL}/api/auth/me", timeout=3)
    except Exception:
        print(f"{RED}Error: Cannot reach server at {SERVER_URL}. Please ensure 'app.py' is running!{RESET}")
        return

    print("Please select an option:")
    print(" 1) Quick Login as Demo User 'alex'")
    print(" 2) Quick Login as Demo User 'sarah'")
    print(" 3) Custom Login")
    print(" 4) Register New User")
    choice = input("\nEnter choice (1-4) [default: 1]: ").strip() or "1"

    if choice == "1":
        current_user = api_login("alex", "password123")
    elif choice == "2":
        current_user = api_login("sarah", "password123")
    elif choice == "3":
        ident = input("Username or Email: ").strip()
        pwd = input("Password: ").strip()
        current_user = api_login(ident, pwd)
    elif choice == "4":
        uname = input("Desired Username: ").strip()
        email = input("Email: ").strip()
        dname = input("Display Name: ").strip()
        pwd = input("Password: ").strip()
        current_user = api_register(uname, email, pwd, dname)
    else:
        print(f"{RED}Invalid selection.{RESET}")
        return

    if not current_user:
        print(f"{RED}Authentication failed. Exiting.{RESET}")
        return

    print(f"\n{GREEN}Welcome back, {BOLD}{current_user['display_name']}{RESET} (@{current_user['username']})!{RESET}")

    # Connect Socket.IO
    # Pass session cookies from requests so Flask-SocketIO recognizes the authenticated user
    cookies = session_http.cookies.get_dict()
    cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])

    sio.connect(
        SERVER_URL,
        headers={"Cookie": cookie_str},
        auth={"user_id": current_user["id"]},
        transports=["websocket", "polling"]
    )

    fetch_rooms()
    # Default to general
    gen_room = next((r for r in all_rooms if r["name"] == "general"), all_rooms[0] if all_rooms else None)
    if gen_room:
        join_channel(gen_room["id"])

    print(f"""{YELLOW}Type your message and press Enter to chat.
Commands:
  /rooms             - List channels
  /join <name>       - Switch channel
  /users             - List online/registered users
  /help              - Ask Nova Bot for help
  /quit              - Exit client
{RESET}""")

    while True:
        try:
            line = input(f"{BLUE}#{current_room.get('name', 'chat')}>{RESET} ").strip()
            if not line:
                continue

            if line in ("/quit", "/exit"):
                print(f"{YELLOW}Goodbye!{RESET}")
                break

            elif line == "/rooms":
                rooms = fetch_rooms()
                print(f"\n{BOLD}Available Channels:{RESET}")
                for r in rooms:
                    active_marker = f"{GREEN}* {RESET}" if r["id"] == current_room["id"] else "  "
                    print(f" {active_marker}#{r['name']} — {r.get('description', '')}")
                print()

            elif line.startswith("/join "):
                target_name = line.split(" ", 1)[1].strip().lstrip("#")
                target_room = next((r for r in all_rooms if r["name"].lower() == target_name.lower()), None)
                if target_room:
                    join_channel(target_room["id"])
                else:
                    print(f"{RED}Channel #{target_name} not found. Type /rooms to see list.{RESET}")

            elif line == "/users":
                users = fetch_users()
                print(f"\n{BOLD}Users Directory:{RESET}")
                for u in users:
                    status_col = GREEN if u.get("status") == "online" else DIM
                    print(f" {status_col}● {u['display_name']} (@{u['username']}) - {u.get('status', 'offline')}{RESET}")
                print()

            else:
                # Send chat message via WebSocket
                sio.emit("send_message", {
                    "room_id": current_room["id"],
                    "content": line,
                    "message_type": "text"
                })

        except (KeyboardInterrupt, EOFError):
            print(f"\n{YELLOW}Exiting client...{RESET}")
            break

    sio.disconnect()


if __name__ == "__main__":
    main()
