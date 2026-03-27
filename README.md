# Pi Webcam RTSP Streamer

Stream a USB webcam (Microsoft Lifecam HD-5000) from a Raspberry Pi 3B+ as an RTSP feed that VLC can play over the network.

## Architecture

```
Lifecam HD-5000 (/dev/video0)
        │  V4L2 / MJPEG
        ▼
     FFmpeg  ──RTSP push──▶  mediamtx (:8554)
                                 │
                                 ▼
                            VLC / any RTSP client
                            rtsp://<pi-ip>:8554/stream

  Python orchestrator
   └─ Web status page (:8080, HTTPS)
       ├─ Start/stop stream
       ├─ Switch resolution (720p/480p)
       ├─ Camera controls (brightness, focus)
       └─ Installable as PWA on mobile
```

- **mediamtx** — lightweight single-binary RTSP server
- **FFmpeg** — captures from the webcam via V4L2 and transcodes MJPEG → H.264
- **server.py** — manages both processes, serves a web status page

## Prerequisites

- Raspberry Pi 3B+ (or compatible) running Raspberry Pi OS (Bookworm or later)
- Microsoft Lifecam HD-5000 (or any UVC-compatible USB webcam)
- Network connection (wired or Wi-Fi)

## Setup

```bash
# Clone the repo
git clone <repo-url> pi-webcam-streamer-server
cd pi-webcam-streamer-server

# Run the setup script (installs ffmpeg, v4l-utils, downloads mediamtx, generates SSL cert)
sudo bash setup.sh

# Fix file ownership (setup runs as root)
sudo chown $(whoami):$(whoami) cert.pem key.pem mediamtx.yml
```

Verify the camera is detected:

```bash
v4l2-ctl --list-devices
```

You should see the Lifecam HD-5000 listed, typically as `/dev/video0`.

## Usage

```bash
# Start the server (auto-starts the stream)
venv/bin/python server.py
```

The server will print:

```
Starting stream from /dev/video0...
RTSP stream: rtsp://admin:password@192.168.1.100:8554/stream
Status page: https://192.168.1.100:8080/
Press Ctrl+C to stop.
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--device` | `/dev/video0` | V4L2 camera device path |
| `--port` | `8080` | Status page HTTP port |
| `--no-autostart` | off | Don't start streaming on launch (use the web UI to start) |

### Web Status Page

Open `https://<pi-ip>:8080/` in a browser to see stream status, the RTSP URL, and controls.

Features:
- **Start/Stop** the stream
- **Resolution switching** — choose between 720p @ 15fps and 480p @ 30fps (only while stopped)
- **Camera controls** — adjust brightness, focus, and autofocus via sliders
- **Live uptime** — updates every second without page refresh

## Authentication

Both the web UI and RTSP stream are password-protected.

- **Web UI** — HTTP Basic Auth (browser will prompt for credentials)
- **RTSP stream** — credentials are embedded in the RTSP URL

Default credentials:

| | Value |
|---|---|
| Username | `admin` |
| Password | `password` |

Change these in [config.py](config.py) (`AUTH_USERNAME` / `AUTH_PASSWORD`) and restart the server. The same credentials are used for both the web UI and RTSP.

## Connecting with VLC

1. Open VLC on your client machine
2. Go to **Media → Open Network Stream** (or `Ctrl+N`)
3. Enter the RTSP URL: `rtsp://admin:password@<pi-ip>:8554/stream`
4. Click **Play**

> **Tip:** To reduce latency in VLC, go to **Tools → Preferences → Input/Codecs** and set **Network caching** to `300` ms.

## Configuration

Edit [config.py](config.py) to change defaults:

| Setting | Default | Description |
|---------|---------|-------------|
| `VIDEO_DEVICE` | `/dev/video0` | Camera device |
| `RESOLUTION_PRESETS` | `720p15`, `480p30` | Available resolution/fps presets |
| `DEFAULT_RESOLUTION` | `720p15` | Resolution preset used on startup |
| `VIDEO_CODEC` | `libx264` | H.264 encoder |
| `PRESET` | `ultrafast` | x264 encoding speed preset |
| `RTSP_PORT` | `8554` | RTSP server port |
| `STATUS_PORT` | `8080` | Web UI HTTPS port |
| `AUTH_USERNAME` | `admin` | Username for web UI and RTSP |
| `AUTH_PASSWORD` | `password` | Password for web UI and RTSP |
| `SSL_CERTFILE` | `cert.pem` | SSL certificate file |
| `SSL_KEYFILE` | `key.pem` | SSL private key file |

## Mobile App (PWA)

The web UI can be installed as a standalone app on your phone.

### Android (Chrome)

1. On the Pi, the SSL certificate must be trusted by your phone. Visit `https://<pi-ip>:8080/cert.pem` on your phone to download it
2. Go to **Settings → Security → Encryption & credentials → Install a certificate → CA certificate** and select the downloaded file
3. Restart Chrome
4. Visit `https://<pi-ip>:8080/` and sign in
5. Chrome will show an "Install app" banner, or use the menu → **Install app**

### iOS (Safari)

1. Visit `https://<pi-ip>:8080/` in Safari and accept the certificate warning
2. Tap **Share → Add to Home Screen**

> **Note:** iOS does not support full PWA install with self-signed certificates, but the home screen shortcut will open in a standalone window.

## Port Forwarding (Remote Access)

To access the stream remotely, forward these ports on your router:

| Port | Protocol | Purpose |
|------|----------|--------|
| `8080` | TCP | Web UI (HTTPS) |
| `8554` | TCP | RTSP stream |

> **Security:** Change the default credentials in [config.py](config.py) before exposing to the internet.

## Troubleshooting

### Camera not found (`/dev/video0` missing)

```bash
# Check if the kernel sees the device
lsusb | grep -i microsoft
# Re-plug the webcam, then check
v4l2-ctl --list-devices
```

### FFmpeg exits immediately

```bash
# Test capture manually
ffmpeg -f v4l2 -input_format mjpeg -video_size 1280x720 -framerate 15 -i /dev/video0 -t 5 test.mp4
```

If the camera doesn't support MJPEG at 720p, try lowering the resolution in [config.py](config.py) or changing `INPUT_FORMAT` to `yuyv422`.

### High CPU usage

The Pi 3B+ should handle 720p @ 15fps with `ultrafast` preset at ~40-50% CPU. If it's too high:

- Lower `FRAMERATE` to `10`
- Lower resolution to `640x480`
- Lower `VIDEO_BITRATE` to `800k`

### VLC shows black screen or won't connect

- Ensure the Pi and client are on the same network
- Check that port `8554` isn't blocked by a firewall: `sudo ufw allow 8554/tcp`
- Try `rtsp://<pi-ip>:8554/stream` in `ffplay` to rule out VLC-specific issues

## License

MIT
