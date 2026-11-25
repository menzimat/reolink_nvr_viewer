"""Persist window geometry, visible channels, and per-pane grid placement."""
import json
from pathlib import Path

class LayoutStore:
    def __init__(self, filename):
        self.path = Path(filename).expanduser()
        self.data = {}

    def load(self):
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.data = {}
        return self.data

    def save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temp.replace(self.path)
