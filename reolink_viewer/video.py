"""RTSP worker: OpenCV capture runs off the Tk main thread."""
import cv2
import threading
import time
from urllib.parse import quote

class CameraStream:
    def __init__(self, channel, host, port, username, password, stream="sub",
                 reconnect_seconds=3, open_timeout=8, max_fps=15):
        self.channel = channel
        self.host = host
        self.port = int(port)
        self.username = username
        self.password = password
        self.stream = stream
        self.reconnect_seconds = reconnect_seconds
        self.open_timeout = open_timeout
        self.max_fps = max_fps
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._frame = None
        self._status = "Starting"
        self._thread = None
        user = quote(username, safe="")
        password_q = quote(password, safe="")
        self.url = (
            f"rtsp://{user}:{password_q}@{host}:{self.port}/"
            f"Preview_{channel['rtsp_channel']:02d}_{stream}"
        )

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"RTSP-{self.channel['rtsp_channel']}",
            daemon=True
        )
        self._thread.start()

    def _set_status(self, value):
        with self._lock:
            self._status = value

    def _run(self):
        while not self._stop.is_set():
            cap = None
            try:
                self._set_status("Connecting")
                cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
                if not cap.isOpened():
                    self._set_status("Connection failed; retrying")
                    time.sleep(self.reconnect_seconds)
                    continue
                self._set_status("Live")
                delay = 1.0 / max(1, self.max_fps)
                while not self._stop.is_set():
                    started = time.monotonic()
                    ok, frame = cap.read()
                    if not ok:
                        self._set_status("Stream lost; reconnecting")
                        break
                    with self._lock:
                        self._frame = frame
                    remaining = delay - (time.monotonic() - started)
                    if remaining > 0:
                        self._stop.wait(remaining)
            except Exception as exc:
                self._set_status(f"Error: {exc}")
            finally:
                if cap is not None:
                    cap.release()
            if not self._stop.is_set():
                time.sleep(self.reconnect_seconds)
        self._set_status("Stopped")

    def get_frame(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    @property
    def status(self):
        with self._lock:
            return self._status

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
