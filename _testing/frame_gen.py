import cv2
import requests
import time

SERVER_URL = "https://ese.pongworks.dpdns.org/upload_frame"
AUTH_TOKEN = "SECRET_TOKEN"

cap = cv2.VideoCapture(0)  # adjust camera index if needed

last_time = time.time()
while True:
    start_time = time.time()
    ret, frame = cap.read()
    if not ret:
        continue

    # Resize or annotate if desired
    _, jpeg = cv2.imencode(".jpg", frame)

    try:
        response = requests.post(
            SERVER_URL,
            files={"frame": ("frame.jpg", jpeg.tobytes(), "image/jpeg")},
            headers={"X-Auth-Token": AUTH_TOKEN},
            timeout=2
        )
        if response.status_code != 200:
            print("Upload failed:", response.status_code)
    except Exception as e:
        print("Error:", e)

    now = time.time()
    delta_time = now - start_time
    last_time = now
    if 0.1-delta_time>0:
        time.sleep(0.1-delta_time)  # send ~10 fps
