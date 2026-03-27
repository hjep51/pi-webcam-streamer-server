#!/usr/bin/env python3
"""Pi Webcam RTSP Streamer — streams a USB webcam over RTSP via mediamtx + FFmpeg."""

import argparse
import html
import json
import os
import re
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
        self.resolution = config.DEFAULT_RESOLUTION
        self._mediamtx_proc: subprocess.Popen | None = None
        self._ffmpeg_proc: subprocess.Popen | None = None
        self._start_time: float | None = None

    # -- public API --

    @property
    def preset(self) -> dict:
        return config.RESOLUTION_PRESETS[self.resolution]

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

    @property
    def resolution_label(self) -> str:
        p = self.preset
        return f"{p['width']}x{p['height']} @ {p['fps']} fps"

    def set_resolution(self, key: str) -> str | None:
        """Change resolution preset. Only allowed while stopped."""
        if self.is_running:
            return "Stop the stream before changing resolution."
        if key not in config.RESOLUTION_PRESETS:
            return f"Unknown resolution: {key}"
        self.resolution = key
        return None

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

        # Start FFmpeg using current resolution preset
        p = self.preset
        rtsp_target = f"rtsp://localhost:{config.RTSP_PORT}/{config.STREAM_NAME}"
        ffmpeg_cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "warning",
            # Input
            "-f", "v4l2",
            "-input_format", config.INPUT_FORMAT,
            "-video_size", f"{p['width']}x{p['height']}",
            "-framerate", str(p["fps"]),
            "-i", self.device,
            # Encoding
            "-c:v", config.VIDEO_CODEC,
            "-preset", config.PRESET,
            "-tune", config.TUNE,
            "-b:v", p["bitrate"],
            "-g", str(p["keyframe_interval"]),
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
# Camera V4L2 controls
# ---------------------------------------------------------------------------

