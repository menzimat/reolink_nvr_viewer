"""Small, explicit Reolink CGI API client for NVR discovery and spotlight.

Video is intentionally handled by RTSP/OpenCV. The HTTP API is used for
channel inventory and white-LED/spotlight state. All channel numbers in this
module are zero-based (the convention used in CGI command payloads).
"""
import requests
from requests.auth import HTTPDigestAuth

class ReolinkAPIError(RuntimeError):
    pass

class ReolinkAPI:
    def __init__(self, host, port, username, password, https=True,
                 verify_tls=False, timeout=8):
        scheme = "https" if https else "http"
        self.base = f"{scheme}://{host}:{port}"
        self.username = username
        self.password = password
        self.verify_tls = verify_tls
        self.timeout = timeout
        self.session = requests.Session()
        self.session.auth = HTTPDigestAuth(username, password)
        self.session.verify = verify_tls
        self.token = None

    def _post(self, command, payload):
        url = f"{self.base}/api.cgi?cmd={command}"
        if self.token:
            url += f"&token={self.token}"
        try:
            response = self.session.post(
                url, json=payload, timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            raise ReolinkAPIError(f"{command} request failed: {exc}") from exc
        if not isinstance(data, list) or not data:
            raise ReolinkAPIError(f"Unexpected response to {command}: {data!r}")
        item = data[0]
        if item.get("code", 0) not in (0, "0"):
            raise ReolinkAPIError(
                f"{command} failed (code {item.get('code')}): {item}"
            )
        return item

    def login(self):
        payload = [{
            "cmd": "Login", "action": 0,
            "param": {"User": {
                "userName": self.username, "password": self.password
            }}
        }]
        item = self._post("Login", payload)
        self.token = item.get("value", {}).get("Token", {}).get("name")
        if not self.token:
            raise ReolinkAPIError("Login response did not contain an API token.")

    def logout(self):
        if not self.token:
            return
        try:
            self._post("Logout", [{"cmd": "Logout", "action": 0, "param": {}}])
        finally:
            self.token = None

    def _ensure_login(self):
        if not self.token:
            self.login()

    def get_channels(self):
        self._ensure_login()
        item = self._post("GetChannelstatus", [{
            "cmd": "GetChannelstatus", "action": 0, "param": {}
        }])
        value = item.get("value", {})
        statuses = value.get("status", [])
        channels = []
        for index, status in enumerate(statuses):
            # CGI inventory is zero-based. RTSP path channel is index + 1.
            online = bool(status.get("online", 0))
            name = status.get("name") or status.get("channelName") or f"Channel {index + 1}"
            channels.append({
                "index": index,
                "rtsp_channel": index + 1,
                "name": name,
                "online": online,
                "raw": status,
            })
        return channels

    def get_spotlight(self, channel_index):
        self._ensure_login()
        item = self._post("GetWhiteLed", [{
            "cmd": "GetWhiteLed", "action": 1,
            "param": {"channel": channel_index}
        }])
        led = item.get("value", {}).get("WhiteLed")
        if not led:
            raise ReolinkAPIError("NVR did not return WhiteLed settings for this channel.")
        return bool(int(led.get("state", 0)))

    def set_spotlight(self, channel_index, enabled):
        self._ensure_login()
        # Read current settings first so mode/brightness/schedule are preserved.
        item = self._post("GetWhiteLed", [{
            "cmd": "GetWhiteLed", "action": 1,
            "param": {"channel": channel_index}
        }])
        led = item.get("value", {}).get("WhiteLed")
        if not led:
            raise ReolinkAPIError("NVR did not return WhiteLed settings for this channel.")
        led["state"] = 1 if enabled else 0
        payload = [{
            "cmd": "SetWhiteLed",
            "param": {"WhiteLed": led}
        }]
        self._post("SetWhiteLed", payload)
        # A successful SetWhiteLed response is the device's acknowledgement.
        # Some NVR firmware returns stale GetWhiteLed settings immediately
        # after a successful update, despite applying the change to the light.
        return bool(enabled)
