"""Configuration constants for the Pi webcam RTSP streamer."""

# Camera
VIDEO_DEVICE = "/dev/video0"
VIDEO_WIDTH = 1280
VIDEO_HEIGHT = 720
FRAMERATE = 15
INPUT_FORMAT = "mjpeg"  # Lifecam HD-3000 outputs MJPEG natively

# Encoding
VIDEO_CODEC = "libx264"
VIDEO_BITRATE = "1500k"
PRESET = "ultrafast"
TUNE = "zerolatency"
KEYFRAME_INTERVAL = 30  # 1 keyframe every 2s at 15fps

# RTSP (mediamtx)
RTSP_PORT = 8554
STREAM_NAME = "stream"
MEDIAMTX_BIN = "mediamtx"
MEDIAMTX_CONFIG = "mediamtx.yml"

# Status page
STATUS_PORT = 8080
