from flask import Flask, Response, redirect, request, abort, render_template
import time
import threading
import atexit
import io
import cv2
import numpy as np

app = Flask(__name__)

latest_frame = None
frame_lock = threading.Lock()

# --- Route: robot uploads a new frame ---
@app.route("/upload_frame", methods=["POST"])
def upload_frame():
    global latest_frame
    # Optional: basic auth token
    token = request.headers.get("X-Auth-Token")
    if token != "SECRET_TOKEN":
        abort(403)

    file = request.files.get("frame")
    if not file:
        abort(400, "No frame uploaded")

    img_bytes = file.read()
    np_img = np.frombuffer(img_bytes, np.uint8)
    frame = cv2.imdecode(np_img, cv2.IMREAD_COLOR)

    with frame_lock:
        latest_frame = frame
    return "OK"

# --- Stream frames to viewers ---
def generate_stream():
    frame_interval = 1.0 / 10.0  # 10 Hz
    while True:
        start = time.time()
        with frame_lock:
            if latest_frame is not None:
                _, buffer = cv2.imencode(".jpg", latest_frame)
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n"
                )
        elapsed = time.time() - start
        if elapsed < frame_interval:
            time.sleep(frame_interval - elapsed)

# --- Redirect root to /watch ---
@app.route("/")
def index():
    return redirect("/watch")

# --- Hidden MJPEG feed ---
@app.route("/video_feed")
def video_feed():
    referer = request.headers.get("Referer", "")
    if not referer.endswith("/watch"):
        abort(403)
    return Response(generate_stream(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")

# --- Visible watch page ---
@app.route("/watch")
def watch():
    return render_template("watch.html")

@atexit.register
def goodbye():
    print("Server stopped cleanly.")

if __name__ == "__main__":
    print("Starting Flask server...")
    app.run(host="0.0.0.0", port=5000)