class CameraControls:
    """Read/write V4L2 camera controls (brightness, focus) via v4l2-ctl."""

    # Maps our UI name → substring to match in v4l2-ctl output.
    # The actual V4L2 control name is parsed from the output at runtime
    # (e.g. "focus_auto" matches "focus_automatic_continuous").
    MATCH_PATTERNS = {
        "brightness": "brightness",
        "focus_absolute": "focus_absolute",
        "focus_auto": "focus_auto",
    }

    def __init__(self, device: str):
        self.device = device
        self._ranges: dict[str, dict] | None = None
        self._v4l2_names: dict[str, str] = {}  # UI name → actual V4L2 control name

    def _parse_ctrls_output(self) -> list[str]:
        """Run v4l2-ctl --list-ctrls and return output lines."""
        try:
            out = subprocess.run(
                ["v4l2-ctl", "-d", self.device, "--list-ctrls"],
                capture_output=True, text=True, timeout=5,
            )
            return out.stdout.splitlines()
        except (OSError, subprocess.TimeoutExpired):
            return []

    @staticmethod
    def _parse_ctrl_name(line: str) -> str | None:
        """Extract the V4L2 control name from a --list-ctrls output line."""
        # Lines look like: "          brightness 0x00980900 (int)  : min=0 ..."
        m = re.match(r"\s*(\w+)\s+0x", line)
        return m.group(1) if m else None

    def query_ranges(self) -> dict[str, dict]:
        """Return {name: {min, max, step, default, value}} for each supported control."""
        if self._ranges is not None:
            return self._ranges

        result: dict[str, dict] = {}
        self._v4l2_names = {}

        for line in self._parse_ctrls_output():
            for ui_name, pattern in self.MATCH_PATTERNS.items():
                if pattern not in line:
                    continue
                actual_name = self._parse_ctrl_name(line)
                if actual_name:
                    self._v4l2_names[ui_name] = actual_name
                nums = dict(re.findall(r"(min|max|step|default|value)=([-\d]+)", line))
                if nums:
                    result[ui_name] = {k: int(v) for k, v in nums.items()}
        self._ranges = result
        return result

    def get_values(self) -> dict[str, int]:
        """Return current values for all supported controls."""
        values: dict[str, int] = {}
        for line in self._parse_ctrls_output():
            for ui_name, pattern in self.MATCH_PATTERNS.items():
                if pattern not in line:
                    continue
                m = re.search(r"value=([-\d]+)", line)
                if m:
                    values[ui_name] = int(m.group(1))
        return values

    def set_value(self, name: str, value: int) -> str | None:
        """Set a single control. Returns error string or None on success."""
        if name not in self.MATCH_PATTERNS:
            return f"Unknown control: {name}"

        ranges = self.query_ranges()
        info = ranges.get(name)
        if info is None:
            return f"Control {name} not supported by this camera"

        if "min" in info and "max" in info:
            value = max(info["min"], min(info["max"], value))

        # Use the actual V4L2 control name discovered from the device
        v4l2_name = self._v4l2_names.get(name)
        if not v4l2_name:
            return f"Could not determine V4L2 name for {name}"

        try:
            proc = subprocess.run(
                ["v4l2-ctl", "-d", self.device, "--set-ctrl", f"{v4l2_name}={value}"],
                capture_output=True, text=True, timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return str(exc)

        if proc.returncode != 0:
            return proc.stderr.strip() or f"v4l2-ctl exited with code {proc.returncode}"

        # Invalidate cached ranges so next read picks up the new value
        self._ranges = None
        return None


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


def make_handler(manager: StreamManager, cam_controls: CameraControls):
    """Factory that returns a request handler class bound to *manager*."""

    template = TEMPLATE_PATH.read_text()
    local_ip = _get_local_ip()

    class Handler(BaseHTTPRequestHandler):

        def do_GET(self):
            if self.path == "/api/controls":
                self._handle_get_controls()
                return
            if self.path == "/api/resolution":
                self._handle_get_resolution()
                return

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
                .replace("{{resolution}}", html.escape(manager.resolution_label))
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
            elif self.path == "/api/controls":
                self._handle_set_controls()
                return
            elif self.path == "/api/resolution":
                self._handle_set_resolution()
                return
            else:
                self.send_error(404)
                return

            # Redirect back to status page
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()

        # -- Resolution API --

        def _handle_get_resolution(self):
            presets = {}
            for key, p in config.RESOLUTION_PRESETS.items():
                presets[key] = f"{p['width']}x{p['height']} @ {p['fps']} fps"
            self._send_json(200, {
                "current": manager.resolution,
                "presets": presets,
                "locked": manager.is_running,
            })

        def _handle_set_resolution(self):
            length = int(self.headers.get("Content-Length", 0))
            if length == 0 or length > 1024:
                self._send_json(400, {"error": "Invalid request body"})
                return
            try:
                body = json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, ValueError):
                self._send_json(400, {"error": "Invalid JSON"})
                return
            key = body.get("resolution") if isinstance(body, dict) else None
            if not isinstance(key, str):
                self._send_json(400, {"error": "Missing 'resolution' string"})
                return
            err = manager.set_resolution(key)
            if err:
                self._send_json(400, {"error": err})
            else:
                self._handle_get_resolution()

        # -- Camera controls API --

        def _handle_get_controls(self):
            ranges = cam_controls.query_ranges()
            values = cam_controls.get_values()
            payload = {}
            for name, info in ranges.items():
                payload[name] = {**info, "value": values.get(name, info.get("value", 0))}
            self._send_json(200, payload)

        def _handle_set_controls(self):
            length = int(self.headers.get("Content-Length", 0))
            if length == 0 or length > 4096:
                self._send_json(400, {"error": "Invalid request body"})
                return
            try:
                body = json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, ValueError):
                self._send_json(400, {"error": "Invalid JSON"})
                return

            if not isinstance(body, dict):
                self._send_json(400, {"error": "Expected JSON object"})
                return

            errors = {}
            for name, value in body.items():
                if not isinstance(value, int):
                    errors[name] = "Value must be an integer"
                    continue
                err = cam_controls.set_value(name, value)
                if err:
                    errors[name] = err

            if errors:
                self._send_json(400, {"errors": errors})
            else:
                self._handle_get_controls()

        # -- Helpers --

        def _send_json(self, code: int, data: dict):
            body = json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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
    cam_controls = CameraControls(device=args.device)

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

    httpd = HTTPServer(("0.0.0.0", args.port), make_handler(manager, cam_controls))
    httpd.serve_forever()


if __name__ == "__main__":
    main()
