import os
import sys

# Configure UTF-8 stdout for Windows consoles
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.join(current_dir, "backend")
sys.path.insert(0, backend_dir)

from app import app, socketio

if __name__ == "__main__":
    print("=" * 65)
    print("  NexusChat Real-Time Application Server")
    print("  Web Client GUI : http://localhost:5000")
    print("  Terminal Client : python console_client.py")
    print("  Database        : chat.db (SQLite)")
    print("  Demo Accounts   : 'alex' / 'password123'")
    print("                    'sarah' / 'password123'")
    print("=" * 65)
    socketio.run(app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True)
