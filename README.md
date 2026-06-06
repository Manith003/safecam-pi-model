# 🛡️ SafeCam Pi Model

An AI-powered edge client for the **SafeCam** security ecosystem, designed to run on a Raspberry Pi (or any Python-capable device). It performs **real-time audio distress detection** using a custom TensorFlow/Keras model, **streams live video** to the SafeCam Dashboard via WebRTC, and can **trigger a local siren** on command — all coordinated through a Socket.IO signaling server.

---

## 📐 System Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                        SafeCam Pi Unit                               │
│                                                                      │
│  ┌─────────────┐    ┌──────────────────┐    ┌────────────────────┐  │
│  │  Microphone  │───▶│  Audio Thread     │───▶│  TF/Keras Model    │  │
│  │  (sounddevice)│   │  (1.5s windows)   │   │  (audio_model.keras)│  │
│  └─────────────┘    └──────────────────┘    └────────┬───────────┘  │
│                                                       │              │
│                                          HELP detected│≥ 0.75 conf   │
│                                                       ▼              │
│  ┌─────────────┐    ┌──────────────────┐    ┌────────────────────┐  │
│  │ Phone Camera │───▶│  WebRTC Track     │───▶│   Socket.IO        │  │
│  │ (IP Webcam)  │   │  (aiortc + av)    │   │   Client           │──────▶ SafeCam Backend
│  └─────────────┘    └──────────────────┘    └────────────────────┘  │     (localhost:3000)
│                                                       ▲              │
│  ┌─────────────┐                                      │              │
│  │ Siren File  │◀──── trigger_siren event ────────────┘              │
│  │ (siren.mp3) │                                                     │
│  └─────────────┘                                                     │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 🌟 Features

| Feature | Description |
|---|---|
| 🎤 **Distress Audio Detection** | Classifies live microphone input into `HELP` vs `NOISE` using a trained Keras CNN on mel-spectrograms |
| 📹 **Live Video Streaming** | Streams video from an IP camera (phone) to the dashboard via WebRTC (aiortc) |
| 🚨 **Remote Siren Trigger** | Dashboard operators can trigger a local alarm (`siren.mp3`) on the Pi unit |
| 🔌 **Socket.IO Signaling** | Full-duplex communication with the SafeCam backend for alerts, WebRTC negotiation, and commands |
| 🔁 **Auto-Reconnect WebRTC** | Built-in watchdog that detects unanswered offers and automatically re-negotiates |
| 🧊 **ICE Candidate Buffering** | Buffers incoming ICE candidates if the peer connection isn't ready yet, drains on creation |
| ⏱️ **Alert Cooldown** | Configurable cooldown (default 15s) to prevent duplicate alert floods |
| 🐧 **Cross-Platform Siren** | Siren playback works on both Windows (`start`) and Linux/Pi (`mpg123`) |

---

## 🧠 ML Pipeline

```
Raw Audio (1.5s @ 16kHz)
        │
        ▼
┌───────────────────┐
│   Preprocessing   │
│  ┌─────────────┐  │
│  │ Pad / Trim   │  │   ← Fixed window: 24,000 samples
│  │ to 24000     │  │
│  └──────┬──────┘  │
│         ▼         │
│  ┌─────────────┐  │
│  │ Mel Spectro- │  │   ← 64 mel bands
│  │ gram (dB)    │  │
│  └──────┬──────┘  │
│         ▼         │
│  ┌─────────────┐  │
│  │ Pad / Trim   │  │   ← Target: 96 time frames
│  │ to 96 frames │  │
│  └──────┬──────┘  │
│         ▼         │
│  ┌─────────────┐  │
│  │ Z-score      │  │   ← (x - μ) / (σ + 1e-6)
│  │ Normalize    │  │
│  └─────────────┘  │
└────────┬──────────┘
         ▼
   Shape: (1, 64, 96, 1)
         │
         ▼
┌───────────────────┐
│  Keras CNN Model  │
│  audio_model.keras│
│                   │
│  Output: [help,   │
│           noise]  │
└────────┬──────────┘
         │
         ▼
  help_prob ≥ 0.75?
   YES → 🆘 ALERT
   NO  → continue
```

### Model Specifications

