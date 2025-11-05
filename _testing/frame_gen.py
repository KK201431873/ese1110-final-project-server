import cv2
import websocket
import time

SERVER_WS = "ws://ese.pongworks.dpdns.org/pi_stream"

cap = cv2.VideoCapture(0)
ws = websocket.WebSocket()
ws.connect(SERVER_WS)

try:
    while True:
        ret, frame = cap.read()
        if not ret:
            continue
        frame = cv2.resize(frame, (320, 240))
        _, jpeg = cv2.imencode(".jpg", frame)
        ws.send(jpeg.tobytes(), opcode=websocket.ABNF.OPCODE_BINARY)
        time.sleep(0.03)  # ~30 fps
finally:
    ws.close()
    cap.release()
