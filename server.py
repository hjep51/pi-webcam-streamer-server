#!/usr/bin/env python3
"""Pi Webcam RTSP Streamer — streams a USB webcam over RTSP via mediamtx + FFmpeg."""

import argparse
import html
import os
import signal
import socket
import subprocess
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from threading import Thread

import config

# ---------------------------------------------------------------------------
# Stream manager
# ---------------------------------------------------------------------------

class StreamManager:
    """Manages mediamtx and FFmpeg subprocesses."""

    def __init__(self, device: str = config.VIDEO_DEVICE):
        self.device = device
        self._mediamtx_proc: subprocess.Popen | None = None
        self._ffmpeg_proc: subprocess.Popen | None = None
        self._start_time: float | None = None

    # -- public API --

    @property
    def is_running(self) -> bool:
        return (
            self._mediamtx_proc is not None
            and self._mediamtx_proc.poll() is None
            and self._ffmpeg_proc is not None
            and self._ffmpeg_proc.poll() is None
        )

    @property
    def uptime(self) -> str:
        if self._start_time is None or not self.is_running:
            return "—"
        elapsed = int(time.time() - self._start_time)
        h, remainder = divmod(elapsed, 3600)
        m, s = divmod(remainder, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def start(self) -> str | None:
        """Start the stream. Returns an error string or None on success."""
        if self.is_running:
            return "Stream is already running."

        # Ensure previous processes are cleaned up
        self.stop()

        project_dir = Path(__file__).resolve().parent
        mediamtx_bin = project_dir / config.MEDIAMTX_BIN
        mediamtx_cfg = project_dir / config.MEDIAMTX_CONFIG
        if not mediamtx_bin.is_file():
            return f"mediamtx binary not found at {mediamtx_bin}. Run setup.sh first."

        if not Path(self.device).exists():
            return f"Camera device {self.device} not found. Is the webcam connected?"

        # Start mediamtx
        try:
            self._mediamtx_proc = subprocess.Popen(
                [str(mediamtx_bin), str(mediamtx_cfg)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            return f"Failed to start mediamtx: {exc}"

        # Give mediamtx a moment to bind its port
        time.sleep(1)
        if self._mediamtx_proc.poll() is not None:
            stderr = self._mediamtx_proc.stderr.read().decode(errors="replace") if self._mediamtx_proc.stderr else ""
            self._mediamtx_proc = None
            return f"mediamtx exited immediately: {stderr[:500]}"

        # Start FFmpeg
        rtsp_target = f"rtsp://localhost:{config.RTSP_PORT}/{config.STREAM_NAME}"
        ffmpeg_cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "warning",
            # Input
            "-f", "v4l2",
            "-input_format", config.INPUT_FORMAT,
            "-video_size", f"{config.VIDEO_WIDTH}x{config.VIDEO_HEIGHT}",
            "-framerate", str(config.FRAMERATE),
            "-i", self.device,
            # Encoding
            "-c:v", config.VIDEO_CODEC,
            "-preset", config.PRESET,
            "-tune", config.TUNE,
            "-b:v", config.VIDEO_BITRATE,
            "-g", str(config.KEYFRAME_INTERVAL),
            # Output
            "-f", "rtsp",
            "-rtsp_transport", "tcp",
            rtsp_target,
        ]

        try:
            self._ffmpeg_proc = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            self._terminate(self._mediamtx_proc)
            self._mediamtx_proc = None
            return f"Failed to start FFmpeg: {exc}"

        # Brief check that FFmpeg didn't die immediately
        time.sleep(1)
        if self._ffmpeg_proc.poll() is not None:
            stderr = self._ffmpeg_proc.stderr.read().decode(errors="replace") if self._ffmpeg_proc.stderr else ""
            self._terminate(self._mediamtx_proc)
            self._mediamtx_proc = None
            self._ffmpeg_proc = None
            return f"FFmpeg exited immediately: {stderr[:500]}"

        self._start_time = time.time()
        return None

    def stop(self):
        """Stop all subprocesses gracefully."""
        self._terminate(self._ffmpeg_proc)
        self._ffmpeg_proc = None
        self._terminate(self._mediamtx_proc)
        self._mediamtx_proc = None
        self._start_time = None

    # -- helpers --

    @staticmethod
    def _terminate(proc: subprocess.Popen | None):
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)


# ---------------------------------------------------------------------------
# HTTP status page
# ---------------------------------------------------------------------------

TEMPLATE_PATH = Path(__file__).parent / "templates" / "status.html"


def _get_local_ip() -> str:
    """Best-effort detection of the Pi's LAN IP address."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def make_handler(manager: StreamManager):
    """Factory that returns a request handler class bound to *manager*."""

    template = TEMPLATE_PATH.read_text()
    local_ip = _get_local_ip()

    class Handler(BaseHTTPRequestHandler):

        def do_GET(self):
            if self.path != "/":
                self.send_error(404)
                return

            running = manager.is_running
            rtsp_url = f"rtsp://{local_ip}:{config.RTSP_PORT}/{config.STREAM_NAME}"
            body = (
                template
                .replace("{{status_class}}", "running" if running else "stopped")
                .replace("{{status_text}}", "Streaming" if running else "Stopped")
                .replace("{{rtsp_url}}", html.escape(rtsp_url))
                .replace("{{device}}", html.escape(manager.device))
                .replace("{{resolution}}", f"{config.VIDEO_WIDTH}x{config.VIDEO_HEIGHT} @ {config.FRAMERATE} fps")
                .replace("{{uptime}}", html.escape(manager.uptime))
                .replace("{{uptime_class}}", "" if running else "muted")
                .replace("{{start_disabled}}", "disabled" if running else "")
                .replace("{{stop_disabled}}", "" if running else "disabled")
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())

        def do_POST(self):
            if self.path == "/start":
                err = manager.start()
                if err:
                    self._send_plain(500, err)
                    return
            elif self.path == "/stop":
                manager.stop()
            else:
                self.send_error(404)
                return

            # Redirect back to status page
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()

        def _send_plain(self, code: int, message: str):
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(message.encode())

        def log_message(self, fmt, *args):
            # Suppress default access logging
            pass

    return Handler


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Pi Webcam RTSP Streamer")
    parser.add_argument("--device", default=config.VIDEO_DEVICE, help="V4L2 camera device path")
    parser.add_argument("--port", type=int, default=config.STATUS_PORT, help="Status page HTTP port")
    parser.add_argument("--no-autostart", action="store_true", help="Don't start streaming automatically on launch")
    args = parser.parse_args()

    manager = StreamManager(device=args.device)

    # Graceful shutdown
    def shutdown(signum, frame):
        print("\nShutting down...")
        manager.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Auto-start the stream unless told not to
    if not args.no_autostart:
        print(f"Starting stream from {args.device}...")
        err = manager.start()
        if err:
            print(f"Error: {err}", file=sys.stderr)
            sys.exit(1)

    local_ip = _get_local_ip()
    rtsp_url = f"rtsp://{local_ip}:{config.RTSP_PORT}/{config.STREAM_NAME}"
    print(f"RTSP stream: {rtsp_url}")
    print(f"Status page: http://{local_ip}:{args.port}/")
    print("Press Ctrl+C to stop.\n")

    httpd = HTTPServer(("0.0.0.0", args.port), make_handler(manager))
    httpd.serve_forever()


if __name__ == "__main__":
    main()
