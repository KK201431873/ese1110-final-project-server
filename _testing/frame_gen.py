import cv2
import websocket
import time

SERVER_WS = "ws://ese.pongworks.dpdns.org/pi_stream"
pi_frequency = 10
pi_stream_password = "pongworks1110"

cap = cv2.VideoCapture(0)
ws = websocket.WebSocket()

def connect_ws():
    try:
        ws.close()
        ws.connect(SERVER_WS)
        ws.send(pi_stream_password)
    except Exception as e:
        print(f"Failed to connect to server.")

connect_ws()

try:
    while True:
        if not ws.connected:
            connect_ws()
        if ws.connected:
            ret, frame = cap.read()
            if not ret:
                continue
            frame = cv2.resize(frame, (320, 240))
            _, jpeg = cv2.imencode(".jpg", frame)
            try:
                ws.send(jpeg.tobytes(), opcode=websocket.ABNF.OPCODE_BINARY)
            except Exception as e:
                print("Failed to send frame.")
                connect_ws()
        time.sleep(1.0/pi_frequency) 
finally:
    ws.close()
    cap.release()
