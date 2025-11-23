from flask import Flask, request, redirect, render_template, make_response, jsonify
from flask_sock import Sock
import threading
import time
import queue
import os
import atexit
import psutil

app = Flask(__name__)
sock = Sock(app)

encoded_frame = None
frame_queue = queue.Queue(maxsize=1)
minimap_queue = queue.Queue(maxsize=1)

## Pi connection config
pi_camera_frequency = 10
pi_minimap_frequency = 20
pi_stream_password = "pongworks1110"

## Client connection config
MAX_CLIENTS = 10
# to register your browser as an admin, visit https://ese.pongworks.dpdns.org/ and enter this into chrome's JS console:
# localStorage.setItem("admin_token", "1e2d1c30ba116e0661a79fa751ab4f8e87b8a9efbc53004cffad7b33742e4ec2");
ADMIN_TOKEN = "1e2d1c30ba116e0661a79fa751ab4f8e87b8a9efbc53004cffad7b33742e4ec2"



## Keep a set of connected WebSocket clients
clients = set()
admin_clients = set()
pi_clients = set()

## Dictionary to store received variables
variables: dict[str, str] = {}  # name -> value



# --- Client viewing page ---
@app.route("/")
def index():
    """Redirect main page to the watch page"""
    return redirect("/watch")


@app.route("/watch")
def watch():
    """Render the watch page with WebSocket video feed"""
    admin_cookie = request.cookies.get("admin_token")
    is_admin = (admin_cookie == ADMIN_TOKEN)

    if len(clients) - len(admin_clients) >= MAX_CLIENTS and not is_admin:
        return redirect("/full")

    return render_template("watch_ws.html")


@app.route("/full")
def full_page():
    return render_template("server_full.html")


# --- Get admin cookie ---
@app.post("/set_admin_cookie")
def set_admin_cookie():
    data = request.get_json(force=True)
    token = data.get("token")

    resp = make_response(jsonify({"ok": True}))

    # Only set cookie if matches admin token
    if token == ADMIN_TOKEN:
        resp.set_cookie(
            "admin_token",
            token,
            httponly=True,     # JS cannot read the cookie directly
            samesite="Strict",
            secure=True        # required for HTTPS
        )
    return resp


# --- WebSocket route for video feed ---
@sock.route("/pi_stream")
def pi_stream(ws):
    """Authenticate data sender and continuously receive JPEG frames over WebSocket."""
    print("[*] Pi attempting to connect")

    # Step 0: Remove stale connections
    for old_ws in list(pi_clients):
        try:
            old_ws.close()
        except:
            pass
        pi_clients.discard(old_ws)

    # Step 1: Authenticate
    auth_msg = ws.receive()
    if auth_msg != pi_stream_password:
        print("[!] Unauthorized connection attempt")
        ws.close()
        return

    print("[+] Pi authenticated successfully")
    pi_clients.add(ws)

    try:
        while True:
            data = ws.receive()
            if data is None:
                break
            
            msg_type = data[0]
            payload = data[1:]

            match msg_type:
                case 1:  # Image
                    # Drop old frame if queue is full
                    try:
                        frame_queue.put(data, block=False)
                    except queue.Full:
                        try:
                            frame_queue.get_nowait()
                        except queue.Empty:
                            pass
                        frame_queue.put_nowait(data)
                    
                case 2:  # Variable
                    text = payload.decode('utf-8')
                    if ":" in text:
                        name, value = text.split(":", 1)
                        variables[name] = value
                        broadcast_variable_update(name, value)
                        continue

                case 3:  # Minimap
                    # Drop old frame if queue is full
                    try:
                        minimap_queue.put(data, block=False)
                    except queue.Full:
                        try:
                            minimap_queue.get_nowait()
                        except queue.Empty:
                            pass
                        minimap_queue.put_nowait(data)

                case _:
                    print("[!] Unknown message type received")
    finally:
        pi_clients.discard(ws)
        print("[*] Pi disconnected")


