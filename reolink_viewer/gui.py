"""Tkinter multi-camera viewer.

Each camera occupies a resizable grid cell. Grid positions and each pane's
requested width/height are persisted. Users can choose any subset of detected
channels using the Channels menu.
"""
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import cv2
from PIL import Image, ImageTk
from .video import CameraStream
from .layout import LayoutStore
from .talkback import Talkback

class CameraPane:
    def __init__(self, app, channel, saved=None, parent=None):
        self.app = app
        self.channel = channel
        self.saved = saved or {}
        self.frame = ttk.Frame(parent or app.video_area, relief="groove", borderwidth=2)
        self.frame.grid_propagate(False)
        self.frame.configure(
            width=int(self.saved.get("width", app.pane_min_width)),
            height=int(self.saved.get("height", app.pane_min_height))
        )
        self.title = ttk.Frame(self.frame)
        self.title.pack(fill="x")
        name = app.channel_label(channel)
        self.name_label = ttk.Label(self.title, text=name, font=("", 10, "bold"))
        self.name_label.pack(side="left", padx=4)
        self.status_label = ttk.Label(self.title, text="Starting")
        self.status_label.pack(side="left", padx=8)
        ttk.Button(self.title, text="Spotlight", command=self.toggle_spotlight).pack(side="right")
        if app.audio_enabled:
            self.talk_button = ttk.Button(self.title, text="Hold to Talk")
            self.talk_button.pack(side="right", padx=3)
            self.talk_button.bind("<ButtonPress-1>", self.talk_start)
            self.talk_button.bind("<ButtonRelease-1>", self.talk_stop)
            self.talk_button.bind("<Leave>", self.talk_stop)
        self.image_label = ttk.Label(self.frame, anchor="center", text="Connecting…")
        self.image_label.pack(fill="both", expand=True)
        self.stream = CameraStream(
            channel, app.host, app.rtsp_port, app.username, app.password,
            stream=app.video_cfg.get("stream", "sub"),
            reconnect_seconds=app.video_cfg.get("reconnect_seconds", 3),
            open_timeout=app.video_cfg.get("open_timeout_seconds", 8),
            max_fps=app.video_cfg.get("max_fps", 15)
        )
        self.stream.start()
        self.spotlight_on = False
        self.talkback = None

    def place(self, row, column):
        self.frame.grid(row=row, column=column, sticky="nsew", padx=3, pady=3)

    def toggle_spotlight(self):
        enabled = not self.spotlight_on
        def work():
            try:
                self.app.api.set_spotlight(self.channel["index"], enabled)
                self.spotlight_on = enabled
                self.app.after(0, lambda: self.status_label.config(
                    text=f"{self.stream.status} | Light {'ON' if enabled else 'OFF'}"
                ))
            except Exception as exc:
                self.app.after(0, lambda: messagebox.showerror("Spotlight error", str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def talk_start(self, _event=None):
        try:
            self.talkback = Talkback(
                self.app.audio_cfg["command"], self.channel["index"],
                self.app.audio_cfg.get("sample_rate", 16000),
                self.app.audio_cfg.get("channels", 1),
                self.app.audio_cfg.get("blocksize", 320)
            )
            self.talkback.start()
            self.status_label.config(text="TALKING — release to stop")
        except Exception as exc:
            self.talkback = None
            messagebox.showerror("Talkback error", str(exc))

    def talk_stop(self, _event=None):
        if self.talkback:
            self.talkback.stop()
            self.talkback = None
            self.status_label.config(text=self.stream.status)

    def update(self):
        frame = self.stream.get_frame()
        self.status_label.config(text=self.stream.status)
        if frame is not None:
            try:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                target_w = max(100, self.image_label.winfo_width())
                target_h = max(80, self.image_label.winfo_height())
                h, w = rgb.shape[:2]
                scale = min(target_w / w, target_h / h)
                size = (max(1, int(w * scale)), max(1, int(h * scale)))
                image = Image.fromarray(rgb).resize(size, Image.Resampling.BILINEAR)
                photo = ImageTk.PhotoImage(image)
                self.image_label.configure(image=photo, text="")
                self.image_label.image = photo
            except tk.TclError:
                pass

    def save_geometry(self):
        return {
            "width": max(self.frame.winfo_width(), self.frame.winfo_reqwidth()),
            "height": max(self.frame.winfo_height(), self.frame.winfo_reqheight())
        }

    def close(self):
        self.talk_stop()
        self.stream.stop()
        self.frame.destroy()


class ViewerApp(tk.Tk):
    def __init__(self, cfg, api, channels, username, password):
        super().__init__()
        self.cfg, self.api, self.channels = cfg, api, channels
        self.username, self.password = username, password
        self.host = cfg["nvr"]["host"]
        self.rtsp_port = cfg["nvr"].get("rtsp_port", 554)
        self.video_cfg = cfg.get("video", {})
        self.audio_cfg = cfg.get("audio", {})
        self.audio_enabled = bool(self.audio_cfg.get("enabled", False))
        gui = cfg.get("gui", {})
        self.pane_min_width = gui.get("pane_min_width", 240)
        self.pane_min_height = gui.get("pane_min_height", 160)
        self.columns = max(1, int(gui.get("default_columns", 3)))
        self.title(gui.get("title", "Reolink NVR Viewer"))
        self.store = LayoutStore(gui["layout_file"])
        self.saved = self.store.load()
        self.geometry(self.saved.get("window_geometry", gui.get("geometry", "1400x900+80+60")))
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.panes = {}
        self.visible = set(self.saved.get(
            "visible_channels", [c["index"] for c in channels if c["online"]]
        ))
        self._build_menu()
        # Nested Panedwindows provide real draggable splitters: horizontal
        # splitters within each row and vertical splitters between rows.
        self.video_area = ttk.Panedwindow(self, orient=tk.VERTICAL)
        self.video_area.pack(fill="both", expand=True)
        self.pane_rows = []
        self.status = ttk.Label(self, text=f"Found {len(channels)} NVR channels")
        self.status.pack(fill="x", side="bottom")
        self._rebuild_panes()
        self.after(100, self._refresh)

    def channel_label(self, channel):
        custom = self.cfg.get("gui", {}).get("channel_names", {})
        return custom.get(str(channel["rtsp_channel"]), channel["name"])

    def _build_menu(self):
        bar = tk.Menu(self)
        channels_menu = tk.Menu(bar, tearoff=False)
        channels_menu.add_command(label="Show All", command=self.show_all)
        channels_menu.add_command(label="Show Online", command=self.show_online)
        channels_menu.add_separator()
        self.channel_vars = {}
        for channel in self.channels:
            var = tk.BooleanVar(value=channel["index"] in self.visible)
            self.channel_vars[channel["index"]] = var
            channels_menu.add_checkbutton(
                label=f"{channel['rtsp_channel']:02d} - {self.channel_label(channel)}",
                variable=var,
                command=lambda c=channel: self.toggle_channel(c["index"])
            )
        bar.add_cascade(label="Channels", menu=channels_menu)
        layout_menu = tk.Menu(bar, tearoff=False)
        for count in (1, 2, 3, 4):
            layout_menu.add_command(
                label=f"{count} column(s)",
                command=lambda n=count: self.set_columns(n)
            )
        layout_menu.add_command(label="Save Layout Now", command=self.save_layout)
        bar.add_cascade(label="Layout", menu=layout_menu)
        self.config(menu=bar)

    def _rebuild_panes(self):
        for pane in list(self.panes.values()):
            pane.close()
        self.panes.clear()
        for child in self.video_area.winfo_children():
            self.video_area.forget(child)
            child.destroy()
        self.pane_rows = []

        selected = [c for c in self.channels if c["index"] in self.visible]
        saved_panes = self.saved.get("panes", {})
        row_count = (len(selected) + self.columns - 1) // self.columns

        for row_index in range(row_count):
            row_widget = ttk.Panedwindow(self.video_area, orient=tk.HORIZONTAL)
            self.video_area.add(row_widget, weight=1)
            self.pane_rows.append(row_widget)
            row_channels = selected[
                row_index * self.columns:(row_index + 1) * self.columns
            ]
            for col_index, channel in enumerate(row_channels):
                key = str(channel["index"])
                pane = CameraPane(self, channel, saved_panes.get(key, {}), parent=row_widget)
                self.panes[channel["index"]] = pane
                row_widget.add(pane.frame, weight=1)

        # Restore splitter coordinates only after Tk has assigned geometry.
        def restore_sashes():
            for row_index, row_widget in enumerate(self.pane_rows):
                row_channels = selected[
                    row_index * self.columns:(row_index + 1) * self.columns
                ]
                cumulative = 0
                for sash_index, channel in enumerate(row_channels[:-1]):
                    saved = saved_panes.get(str(channel["index"]), {})
                    cumulative += int(saved.get("width", self.pane_min_width))
                    try:
                        row_widget.sashpos(sash_index, cumulative)
                    except tk.TclError:
                        pass
            cumulative_height = 0
            for sash_index, row_channels in enumerate([
                selected[i * self.columns:(i + 1) * self.columns]
                for i in range(row_count)
            ][:-1]):
                row_heights = [
                    int(saved_panes.get(str(c["index"]), {}).get(
                        "height", self.pane_min_height
                    )) for c in row_channels
                ]
                cumulative_height += max(row_heights or [self.pane_min_height])
                try:
                    self.video_area.sashpos(sash_index, cumulative_height)
                except tk.TclError:
                    pass
        self.after(250, restore_sashes)

    def toggle_channel(self, index):
        if index in self.visible:
            self.visible.remove(index)
        else:
            self.visible.add(index)
        self._rebuild_panes()

    def show_all(self):
        self.visible = {c["index"] for c in self.channels}
        for index, var in self.channel_vars.items():
            var.set(index in self.visible)
        self._rebuild_panes()

    def show_online(self):
        self.visible = {c["index"] for c in self.channels if c["online"]}
        for index, var in self.channel_vars.items():
            var.set(index in self.visible)
        self._rebuild_panes()

    def set_columns(self, count):
        self.columns = count
        self.saved["panes"] = {}
        self._rebuild_panes()

    def _refresh(self):
        for pane in list(self.panes.values()):
            pane.update()
        self.after(100, self._refresh)

    def save_layout(self):
        panes = {}
        for position, channel in enumerate(
            c for c in self.channels if c["index"] in self.visible
        ):
            geometry = self.panes[channel["index"]].save_geometry()
            geometry["row"] = position // self.columns
            geometry["column"] = position % self.columns
            panes[str(channel["index"])] = geometry
        self.store.save({
            "window_geometry": self.geometry(),
            "visible_channels": sorted(self.visible),
            "columns": self.columns,
            "panes": panes
        })
        self.status.config(text="Layout saved")

    def on_close(self):
        self.save_layout()
        for pane in list(self.panes.values()):
            pane.close()
        try:
            self.api.logout()
        except Exception:
            pass
        self.destroy()