| Parameter | Value |
|---|---|
| Sample Rate | `16,000 Hz` |
| Window Duration | `1.5 seconds` (24,000 samples) |
| Mel Bands | `64` |
| Time Frames | `96` |
| Input Shape | `(1, 64, 96, 1)` |
| Output Classes | `[HELP, NOISE]` |
| Confidence Threshold | `0.75` |
| Model Format | Keras (`.keras`) |

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.10+**
- **FFmpeg** (for `aiortc` / `av`)
- **mpg123** (Linux/Pi — for siren playback)
- A working **microphone**
- An **IP camera** or phone running [IP Webcam](https://play.google.com/store/apps/details?id=com.pas.webcam) (or similar)
- **SafeCam Backend** running at the configured `SERVER_URL`

### 1. Clone the Repository

```bash
git clone https://github.com/Manith003/safecam-pi-model.git
cd safecam-pi-model
```

### 2. Create Virtual Environment

```bash
python -m venv venv

# Linux / macOS / Raspberry Pi
source venv/bin/activate

# Windows
venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

#### Core Dependencies

| Package | Purpose |
|---|---|
| `tensorflow` | Keras model inference |
| `librosa` | Mel-spectrogram extraction |
| `sounddevice` | Microphone audio capture |
| `numpy` | Numerical processing |
| `opencv-python` | Video frame capture (IP camera) |
| `aiortc` | WebRTC peer connection |
| `av` | Video frame encoding |
| `python-socketio[asyncio_client]` | Real-time server communication |

### 4. Place Required Files

```
safecam-pi-model/
├── main.py               # Entry point (provided source)
├── audio_model.keras      # ⚠️ Trained Keras model (YOU must provide)
├── siren.mp3              # ⚠️ Siren audio file (YOU must provide)
└── requirements.txt
```

> **Note:** The `audio_model.keras` file is your trained binary classifier. See [Training Your Own Model](#-training-your-own-model) below.

### 5. Configure Constants

Edit the top of `main.py`:

```python
DEVICE_ID       = "Pi-Unit-001"                    # Unique device identifier
SERVER_URL      = "http://localhost:3000"           # SafeCam backend URL
PHONE_VIDEO_URL = "http://192.168.1.4:8080/video"  # IP Webcam stream URL

VOLUME_THRESHOLD = 0.22       # (legacy) RMS threshold
COOLDOWN_SECONDS = 15         # Min seconds between alerts
SIREN_FILE       = "siren.mp3"
CONF             = 0.75       # Model confidence threshold
```

### 6. Start the SafeCam Backend

Ensure the [SafeCam Backend](https://github.com/Manith003/safecam-backend) is running:

```bash
# In the backend directory
npm run dev   # → http://localhost:3000
```

### 7. Start the IP Camera

Open **IP Webcam** on your phone and start the server. Note the URL (e.g., `http://192.168.1.4:8080/video`).

### 8. Run the Pi Client

```bash
python main.py
```

#### Expected Console Output

```
🎤 Listening (1.5 sec windows)...
✔ Connected to SafeCam+ Server
📡 WebRTC offer sent to signaling server
⏳ Waiting for webrtc_answer...
✅ Answer received — watchdog stopping
ℹ️ RTC connectionState: connected
HELP:0.03 NOISE:0.97
HELP:0.05 NOISE:0.95
HELP:0.88 NOISE:0.12
🆘 HELP DETECTED!
```

---

## 🔌 Socket.IO Event Reference

### Outgoing Events (Pi → Backend)

| Event | Payload | Trigger |
|---|---|---|
| `register_device` | `{ deviceId }` | On connect |
| `new_alert` | `{ id, deviceId, location, latitude, longitude, status, timestamp }` | HELP detected above threshold |
| `webrtc_offer` | `{ deviceId, sdp, type }` | WebRTC negotiation start |
| `webrtc_ice_candidate` | `{ deviceId, candidate, sdpMid, sdpMLineIndex }` | ICE candidate discovered |

### Incoming Events (Backend → Pi)

| Event | Payload | Action |
|---|---|---|
| `webrtc_answer` | `{ sdp, type }` | Sets remote SDP description |
| `webrtc_ice_candidate` | `{ candidate, sdpMid, sdpMLineIndex }` | Adds ICE candidate to peer connection |
| `start_webrtc` | `{}` | Re-initiates WebRTC (dashboard refresh) |
| `trigger_siren` | `{}` | Plays `siren.mp3` locally |

### Alert Payload Example

```json
{
  "id": "#A-48291",
  "deviceId": "Pi-Unit-001",
  "location": "SafeCam Simulation Zone",
  "latitude": 13.0827,
  "longitude": 80.2707,
  "status": "PENDING",
  "timestamp": 1717689600.123
}
```

---

## 🧵 Threading Model

```
┌──────────────────────────────────────────────┐
│              Main Thread                      │
│          (asyncio event loop)                 │
│                                              │
│  • Socket.IO connection & events             │
│  • WebRTC peer connection management         │
│  • Video frame encoding & streaming          │
│  • Siren trigger handling                    │
└──────────────────┬───────────────────────────┘
                   │
                   │  loop.call_soon_threadsafe()
                   │  (cross-thread alert emit)
                   │
┌──────────────────▼───────────────────────────┐
│           Audio Thread (daemon)              │
│                                              │
│  • Microphone recording (1.5s windows)       │
│  • Mel-spectrogram preprocessing             │
│  • TensorFlow model inference                │
│  • Cooldown management                       │
└──────────────────────────────────────────────┘
```

---

## ⚙️ Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `DEVICE_ID` | `"Pi-Unit-001"` | Unique identifier registered with the backend |
| `SERVER_URL` | `"http://localhost:3000"` | SafeCam backend Socket.IO endpoint |
| `PHONE_VIDEO_URL` | `"http://192.0.0.4:8080/video"` | IP Webcam video stream URL |
| `COOLDOWN_SECONDS` | `15` | Minimum gap between consecutive alerts |
| `CONF` | `0.75` | Minimum `help_prob` to trigger an alert |
| `SR` | `16000` | Audio sample rate (Hz) |
| `WINDOW` | `24000` | Audio samples per recording (1.5s) |
| `N_MELS` | `64` | Number of mel frequency bands |
| `TARGET` | `96` | Target spectrogram time frames |
| `MODEL_PATH` | `"audio_model.keras"` | Path to the trained Keras model |
| `SIREN_FILE` | `"siren.mp3"` | Path to the siren audio file |

---

## 🏋️ Training Your Own Model

The audio model is a binary classifier expecting input shape `(64, 96, 1)`.

### Dataset Structure

```
dataset/
├── help/       # Audio clips of distress calls / "help"
│   ├── help_001.wav
│   ├── help_002.wav
│   └── ...
└── noise/      # Background noise, speech, ambient sounds
    ├── noise_001.wav
    ├── noise_002.wav
    └── ...
```

### Training Outline

```python
# 1. Preprocess all audio files into mel-spectrograms (64 x 96)
# 2. Label: help → [1, 0], noise → [0, 1]
# 3. Train a CNN (e.g., Conv2D → MaxPool → Dense → Softmax)
# 4. Export as .keras:

model.save("audio_model.keras")
```

> **Tip:** Use data augmentation (time shift, noise injection, pitch shift) to improve robustness.

---

## 🛡️ Resilience & Edge Cases

| Scenario | Handling |
|---|---|
| Camera feed drops | Returns black frame `(480×640×3)` — stream continues |
| WebRTC answer timeout (12s) | Watchdog auto-restarts negotiation |
| ICE candidates arrive before PC ready | Buffered in `_ice_buffer`, drained on PC creation |
| Duplicate `connect` events | Guarded by `_connected` flag |
| Duplicate siren triggers | Guarded by `_siren_lock` with 6s cooldown |
| Audio silence (RMS < 0.01) | Frame skipped — no inference wasted |
| Server unreachable | Graceful exit with cleanup |
| `KeyboardInterrupt` | Clean shutdown of camera, PC, and Socket.IO |

---

## 🐛 Troubleshooting

| Problem | Solution |
|---|---|
| `❌ Cannot open video feed` | Verify `PHONE_VIDEO_URL` — ensure IP Webcam is running and accessible on the same network |
| `❌ Cannot connect to server` | Confirm SafeCam Backend is running on `SERVER_URL` |
| No microphone input | Run `python -m sounddevice` to list devices; set `sd.default.device` if needed |
| Model not found | Ensure `audio_model.keras` exists in the working directory |
| `mpg123: command not found` | Install: `sudo apt install mpg123` |
| TensorFlow import errors | Use `pip install tensorflow` or `tflite-runtime` for Pi Zero |
| WebRTC keeps restarting | Check firewall/NAT rules; ensure STUN/TURN servers if not on LAN |
| High CPU usage | Reduce `SR`, increase `COOLDOWN_SECONDS`, or use TFLite model |

---

## 📦 Project Files

```
safecam-pi-model/
├── main.py                # Application entry point
├── audio_model.keras       # Trained distress detection model
├── siren.mp3              # Alert siren audio file
├── requirements.txt       # Python dependencies
└── README.md              # This file
```

---

## 🔗 Related Repositories

| Repository | Description |
|---|---|
| [safecam-backend](https://github.com/Manith003/safecam-backend) | Node.js backend server with Socket.IO signaling |
| [safecam-dashboard](https://github.com/Manith003/safecam-dashboard) | Web-based monitoring dashboard with live video & alert management |

---

## 📝 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

## 👨‍💻 Author

**Manith003** — [@Manith003](https://github.com/Manith003)

---

<p align="center">
  Built with ❤️ for safer communities
</p>
