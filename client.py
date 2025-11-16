import asyncio
import os
import platform
import time
import threading
import random

import sounddevice as sd
import numpy as np
import cv2

import socketio
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
import av
from aiortc.sdp import candidate_from_sdp


DEVICE_ID = "Pi-Unit-001"
SERVER_URL = "http://localhost:3000"
PHONE_VIDEO_URL = "http://192.0.0.4:8080/video"

VOLUME_THRESHOLD = 0.11
COOLDOWN_SECONDS = 5
SIREN_FILE = "siren.mp3"


sio = socketio.AsyncClient(reconnection=True, reconnection_attempts=999)

# State
_last_alert_time = 0
_stop_threads = False

# WebRTC state
pc: RTCPeerConnection | None = None
camera_track = None
_webrtc_started = False
_offer_task = None

# Buffer for incoming ICE candidates received before pc is ready
_ice_buffer = []

# Lock to avoid concurrent re-creates
_pc_lock = asyncio.Lock()


# ---------- AUDIO THREAD ----------
def audio_thread(loop: asyncio.AbstractEventLoop):
    """Runs in a separate thread. Schedules async emits on the asyncio loop."""
    global _last_alert_time, _stop_threads

    try:
        devs = sd.query_devices()
        print("🎤 sounddevice devices found:", len(devs))
    except Exception:
        pass

    def callback(indata, frames, time_info, status):
        global _last_alert_time
        try:
            if indata is None:
                return
            arr = np.asarray(indata)
            if arr.size == 0:
                return
            mono = np.mean(arr, axis=1) if arr.ndim == 2 else arr
            volume_rms = np.sqrt(np.mean(mono**2))
            now = time.time()

            if volume_rms > 0.01:
                print(f"🔊 RMS: {volume_rms:.4f}")

            if volume_rms > VOLUME_THRESHOLD:
                if now - _last_alert_time >= COOLDOWN_SECONDS:
                    print(f"🎤 HIGH VOLUME DETECTED — RMS: {volume_rms:.4f}")

                    def emit_alert():
                        return sio.emit("new_alert", {
                            "id": f"#A-{random.randint(10000, 99999)}",
                            "deviceId": DEVICE_ID,
                            "location": "SafeCam Simulation Zone",
                            "latitude": 13.0827,
                            "longitude": 80.2707,
                            "status": "PENDING",
                            "timestamp": time.time()
                        })

                    try:
                        loop.call_soon_threadsafe(lambda: asyncio.ensure_future(emit_alert()))
                    except Exception as e:
                        print("⚠ Could not schedule alert emit:", e)

                    print("📡 Alert scheduled to dashboard!")
                    _last_alert_time = now

        except Exception as e:
            print("❌ Audio callback error:", e)

    print("🎤 Starting microphone listening (audio thread)...")
    try:
        with sd.InputStream(callback=callback):
            while not _stop_threads:
                sd.sleep(200)
    except Exception as e:
        print("❌ Error in audio thread:", e)


# ---------- CAMERA TRACK ----------
class CameraStream(VideoStreamTrack):
    def __init__(self, url: str):
        super().__init__()
        self.url = url
        self.cap = cv2.VideoCapture(url)
        if not self.cap.isOpened():
            print("❌ ERROR: Cannot open video feed:", url)

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        ret, frame = self.cap.read()
        if not ret:
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        vframe = av.VideoFrame.from_ndarray(frame_rgb, format="rgb24")
        vframe.pts = pts
        vframe.time_base = time_base
        return vframe

    def stop(self):
        try:
            if self.cap and self.cap.isOpened():
                self.cap.release()
        except Exception:
            pass


# ---------- Helper: create peer connection ----------
async def _create_peer():
    global pc, camera_track, _ice_buffer

    async with _pc_lock:
        if pc is not None:
            try:
                await pc.close()
            except Exception:
                pass
            pc = None

        pc = RTCPeerConnection()
        print("🔧 New RTCPeerConnection created")

        @pc.on("icecandidate")
        async def on_icecandidate(event):
            if event is None:
                return
            try:
                if event.candidate:
                    cand = event.candidate.to_sdp() if hasattr(event.candidate, "to_sdp") else str(event.candidate)
                    payload = {
                        "deviceId": DEVICE_ID,
                        "candidate": cand,
                        "sdpMid": getattr(event.candidate, "sdpMid", None),
                        "sdpMLineIndex": getattr(event.candidate, "sdpMLineIndex", None)
                    }
                    await sio.emit("webrtc_ice_candidate", payload)
            except Exception as e:
                print("❌ Error while emitting ICE candidate:", e)

        @pc.on("connectionstatechange")
        async def on_conn_state():
            try:
                print("ℹ️ RTC connectionState:", pc.connectionState)
                if pc.connectionState in ("failed", "closed", "disconnected"):
                    try:
                        await pc.close()
                    except Exception:
                        pass
            except Exception:
                pass

        camera_track = CameraStream(PHONE_VIDEO_URL)
        try:
            pc.addTrack(camera_track)
        except Exception as e:
            print("❌ Error adding track to pc:", e)

        if _ice_buffer:
            print(f"🔁 Draining {_ice_buffer.__len__()} buffered ICE candidates")
            for item in _ice_buffer:
                try:
                    cand_sdp = item.get("candidate")
                    sdpMid = item.get("sdpMid")
                    sdpMLineIndex = item.get("sdpMLineIndex")
                    if not cand_sdp:
                        continue
                    ice = candidate_from_sdp(cand_sdp)
                    ice.sdpMid = sdpMid
                    ice.sdpMLineIndex = sdpMLineIndex
                    await pc.addIceCandidate(ice)
                except Exception as e:
                    print("❌ Error while adding buffered ICE:", e)
            _ice_buffer = []

        return pc


