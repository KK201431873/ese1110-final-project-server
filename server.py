from flask import Flask, request, abort, redirect, render_template
from flask_sock import Sock
import threading
import time
import queue
import cv2
import numpy as np

app = Flask(__name__)
sock = Sock(app)

latest_frame = None
encoded_frame = None
frame_lock = threading.Lock()
frame_queue = queue.Queue(maxsize=1)

# Keep a set of connected WebSocket clients
clients = set()


# --- Route: robot uploads a new frame ---
@app.route("/upload_frame", methods=["POST"])
def upload_frame():
    token = request.headers.get("X-Auth-Token")
    if token != "SECRET_TOKEN":
        abort(403)

    file = request.files.get("frame")
    if not file:
        abort(400, "No frame uploaded")

    img_bytes = file.read()
    np_img = np.frombuffer(img_bytes, np.uint8)
    frame = cv2.imdecode(np_img, cv2.IMREAD_COLOR)

    # Downscale for efficiency (optional)
    if frame is not None and isinstance(frame, np.ndarray):
        frame = cv2.resize(frame, (320, 240))
    else:
        abort(400, "Invalid frame")

    # Non-blocking put; drop oldest if full
    try:
        if frame_queue.full():
            frame_queue.get_nowait()
        frame_queue.put_nowait(frame)
    except queue.Full:
        pass

    return "OK"


# --- Background encoder ---
def encode_worker():
    global latest_frame, encoded_frame
    while True:
        try:
            frame = frame_queue.get(timeout=1)
            success, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
            if success:
                with frame_lock:
                    latest_frame = frame
                    encoded_frame = buffer.tobytes()
        except queue.Empty:
            continue


# --- Broadcast to WebSocket clients ---
def broadcast_worker():
    """Send the latest encoded frame to all connected clients."""
    while True:
        if encoded_frame is not None and clients:
            dead_clients = []
            for ws in clients.copy():
                try:
                    ws.send(encoded_frame)
                except Exception:
                    dead_clients.append(ws)
            for dc in dead_clients:
                clients.discard(dc)
        time.sleep(0.1) 


# WebSocket route for the Pi to send frames
@sock.route("/pi_stream")
def pi_stream(ws):
    global encoded_frame
    print("[*] Pi connected")
    try:
        while True:
            data = ws.receive()
            if data is None:
                break
            # Received JPEG bytes from Pi
            with frame_lock:
                encoded_frame = data
    finally:
        print("[*] Pi disconnected")

# --- WebSocket route for video feed ---
@sock.route("/video_feed")
def video_feed(ws):
    clients.add(ws)
    print(f"[+] Client connected ({len(clients)} total)")
    try:
        while True:
            data = ws.receive()
            if data is None:
                break
    finally:
        clients.discard(ws)
        print(f"[-] Client disconnected ({len(clients)} total)")


# --- Simple viewer page ---
@app.route("/")
def index():
    return redirect("/watch")


@app.route("/watch")
def watch():
    return render_template("watch_ws.html")


# --- Run setup ---
if __name__ == "__main__":
    from flask_cors import CORS
    from flask_sock import Sock
    import atexit

    CORS(app)

    threading.Thread(target=encode_worker, daemon=True).start()
    threading.Thread(target=broadcast_worker, daemon=True).start()

    print("Starting WebSocket video server on port 5000...")
    app.run(host="0.0.0.0", port=5000, threaded=True)
