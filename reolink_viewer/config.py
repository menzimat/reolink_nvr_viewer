"""Configuration loading and path expansion."""
from pathlib import Path
import yaml

def load_config(path="config.yaml"):
    config_path = Path(path).expanduser()
    if not config_path.exists():
        raise FileNotFoundError(
            f"{config_path} not found. Copy config.yaml.example to config.yaml "
            "and edit the NVR/KeePassXC settings."
        )
    with config_path.open("r", encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle) or {}
    cfg.setdefault("nvr", {})
    cfg.setdefault("video", {})
    cfg.setdefault("gui", {})
    cfg.setdefault("audio", {})
    cfg["gui"]["layout_file"] = str(Path(
        cfg["gui"].get("layout_file", "~/.config/reolink-nvr-viewer/layout.json")
    ).expanduser())
    return cfg
