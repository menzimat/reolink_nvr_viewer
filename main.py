#!/usr/bin/env python3
"""Launch the Reolink NVR multi-channel viewer."""
import argparse
import getpass
import sys
import tkinter as tk
from tkinter import messagebox
from reolink_viewer.config import load_config
from reolink_viewer.credentials import get_keepass_password
from reolink_viewer.reolink_api import ReolinkAPI
from reolink_viewer.gui import ViewerApp

def main():
    parser = argparse.ArgumentParser(description="Reolink NVR multi-channel viewer")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    try:
        cfg = load_config(args.config)
        nvr = cfg["nvr"]
        password = get_keepass_password(
            nvr["keepass_database"], nvr["keepass_entry"],
            nvr.get("keepass_group", "")
        )
        api = ReolinkAPI(
            nvr["host"], nvr.get("http_port", 443), nvr["username"], password,
            https=nvr.get("https", True),
            verify_tls=nvr.get("verify_tls", False)
        )
        api.login()
        channels = api.get_channels()
        if not channels:
            raise RuntimeError("NVR returned no channels.")
        app = ViewerApp(cfg, api, channels, nvr["username"], password)
        app.mainloop()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Reolink NVR Viewer", str(exc))
            root.destroy()
        except Exception:
            pass
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
