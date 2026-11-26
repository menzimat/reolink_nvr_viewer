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
    def __init__(self, app, channel, stream_type, saved=None, parent=None):
        self.app = app
        self.channel = channel
        self.stream_type = stream_type
        self.saved = saved or {}
        self.frame = ttk.Frame(parent or app.video_area, relief="groove", borderwidth=2)
        self.frame.grid_propagate(False)
        self.frame.configure(
            width=int(self.saved.get("width", app.pane_min_width)),
            height=int(self.saved.get("height", app.pane_min_height))
        )
        self.title = ttk.Frame(self.frame)
        self.title.pack(fill="x")
        name = f"{app.channel_label(channel)} ({stream_type})"
        self.name_label = ttk.Label(self.title, text=name, font=("", 10, "bold"))
        self.name_label.pack(side="left", padx=4)
        self.channel_choices = {
            f"{item['rtsp_channel']:02d} - {app.channel_label(item)}": item["index"]
            for item in app.channels if self.stream_type in app.channel_streams(item)
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
            stream=stream_type,
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
            self.app.select_channel(self.key, index, self.stream_type)

    @property
    def key(self):
        return self.app.pane_key(self.channel["index"], self.stream_type)

    def set_channel(self, channel):
        """Replace this pane's stream and controls without disturbing other panes."""
        if self.talkback:
            self.talk_stop()
        self.stream.stop()
        self.channel = channel
        self.name_label.config(text=f"{self.app.channel_label(channel)} ({self.stream_type})")
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
            stream=self.stream_type,
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
        self.cfg, self.api = cfg, api
        self.username, self.password = username, password
        self.host = cfg["nvr"]["host"]
        self.rtsp_port = cfg["nvr"].get("rtsp_port", 554)
        self.video_cfg = cfg.get("video", {})
        self.audio_cfg = cfg.get("audio", {})
        self.audio_enabled = bool(self.audio_cfg.get("enabled", False))
        gui = cfg.get("gui", {})
        excluded = {int(n) for n in gui.get("excluded_channels", [])}
        self.channels = [c for c in channels if c["rtsp_channel"] not in excluded]
        self.channel_config = {
            int(number): value for number, value in gui.get("channels", {}).items()
        }
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
        self.channel_indexes = {c["index"] for c in self.channels}
        self.stream_specs = [
            (c["index"], stream) for c in self.channels
            for stream in self.channel_streams(c)
        ]
        valid_keys = {self.pane_key(*spec) for spec in self.stream_specs}
        self.saved["panes"] = self._normalize_saved_panes(
            self.saved.get("panes", {}), valid_keys
        )
        default_visible = [self.pane_key(c["index"], s)
                           for c in self.channels if c["online"]
                           for s in self.channel_streams(c)]
        # Read current format and migrate older channel-only layout files.
        saved_visible = self.saved.get("visible_panes")
        if saved_visible is None:
            legacy = set(self.saved.get("visible_channels", [
                c["index"] for c in self.channels if c["online"]
            ]))
            saved_visible = [self.pane_key(i, s) for i, s in self.stream_specs
                             if i in legacy]
        else:
            saved_visible = [self._normalize_saved_key(key, valid_keys)
                             for key in saved_visible]
            saved_visible = list(dict.fromkeys(
                key for key in saved_visible if key is not None
            ))
            saved_set = set(saved_visible)
            # Newly configured stream panes join channels already visible in
            # an older saved layout, without resetting the user's selection.
            for channel in self.channels:
                channel_keys = [self.pane_key(channel["index"], s)
                                for s in self.channel_streams(channel)]
                if any(key in saved_set for key in channel_keys):
                    saved_visible.extend(key for key in channel_keys if key not in saved_set)
                    saved_set.update(channel_keys)
        self.visible = set(saved_visible) & valid_keys
        saved_order = self.saved.get("display_order_panes")
        if saved_order is None:
            legacy_order = self.saved.get("display_order", [])
            saved_order = [self.pane_key(i, s) for i in legacy_order
                           for ci, s in self.stream_specs if ci == i]
        else:
            saved_order = [self._normalize_saved_key(key, valid_keys)
                           for key in saved_order]
            saved_order = list(dict.fromkeys(
                key for key in saved_order if key is not None
            ))
        self.display_order = [k for k in saved_order if k in self.visible]
        self.display_order.extend(k for k in default_visible
                                  if k in self.visible and k not in self.display_order)
        self._build_menu()
        # Nested Panedwindows provide real draggable splitters: horizontal
        # splitters within each row and vertical splitters between rows.
        self.video_area = ttk.Panedwindow(self, orient=tk.VERTICAL)
        self.video_area.pack(fill="both", expand=True)
        self.pane_rows = []
        self.status = ttk.Label(self, text=f"Found {len(self.channels)} available NVR channels")
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

    def pane_key(self, index, stream):
        return f"{index}:{stream}"

    def _normalize_saved_key(self, key, valid_keys):
        """Keep saved panes when a channel's configured stream type changed."""
        if not isinstance(key, str):
            return None
        if key in valid_keys:
            return key
        try:
            index_text, _old_stream = key.split(":", 1)
            index = int(index_text)
        except (ValueError, TypeError):
            return None
        channel = next((c for c in self.channels if c["index"] == index), None)
        if channel is None:
            return None
        options = self.channel_streams(channel)
        preferred = self.video_cfg.get("stream", "sub")
        stream = preferred if preferred in options else options[0]
        return self.pane_key(index, stream)

    def _normalize_saved_panes(self, panes, valid_keys):
        """Migrate pane geometry from old stream-specific keys when possible."""
        if not isinstance(panes, dict):
            return {}
        normalized = {key: value for key, value in panes.items()
                      if key in valid_keys}
        for key, value in panes.items():
            target = self._normalize_saved_key(key, valid_keys)
            if target is not None and target not in normalized:
                normalized[target] = value
        return normalized

    def channel_streams(self, channel):
        setting = self.channel_config.get(channel["rtsp_channel"], {})
        streams = setting.get("streams") if isinstance(setting, dict) else None
        streams = streams or [self.video_cfg.get("stream", "sub")]
        return list(dict.fromkeys(s for s in streams if s in ("main", "sub"))) or ["sub"]

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
            var = tk.BooleanVar(value=any(self.pane_key(channel["index"], s) in self.visible
                                          for s in self.channel_streams(channel)))
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

        selected = [(self.channel_by_index(int(k.split(":", 1)[0])), k.split(":", 1)[1])
                    for k in self.display_order]
        saved_panes = self.saved.get("panes", {})
        row_count = (len(selected) + self.columns - 1) // self.columns

        for row_index in range(row_count):
            row_widget = ttk.Panedwindow(self.video_area, orient=tk.HORIZONTAL)
            self.video_area.add(row_widget, weight=1)
            self.pane_rows.append(row_widget)
            row_specs = selected[
                row_index * self.columns:(row_index + 1) * self.columns
            ]
            for col_index, (channel, stream) in enumerate(row_specs):
                key = self.pane_key(channel["index"], stream)
                pane = CameraPane(self, channel, stream, saved_panes.get(key, {}), parent=row_widget)
                self.panes[key] = pane
                row_widget.add(pane.frame, weight=1)

        # Restore splitter coordinates only after Tk has assigned geometry.
        def restore_sashes():
            saved_row_sashes = self.saved.get("row_sashes", [])
            for row_index, row_widget in enumerate(self.pane_rows):
                row_specs = selected[
                    row_index * self.columns:(row_index + 1) * self.columns
                ]
                for sash_index, (channel, stream) in enumerate(row_specs[:-1]):
                    if (row_index < len(saved_row_sashes)
                            and sash_index < len(saved_row_sashes[row_index])):
                        position = int(saved_row_sashes[row_index][sash_index])
                    else:
                        position = sum(
                            int(saved_panes.get(self.pane_key(item[0]["index"], item[1]), {}).get(
                                "width", self.pane_min_width
                            )) for item in row_specs[:sash_index + 1]
                        )
                    try:
                        row_widget.sashpos(sash_index, position)
                    except tk.TclError:
                        pass
            saved_vertical_sashes = self.saved.get("vertical_sashes", [])
            for sash_index, row_specs in enumerate([
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
                        int(saved_panes.get(self.pane_key(c[0]["index"], c[1]), {}).get(
                            "height", self.pane_min_height
                        )) for c in prior_row
                    ] or [self.pane_min_height]) for prior_row in prior_rows)
                try:
                    self.video_area.sashpos(sash_index, position)
                except tk.TclError:
                    pass
        self.after(250, restore_sashes)

    def toggle_channel(self, index):
        keys = [self.pane_key(index, s) for s in self.channel_streams(self.channel_by_index(index))]
        if any(key in self.visible for key in keys):
            self.visible.difference_update(keys)
            self.display_order = [key for key in self.display_order if key not in keys]
        else:
            self.visible.update(keys)
            self.display_order.extend(key for key in keys if key not in self.display_order)
        self._rebuild_panes()

    def channel_by_index(self, index):
        return next(channel for channel in self.channels if channel["index"] == index)

    def select_channel(self, current_key, selected_index, stream):
        new_key = self.pane_key(selected_index, stream)
        if current_key not in self.panes or current_key == new_key:
            return
        current_pane = self.panes[current_key]
        affected_indexes = {current_pane.channel["index"], selected_index}
        if new_key in self.visible:
            other_pane = self.panes[new_key]
            current_channel = current_pane.channel
            selected_channel = other_pane.channel
            # Preserve the two widget trees and their splitter positions;
            # only restart the streams in the panes whose assignments changed.
            current_pane.set_channel(selected_channel)
            other_pane.set_channel(current_channel)
            old_position = self.display_order.index(current_key)
            other_position = self.display_order.index(new_key)
            self.display_order[old_position], self.display_order[other_position] = (
                new_key, current_key
            )
            self.panes[current_key], self.panes[new_key] = other_pane, current_pane
        else:
            channel = self.channel_by_index(selected_index)
            current_pane.set_channel(channel)
            position = self.display_order.index(current_key)
            self.display_order[position] = new_key
            self.visible.discard(current_key)
            self.visible.add(new_key)
            self.panes.pop(current_key)
            self.panes[new_key] = current_pane
        for index in affected_indexes:
            var = self.channel_vars.get(index)
            if var is not None:
                var.set(any(self.pane_key(index, s) in self.visible
                            for s in self.channel_streams(self.channel_by_index(index))))

    def show_all(self):
        self.display_order = [self.pane_key(i, s) for i, s in self.stream_specs]
        self.visible = set(self.display_order)
        for index, var in self.channel_vars.items():
            var.set(any(self.pane_key(index, s) in self.visible
                        for s in self.channel_streams(self.channel_by_index(index))))
        self._rebuild_panes()

    def show_online(self):
        self.display_order = [self.pane_key(c["index"], s) for c in self.channels if c["online"]
                              for s in self.channel_streams(c)]
        self.visible = set(self.display_order)
        for index, var in self.channel_vars.items():
            var.set(any(self.pane_key(index, s) in self.visible
                        for s in self.channel_streams(self.channel_by_index(index))))
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
        for position, key in enumerate(self.display_order):
            geometry = self.panes[key].save_geometry()
            geometry["row"] = position // self.columns
            geometry["column"] = position % self.columns
            panes[key] = geometry
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
            "visible_panes": [key for key in self.display_order if key in self.visible],
            "display_order_panes": list(self.display_order),
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
