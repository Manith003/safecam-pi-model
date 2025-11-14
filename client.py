import socketio
import os
import sounddevice as sd
import numpy as np
import cv2
import time
import threading
import base64
import platform

DEVICE_ID = "Pi-Unit-001"   
SERVER_URL = "http://localhost:3000"   
PHONE_VIDEO_URL = "http://192.0.0.4:8080/video"   

VOLUME_THRESHOLD = 0.22
COOLDOWN_SECONDS = 2
SIREN_FILE = "siren.mp3"


sio = socketio.Client(
    reconnection=True,
    reconnection_delay=2,
    reconnection_attempts=999
)

last_alert_time = 0
threat_detected = False
stop_threads = False


@sio.event
def connect():
    print(f"✔ Connected to SafeCam+ Server")
    sio.emit("register_device", {"deviceId": DEVICE_ID})


@sio.on("trigger_siren")
def trigger_siren(data=None):
    print("🚨 SIREN TRIGGER RECEIVED FROM DASHBOARD!")

    if platform.system() == "Windows":
        os.system(f'start {SIREN_FILE}')
    else:
        os.system(f"mpg123 {SIREN_FILE}")


@sio.event
def disconnect():
    print("❌ Disconnected from Server. Reconnecting...")


def audio_thread():
    global last_alert_time, stop_threads

    def callback(indata, frames, time_info, status):
        global last_alert_time

        volume_rms = np.sqrt(np.mean(indata**2))
        now = time.time()

        if volume_rms > VOLUME_THRESHOLD:
            if now - last_alert_time >= COOLDOWN_SECONDS:
                print(f"🎤 HIGH VOLUME DETECTED — RMS: {volume_rms:.4f}")

                # send alert directly
                sio.emit("new_alert", {
                    "id": f"#A-{np.random.randint(10000, 99999)}",
                    "deviceId": DEVICE_ID,
                    "location": "SafeCam Simulation Zone",
                    "latitude": 13.0827,
                    "longitude": 80.2707,
                    "status": "PENDING",
                    "timestamp": time.time()
                })

                print("📡 Alert sent to dashboard!")
                last_alert_time = now

    try:
        print("🎤 Starting microphone listening...")
        with sd.InputStream(callback=callback):
            while not stop_threads:
                sd.sleep(200)
    except Exception as e:
        print("❌ Error in audio thread:", e)

def video_thread():
    global stop_threads

    print("📹 Connecting to phone camera...")
    cap = cv2.VideoCapture(PHONE_VIDEO_URL)

    if not cap.isOpened():
        print("❌ ERROR: Cannot open video feed. Check your phone stream.")
        return

    print("📹 Video stream connected!")

    while not stop_threads:
        ret, frame = cap.read()
        if not ret:
            print("⚠ Cannot read frame... retrying")
            time.sleep(1)
            continue

        _, buffer = cv2.imencode(".jpg", frame)
        frame_b64 = base64.b64encode(buffer).decode("utf-8")

        sio.emit("video_frame", {
            "deviceId": DEVICE_ID,
            "frame": frame_b64
        })

        time.sleep(0.06)

    cap.release()


if __name__ == "__main__":
    print("🔌 Connecting to SafeCam+ backend...")
    
    try:
        sio.connect(SERVER_URL)
    except Exception as e:
        print("❌ Cannot connect to server:", e)

    # Start audio thread
    t1 = threading.Thread(target=audio_thread)
    t1.daemon = True
    t1.start()

    # Start video stream thread
    video_thread()

    # Cleanup
    stop_threads = True
    sio.disconnect()
    print("👋 SafeCam+ Client stopped.")

