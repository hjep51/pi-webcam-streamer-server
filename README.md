# Pi Webcam RTSP Streamer

Stream a USB webcam (Microsoft Lifecam HD-3000) from a Raspberry Pi 3B+ as an RTSP feed that VLC can play over the network.

## Architecture

```
Lifecam HD-3000 (/dev/video0)
        │  V4L2 / MJPEG
        ▼
     FFmpeg  ──RTSP push──▶  mediamtx (:8554)
                                 │
                                 ▼
                            VLC / any RTSP client
                            rtsp://<pi-ip>:8554/stream

  Python orchestrator
   └─ Web status page (:8080)
```

- **mediamtx** — lightweight single-binary RTSP server
- **FFmpeg** — captures from the webcam via V4L2 and transcodes MJPEG → H.264
- **server.py** — manages both processes, serves a web status page

## Prerequisites

- Raspberry Pi 3B+ (or compatible) running Raspberry Pi OS (Bookworm or later)
- Microsoft Lifecam HD-3000 (or any UVC-compatible USB webcam)
- Network connection (wired or Wi-Fi)

## Setup

```bash
# Clone the repo
git clone <repo-url> pi-webcam-streamer-server
cd pi-webcam-streamer-server

# Run the setup script (installs ffmpeg, v4l-utils, downloads mediamtx)
sudo bash setup.sh
```

Verify the camera is detected:

```bash
v4l2-ctl --list-devices
```

You should see the Lifecam HD-3000 listed, typically as `/dev/video0`.

## Usage

```bash
# Start the server (auto-starts the stream)
venv/bin/python server.py
```

The server will print:

```
Starting stream from /dev/video0...
RTSP stream: rtsp://192.168.1.100:8554/stream
Status page: http://192.168.1.100:8080/
Press Ctrl+C to stop.
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--device` | `/dev/video0` | V4L2 camera device path |
| `--port` | `8080` | Status page HTTP port |
| `--no-autostart` | off | Don't start streaming on launch (use the web UI to start) |

### Web Status Page

Open `http://<pi-ip>:8080/` in a browser to see stream status, the RTSP URL, and start/stop controls.

## Connecting with VLC

1. Open VLC on your client machine
2. Go to **Media → Open Network Stream** (or `Ctrl+N`)
3. Enter the RTSP URL: `rtsp://<pi-ip>:8554/stream`
4. Click **Play**

> **Tip:** To reduce latency in VLC, go to **Tools → Preferences → Input/Codecs** and set **Network caching** to `300` ms.

## Configuration

Edit [config.py](config.py) to change defaults:

| Setting | Default | Description |
|---------|---------|-------------|
| `VIDEO_DEVICE` | `/dev/video0` | Camera device |
| `VIDEO_WIDTH` / `VIDEO_HEIGHT` | `1280` / `720` | Capture resolution |
| `FRAMERATE` | `15` | Frames per second |
| `VIDEO_BITRATE` | `1500k` | H.264 encoding bitrate |
| `RTSP_PORT` | `8554` | RTSP server port |
| `STATUS_PORT` | `8080` | Web status page port |

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
