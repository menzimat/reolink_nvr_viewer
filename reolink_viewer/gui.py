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
        self.channel_choices = {
            f"{item['rtsp_channel']:02d} - {app.channel_label(item)}": item["index"]
            for item in app.channels
        }
        self.channel_choice = tk.StringVar(value=app.channel_choice_label(channel))
        self.channel_menu = ttk.Combobox(
            self.title, textvariable=self.channel_choice,
            values=list(self.channel_choices), state="readonly", width=22
        )
        self.channel_menu.configure(foreground="black")
        self.channel_menu.pack(side="left", padx=4)
        self.channel_menu.bind("<<ComboboxSelected>>", self._select_channel)
        self.status_label = ttk.Label(self.title, text="Starting")
        self.status_label.pack(side="left", padx=8)
        self.spotlight_button = ttk.Button(
            self.title, text="Spotlight OFF", command=self.toggle_spotlight
        )
        self.spotlight_button.state(["disabled"])
        self.spotlight_button.pack(side="right")
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
        threading.Thread(target=self._load_spotlight_state, daemon=True).start()

    def _select_channel(self, _event=None):
        index = self.channel_choices.get(self.channel_choice.get())
        if index is not None and index != self.channel["index"]:
            self.app.select_channel(self.channel["index"], index)

    def set_channel(self, channel):
        """Replace this pane's stream and controls without disturbing other panes."""
        if self.talkback:
            self.talk_stop()
        self.stream.stop()
        self.channel = channel
        self.name_label.config(text=self.app.channel_label(channel))
        self.channel_choice.set(self.app.channel_choice_label(channel))
        self.status_label.config(text="Starting")
        self.image_label.configure(image="", text="Connecting…")
        self.image_label.image = None
        self.spotlight_button.config(text="Spotlight OFF", style="TButton")
        self.spotlight_button.state(["disabled"])
        self.spotlight_on = False
        self.stream = CameraStream(
            channel, self.app.host, self.app.rtsp_port,
            self.app.username, self.app.password,
            stream=self.app.video_cfg.get("stream", "sub"),
            reconnect_seconds=self.app.video_cfg.get("reconnect_seconds", 3),
            open_timeout=self.app.video_cfg.get("open_timeout_seconds", 8),
            max_fps=self.app.video_cfg.get("max_fps", 15)
        )
        self.stream.start()
        threading.Thread(target=self._load_spotlight_state, daemon=True).start()

    def place(self, row, column):
        self.frame.grid(row=row, column=column, sticky="nsew", padx=3, pady=3)

    def toggle_spotlight(self):
        enabled = not self.spotlight_on
        self.spotlight_button.state(["disabled"])
        def work():
            try:
                confirmed = self.app.api.set_spotlight(self.channel["index"], enabled)
                self.app.after(0, lambda: self._set_spotlight_state(confirmed))
            except Exception as exc:
                self.app.after(0, lambda error=exc: self._spotlight_failed(error))
        threading.Thread(target=work, daemon=True).start()

    def _load_spotlight_state(self):
        channel_index = self.channel["index"]
        try:
            enabled = self.app.api.get_spotlight(channel_index)
        except Exception:
            self.app.after(0, lambda: (
                self.spotlight_button.state(["!disabled"])
                if self.channel["index"] == channel_index else None
            ))
            return
        self.app.after(0, lambda: (
            self._set_spotlight_state(enabled)
            if self.channel["index"] == channel_index else None
        ))

    def _set_spotlight_state(self, enabled):
        self.spotlight_on = bool(enabled)
        self.spotlight_button.config(
            text=f"Spotlight {'ON' if self.spotlight_on else 'OFF'}",
            style="SpotlightOn.TButton" if self.spotlight_on else "TButton"
        )
        self.spotlight_button.state(["!disabled"])

    def _spotlight_failed(self, exc):
        self.spotlight_button.state(["!disabled"])
        messagebox.showerror("Spotlight error", str(exc))

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
        self.dark_mode = bool(gui.get("dark_mode", False))
        self._configure_theme()
        self.pane_min_width = gui.get("pane_min_width", 240)
        self.pane_min_height = gui.get("pane_min_height", 160)
        default_columns = max(1, int(gui.get("default_columns", 3)))
        self.title(gui.get("title", "Reolink NVR Viewer"))
        self.store = LayoutStore(gui["layout_file"])
        self.saved = self.store.load()
        self.columns = max(1, int(self.saved.get("columns", default_columns)))
        self.geometry(self.saved.get("window_geometry", gui.get("geometry", "1400x900+80+60")))
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.panes = {}
        channel_indexes = {channel["index"] for channel in channels}
        self.visible = set(self.saved.get(
            "visible_channels", [c["index"] for c in channels if c["online"]]
        )) & channel_indexes
        saved_order = self.saved.get("display_order", [])
        self.display_order = [i for i in saved_order if i in self.visible]
        self.display_order.extend(
            c["index"] for c in channels
            if c["index"] in self.visible and c["index"] not in self.display_order
        )
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

    def _configure_theme(self):
        """Configure ttk colors and optionally apply the dark palette."""
        style = ttk.Style(self)
        # Native ttk themes often ignore per-button background colors. Clam
        # honors the custom yellow Spotlight ON style on all platforms.
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "SpotlightOn.TButton", background="#ffd54f", foreground="#202124"
        )
        style.map("SpotlightOn.TButton", background=[("active", "#ffca28")])
        if not self.dark_mode:
            return
        palette = {
            "background": "#202124",
            "surface": "#292a2d",
            "foreground": "#e8eaed",
            "muted": "#bdc1c6",
            "border": "#5f6368",
        }
        self.configure(background=palette["background"])
        style.configure(".", background=palette["surface"], foreground=palette["foreground"])
        style.configure("TFrame", background=palette["surface"])
        style.configure("TPanedwindow", background=palette["background"])
        style.configure("TLabel", background=palette["surface"], foreground=palette["foreground"])
        style.configure("TButton", background=palette["surface"], foreground=palette["foreground"])
        style.map(
            "TButton",
            background=[("disabled", palette["surface"]), ("active", palette["border"])],
            foreground=[("disabled", palette["muted"])],
        )
        self._menu_colors = {
            "background": palette["surface"], "foreground": palette["foreground"],
            "activebackground": palette["border"], "activeforeground": palette["foreground"],
        }

    def channel_label(self, channel):
        custom = self.cfg.get("gui", {}).get("channel_names", {})
        return custom.get(str(channel["rtsp_channel"]), channel["name"])

    def channel_choice_label(self, channel):
        return f"{channel['rtsp_channel']:02d} - {self.channel_label(channel)}"

    def _build_menu(self):
        menu_options = getattr(self, "_menu_colors", {})
        bar = tk.Menu(self, **menu_options)
        channels_menu = tk.Menu(bar, tearoff=False, **menu_options)
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
        layout_menu = tk.Menu(bar, tearoff=False, **menu_options)
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

        selected = [self.channel_by_index(i) for i in self.display_order]
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
            saved_row_sashes = self.saved.get("row_sashes", [])
            for row_index, row_widget in enumerate(self.pane_rows):
                row_channels = selected[
                    row_index * self.columns:(row_index + 1) * self.columns
                ]
                for sash_index, channel in enumerate(row_channels[:-1]):
                    if (row_index < len(saved_row_sashes)
                            and sash_index < len(saved_row_sashes[row_index])):
                        position = int(saved_row_sashes[row_index][sash_index])
                    else:
                        position = sum(
                            int(saved_panes.get(str(item["index"]), {}).get(
                                "width", self.pane_min_width
                            )) for item in row_channels[:sash_index + 1]
                        )
                    try:
                        row_widget.sashpos(sash_index, position)
                    except tk.TclError:
                        pass
            saved_vertical_sashes = self.saved.get("vertical_sashes", [])
            for sash_index, row_channels in enumerate([
                selected[i * self.columns:(i + 1) * self.columns]
                for i in range(row_count)
            ][:-1]):
                if sash_index < len(saved_vertical_sashes):
                    position = int(saved_vertical_sashes[sash_index])
                else:
                    prior_rows = [
                        selected[i * self.columns:(i + 1) * self.columns]
                        for i in range(sash_index + 1)
                    ]
                    position = sum(max([
                        int(saved_panes.get(str(c["index"]), {}).get(
                            "height", self.pane_min_height
                        )) for c in row
                    ] or [self.pane_min_height]) for row in prior_rows)
                try:
                    self.video_area.sashpos(sash_index, position)
                except tk.TclError:
                    pass
        self.after(250, restore_sashes)

    def toggle_channel(self, index):
        if index in self.visible:
            self.visible.remove(index)
            self.display_order.remove(index)
        else:
            self.visible.add(index)
            self.display_order.append(index)
        self._rebuild_panes()

    def channel_by_index(self, index):
        return next(channel for channel in self.channels if channel["index"] == index)

    def select_channel(self, current_index, selected_index):
        """Change only the pane(s) whose displayed channel assignments change."""
        current_pane = self.panes[current_index]
        current_channel = self.channel_by_index(current_index)
        if selected_index in self.visible:
            selected_pane = self.panes[selected_index]
            selected_channel = self.channel_by_index(selected_index)
            current_pane.set_channel(selected_channel)
            selected_pane.set_channel(current_channel)
            self.panes[current_index], self.panes[selected_index] = (
                selected_pane, current_pane
            )
            current_position = self.display_order.index(current_index)
            selected_position = self.display_order.index(selected_index)
            self.display_order[current_position], self.display_order[selected_position] = (
                self.display_order[selected_position], self.display_order[current_position]
            )
        else:
            current_pane.set_channel(self.channel_by_index(selected_index))
            self.panes.pop(current_index)
            self.panes[selected_index] = current_pane
            position = self.display_order.index(current_index)
            self.display_order[position] = selected_index
            self.visible.remove(current_index)
            self.visible.add(selected_index)
            for channel_index, var in self.channel_vars.items():
                var.set(channel_index in self.visible)

    def show_all(self):
        self.visible = {c["index"] for c in self.channels}
        self.display_order = [c["index"] for c in self.channels]
        for index, var in self.channel_vars.items():
            var.set(index in self.visible)
        self._rebuild_panes()

    def show_online(self):
        self.visible = {c["index"] for c in self.channels if c["online"]}
        self.display_order = [c["index"] for c in self.channels if c["online"]]
        for index, var in self.channel_vars.items():
            var.set(index in self.visible)
        self._rebuild_panes()

    def set_columns(self, count):
        self.columns = count
        self.saved["panes"] = {}
        self.saved["row_sashes"] = []
        self.saved["vertical_sashes"] = []
        self._rebuild_panes()

    def _refresh(self):
        for pane in list(self.panes.values()):
            pane.update()
        self.after(100, self._refresh)

    def save_layout(self):
        panes = {}
        for position, channel in enumerate(self.channel_by_index(i) for i in self.display_order):
            geometry = self.panes[channel["index"]].save_geometry()
            geometry["row"] = position // self.columns
            geometry["column"] = position % self.columns
            panes[str(channel["index"])] = geometry
        row_sashes = []
        for row_widget in self.pane_rows:
            row_sashes.append([
                row_widget.sashpos(index)
                for index in range(max(0, len(row_widget.panes()) - 1))
            ])
        vertical_sashes = [
            self.video_area.sashpos(index)
            for index in range(max(0, len(self.video_area.panes()) - 1))
        ]
        layout = {
            "window_geometry": self.geometry(),
            "visible_channels": sorted(self.visible),
            "display_order": list(self.display_order),
            "columns": self.columns,
            "panes": panes,
            "row_sashes": row_sashes,
            "vertical_sashes": vertical_sashes
        }
        self.store.save(layout)
        self.saved = layout
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
