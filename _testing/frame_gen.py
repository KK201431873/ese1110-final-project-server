import cv2
import websocket
import time
import numpy as np
import math
import sys


SERVER_WS = "ws://ese.pongworks.dpdns.org/pi_stream"
pi_camera_frequency = 10
pi_minimap_frequency = 30
pi_stream_password = "pongworks1110"

"""
Minimap drawing config
"""
robot_x: float = 0
robot_y: float = 0
robot_heading: float = math.pi/3

mmap_width: int = 640
mmap_height: int = 320
mmap_real_width: float = 4 # meters
aspect_ratio: float = mmap_width / mmap_height
meters_per_pixel: float = mmap_real_width / mmap_width

robot_width: float = 0.4 # meters

grid_lines_per_meter: int = 4
grid_width: float = 1.0 / grid_lines_per_meter # meters

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

last_cam_frame_time = time.perf_counter()
last_minimap_frame_time = time.perf_counter()

try:
    while True:
        now = time.perf_counter()

        if not ws.connected:
            connect_ws()
        if ws.connected:
            # # Get and send camera frame
            # if (now - last_cam_frame_time >= 1.0 / pi_camera_frequency):
            #     ret, frame = cap.read()
            #     if not ret:
            #         continue
            #     frame = cv2.resize(frame, (320, 240))
            #     _, jpeg = cv2.imencode(".jpg", frame)
            #     try:
            #         ws.send(b"\x01" +jpeg.tobytes(), opcode=websocket.ABNF.OPCODE_BINARY)
            #     except Exception as e:
            #         print("Failed to send frame.")
            #         connect_ws()
            #     last_cam_frame_time = now

            # simulate robot movement
            robot_x = 2.0 * math.cos(time.time() * 0.5)
            robot_y = 2.0 * math.sin(time.time() * 0.5)
            robot_heading = math.pi*math.sin(time.time())

            # Draw and send minimap
            if (now - last_minimap_frame_time >= 1.0 / pi_minimap_frequency):
                minimap = np.zeros((mmap_height, mmap_width, 3), dtype=np.uint8)
                minimap[:] = (20, 20, 20) # Create a blank dark background
                center = (mmap_width // 2, mmap_height // 2)

                # --- Draw grid lines ---
                grid_color_minor = (40, 40, 40)
                grid_color_major = (70, 70, 70)

                # Pixels per meter
                px_per_m = 1.0 / meters_per_pixel

                # Center world coordinates (in meters)
                cx, cy = robot_x, robot_y

                # Compute world-space bounds visible in minimap
                half_width_m = (mmap_width / 2) * meters_per_pixel
                half_height_m = (mmap_height / 2) * meters_per_pixel

                xmin = cx - half_width_m
                xmax = cx + half_width_m
                ymin = cy - half_height_m
                ymax = cy + half_height_m

                # Round down to nearest grid step to start lines cleanly
                start_x = math.floor(xmin / grid_width) * grid_width
                start_y = math.floor(ymin / grid_width) * grid_width

                # Draw vertical and horizontal grid lines
                for gx in np.arange(start_x, xmax, grid_width):
                    x_px = int((gx - cx) * px_per_m + mmap_width / 2)
                    is_major = (round(gx / grid_width) % grid_lines_per_meter == 0)
                    color = grid_color_major if is_major else grid_color_minor
                    cv2.line(minimap, (x_px, 0), (x_px, mmap_height), color, 1, cv2.LINE_AA)

                for gy in np.arange(start_y, ymax, grid_width):
                    y_px = int(mmap_height / 2 - (gy - cy) * px_per_m)
                    is_major = (round(gy / grid_width) % grid_lines_per_meter == 0)
                    color = grid_color_major if is_major else grid_color_minor
                    cv2.line(minimap, (0, y_px), (mmap_width, y_px), color, 1, cv2.LINE_AA)

                # --- Draw robot in center ---
                bot_side_length = int(robot_width * mmap_width / mmap_real_width)
                rect = (center, (bot_side_length, bot_side_length), -math.degrees(robot_heading)) 
                box = cv2.boxPoints(rect)
                box = np.intp(box)
                
                # semi-transparent fill + outline
                overlay = minimap.copy()
                cv2.fillPoly(overlay, [box], color=(255, 255, 255)) # type: ignore
                alpha = 0.4
                cv2.addWeighted(overlay, alpha, minimap, 1 - alpha, 0, minimap)
                cv2.polylines(minimap, [box], isClosed=True, color=(255, 255, 255), thickness=1, lineType=cv2.LINE_AA) # type: ignore
                
                # Draw heading line
                end_x = int(center[0] + bot_side_length/2 * np.cos(robot_heading))
                end_y = int(center[1] - bot_side_length/2 * np.sin(robot_heading))
                cv2.line(minimap, center, (end_x, end_y), (255, 255, 255), thickness=1, lineType=cv2.LINE_AA)

                # --- Draw ball (if detected) ---
                _target_relative_position = (40*math.cos(1.31*time.time()), 30*math.sin(1.1*time.time()))
                if _target_relative_position:
                    bx = int(center[0] + _target_relative_position[1])  # left-right offset
                    by = int(center[1] - _target_relative_position[0])  # forward offset
                    cv2.circle(minimap, (bx, by), 6, (0, 165, 255), thickness=cv2.FILLED, lineType=cv2.LINE_AA)
                
                # minimap = cv2.resize(minimap, (320, 240))
                _, jpeg = cv2.imencode(".jpg", minimap)
                try:
                    ws.send(b"\x03" +jpeg.tobytes(), opcode=websocket.ABNF.OPCODE_BINARY)
                except Exception as e:
                    print("Failed to send minimap.")
                    connect_ws()
                last_minimap_frame_time = now

finally:
    ws.close()
    cap.release()
