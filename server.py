from flask import Flask, request, redirect, render_template
from flask_sock import Sock
import threading
import time
import queue

app = Flask(__name__)
sock = Sock(app)

encoded_frame = None
frame_queue = queue.Queue(maxsize=1)
pi_frequency = 10
pi_stream_password = "pongworks1110"

# Keep a set of connected WebSocket clients
clients = set()

# Dictionary to store received variables
variables: dict[str, str] = {}  # name -> value



# --- Client viewing page ---
@app.route("/")
def index():
    """Redirect main page to the watch page"""
    return redirect("/watch")


@app.route("/watch")
def watch():
    """Render the watch page with WebSocket video feed"""
    return render_template("watch_ws.html")


# --- WebSocket route for video feed ---
@sock.route("/pi_stream")
def pi_stream(ws):
    """Authenticate data sender and continuously receive JPEG frames over WebSocket."""
    print("[*] Pi attempting to connect")

    # Step 1: Authenticate
    auth_msg = ws.receive()
    if auth_msg != pi_stream_password:
        print("[!] Unauthorized connection attempt")
        ws.close()
        return

    print("[+] Pi authenticated successfully")
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
                case _:
                    print("[!] Unknown message type received")
    finally:
        print("[*] Pi disconnected")


# --- WebSocket route for client monitoring ---
@sock.route("/video_feed")
def video_feed(ws):
    """Keep track of connected clients using a set."""
    clients.add(ws)
    print(f"[+] Client connected ({len(clients)} total)")
    try:
        while True:
            data = ws.receive()
            # When data is none, it means client has disconnected
            if data is None:
                break
    finally:
        clients.discard(ws)
        print(f"[-] Client disconnected ({len(clients)} total)")


# --- Broadcast to WebSocket clients ---
def broadcast_worker():
    """Send latest frame to all connected clients."""
    global encoded_frame
    while True:
        try:
            # Always take the newest frame from the queue
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

        time.sleep(1.0 / pi_frequency)


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


# --- Run setup ---
if __name__ == "__main__":
    from flask_cors import CORS
    from flask_sock import Sock
    import atexit

    CORS(app)

    threading.Thread(target=broadcast_worker, daemon=True).start()

    print("Starting WebSocket video server on port 5000...")
    app.run(host="0.0.0.0", port=5000, threaded=True)