# --- WebSocket route for client monitoring ---
@sock.route("/video_feed")
def video_feed(ws):
    """Keep track of connected clients using a set, up to MAX_CLIENTS."""
    # Extract cookies
    cookies = ws.environ.get("HTTP_COOKIE", "")
    cookie_dict = dict(item.split("=", 1) for item in cookies.split("; ") if "=" in item)

    is_admin = (cookie_dict.get("admin_token") == ADMIN_TOKEN)

    # Count only normal viewers
    viewer_count = len(clients) - len(admin_clients)

    # Enforce viewer limit for non-admins
    if not is_admin and viewer_count >= MAX_CLIENTS:
        try:
            ws.send("SERVER_FULL")
            time.sleep(0.1)
            ws.close()
        except Exception:
            pass
        print("[!] Non-admin refused (server full)")
        return

    # Register client first
    clients.add(ws)

    # Track admin separately
    if is_admin:
        admin_clients.add(ws)

    viewer_count = len(clients) - len(admin_clients)
    user_type = "Admin" if is_admin else "Client"
    print(f"[+] {user_type} connected (admins={len(admin_clients)}, viewers={viewer_count}; admin={is_admin})")

    # Keep connection alive
    try:
        while True:
            if ws.receive() is None:
                break
    except:
        pass
    finally:
        clients.discard(ws)
        admin_clients.discard(ws) 

        print(f"[-] {user_type} disconnected (admins={len(admin_clients)}, viewers={len(clients)-len(admin_clients)})")


# --- Admin-only command route -----------------------------------
@app.post("/command_robot")
def command_robot():
    admin_cookie = request.cookies.get("admin_token")
    if admin_cookie != ADMIN_TOKEN:
        return jsonify({"ok": False, "message": "Not authorized"}), 403

    # Broadcast command to Pi via WebSockets
    req_data: dict = request.get_json()
    if req_data and "command_running" in req_data:
        running = req_data["command_running"]
        command: str = "START_ROBOT" if running else "STOP_ROBOT"
        broadcast_command(command)

        return jsonify({"ok": True, "message": f"{command} command sent"})
    
    return jsonify({"ok": False, "message": "Failed to get command request."})


# --- Broadcast to WebSocket clients ---
def broadcast_camera_worker():
    """Send latest camera frame to all connected clients."""
    global encoded_frame
    while True:
        try:
            encoded_frame = frame_queue.get(timeout=1)
        except queue.Empty:
            continue

        if clients:
            dead_clients = []
            for ws in clients.copy():
                try:
                    ws.send(encoded_frame)
                except Exception:
                    dead_clients.append(ws)
            for dc in dead_clients:
                clients.discard(dc)
                admin_clients.discard(dc)

        time.sleep(1.0 / pi_camera_frequency)


def broadcast_minimap_worker():
    """Send latest minimap frame to all connected clients."""
    global encoded_frame
    while True:
        try:
            encoded_minimap = minimap_queue.get(timeout=1)
        except queue.Empty:
            continue

        if clients:
            dead_clients = []
            for ws in clients.copy():
                try:
                    ws.send(encoded_minimap)
                except Exception:
                    dead_clients.append(ws)
            for dc in dead_clients:
                clients.discard(dc)

        time.sleep(1.0 / pi_minimap_frequency)


def broadcast_variable_update(name, value):
    """Send variable update to all connected clients."""
    msg = f"VAR_UPDATE:{name}:{value}"
    dead_clients = []
    for ws in clients.copy():
        try:
            ws.send(msg)
        except Exception:
            dead_clients.append(ws)
    for dc in dead_clients:
        clients.discard(dc)


def broadcast_command(cmd: str):
    """Send a command string to the Pi via WebSocket."""
    msg = f"CMD:{cmd}"
    dead = []
    for ws in pi_clients.copy():
        try:
            ws.send(msg)
            print(f"[broadcast_command] Sent {cmd} command!")
        except:
            dead.append(ws)
    for d in dead:
        pi_clients.discard(d)


# --- Graceful shutdown handler ---
def cleanup_on_exit():
    print("\n[!] Shutting down cleanly...")
    for ws in list(clients):
        try:
            ws.close()
        except Exception:
            pass
    clients.clear()

    # Close any remaining threads
    os._exit(0)


atexit.register(cleanup_on_exit)


# --- NEW: Ensure old instance isn’t already running ---
def free_port_if_in_use(port=5000):
    """Check if port is in use; if so, kill the process occupying it."""
    for conn in psutil.net_connections():
        if conn.laddr and conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
            pid = conn.pid
            if pid and pid != os.getpid():
                try:
                    print(f"[!] Port {port} already in use by PID {pid}. Killing it...")
                    p = psutil.Process(pid)
                    p.terminate()
                    p.wait(timeout=3)
                    print("[+] Old instance terminated.")
                except Exception as e:
                    print(f"[!] Failed to terminate PID {pid}: {e}")
            break


if __name__ == "__main__":
    from flask_cors import CORS

    CORS(app)

    # Kill any previous server still listening on port 5000
    free_port_if_in_use(5000)

    threading.Thread(target=broadcast_camera_worker, daemon=True).start()
    threading.Thread(target=broadcast_minimap_worker, daemon=True).start()
    print("Starting WebSocket video server on port 5000...")

    app.run(
        host="0.0.0.0",
        port=5000,
        threaded=True,
        use_reloader=False
    )