# ---------- start webrtc with retry watchdog ----------
async def start_webrtc():
    global _webrtc_started, _offer_task, pc, camera_track

    print("🔄 start_webrtc() called")

    if pc is not None:
        try:
            print("⚠️ Closing previous RTCPeerConnection...")
            await pc.close()
        except Exception:
            pass

    await _create_peer()

    try:
        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)

        await sio.emit("webrtc_offer", {
            "deviceId": DEVICE_ID,
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type
        })

        print("📡 WebRTC offer sent to signaling server")

        async def _watch_for_answer(timeout=12):
            print("⏳ Waiting for webrtc_answer...")

            for _ in range(timeout):
                await asyncio.sleep(1)

                if pc is None:
                    return

                if pc.remoteDescription is not None:
                    print("✅ Answer received — watchdog stopping")
                    return

            print("⚠ Timeout — dashboard did NOT reply. Restarting WebRTC...")

            try:
                await pc.close()
            except:
                pass

            await asyncio.sleep(1)
            await start_webrtc()

        if _offer_task is None or _offer_task.done():
            _offer_task = asyncio.create_task(_watch_for_answer())

    except Exception as e:
        print("❌ Error starting WebRTC (offer):", e)


# ---------- SOCKET.IO EVENTS ----------
@sio.event
async def connect():
    global _webrtc_started
    print("✔ Connected to SafeCam+ Server")
    await sio.emit("register_device", {"deviceId": DEVICE_ID})
    asyncio.create_task(start_webrtc())


@sio.on("webrtc_answer")
async def on_webrtc_answer(data):
    global pc
    try:
        if not pc:
            print("⚠ Received webrtc_answer but pc is None")
            return
        print("📡 Received webrtc_answer from dashboard")
        desc = RTCSessionDescription(sdp=data["sdp"], type=data["type"])
        try:
            await pc.setRemoteDescription(desc)
            print("✅ remoteDescription set from answer")
        except Exception as e:
            print("❌ Error handling webrtc_answer:", e)
    except Exception as e:
        print("❌ Unexpected error in on_webrtc_answer:", e)

@sio.on("start_webrtc")
async def restart_webrtc(data=None):
    print("🔄 Restarting WebRTC due to dashboard refresh...")
    await start_webrtc()

@sio.on("webrtc_ice_candidate")
async def on_webrtc_ice_candidate(data):
    """
    Accept candidate strings from dashboard. If pc not ready, buffer them.
    """
    global pc, _ice_buffer
    try:
        print("🔥 RAW ICE RECEIVED:", data)

        cand_sdp = data.get("candidate")
        sdpMid = data.get("sdpMid")
        sdpMLineIndex = data.get("sdpMLineIndex")

        if not cand_sdp:
            return

        if pc is None:
            _ice_buffer.append({
                "candidate": cand_sdp,
                "sdpMid": sdpMid,
                "sdpMLineIndex": sdpMLineIndex
            })
            print("⏳ PC not ready — buffered ICE candidate")
            return

        try:
            ice = candidate_from_sdp(cand_sdp)
            ice.sdpMid = sdpMid
            ice.sdpMLineIndex = sdpMLineIndex
            await pc.addIceCandidate(ice)
            print("✅ ICE candidate added (converted)")
        except Exception as e:
            print("❌ Error adding ICE candidate (converted):", e)
            try:
                candidate_dict = {"candidate": cand_sdp, "sdpMid": sdpMid, "sdpMLineIndex": sdpMLineIndex}
                await pc.addIceCandidate(candidate_dict)
                print("✅ ICE candidate added (dict fallback)")
            except Exception as e2:
                print("❌ Fallback also failed for ICE:", e2)

    except Exception as e:
        print("❌ Unexpected error in on_webrtc_ice_candidate:", e)


@sio.on("trigger_siren")
async def on_trigger_siren(data=None):
    print("🚨 SIREN TRIGGER RECEIVED FROM DASHBOARD!")
    try:
        if platform.system() == "Windows":
            os.system(f'start {SIREN_FILE}')
        else:
            os.system(f"mpg123 {SIREN_FILE}")
    except Exception as e:
        print("❌ Error while playing siren:", e)


@sio.event
async def disconnect():
    print("❌ Disconnected from Server")
    try:
        if pc:
            await pc.close()
    except Exception:
        pass


# ---------- MAIN ----------
async def main():
    global _stop_threads, pc, camera_track

    loop = asyncio.get_running_loop()
    t = threading.Thread(target=audio_thread, args=(loop,), daemon=True)
    t.start()

    try:
        await sio.connect(SERVER_URL)
    except Exception as e:
        print("❌ Cannot connect to server:", e)
        _stop_threads = True
        return

    try:
        await sio.wait()
    except asyncio.CancelledError:
        pass
    finally:
        _stop_threads = True
        if camera_track:
            try:
                camera_track.stop()
            except Exception:
                pass
        if pc:
            try:
                await pc.close()
            except Exception:
                pass
        await sio.disconnect()
        print("👋 SafeCam+ Client stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 KeyboardInterrupt — exiting")

