#!/usr/bin/env python3
"""Tkinter control panel for the Cardputer-Adv Windows remote bridge."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import queue
import socket
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from mss import mss

from windows_remote_server import (
    DEFAULT_CONFIG,
    INPUT_BACKEND_CHOICES,
    QUALITY_FILTER_CHOICES,
    ensure_admin,
    is_admin,
    make_server_args,
    run_server,
)


APP_DIR_NAME = "CardputerAdvRemote"
SETTINGS_FILE_NAME = "settings.json"
PRESETS = {
    "Balanced": {"fps": 15.0, "quality_filter": "bilinear"},
    "Fast / Game": {"fps": 30.0, "quality_filter": "nearest"},
    "Stable": {"fps": 8.0, "quality_filter": "bilinear"},
    "Sharp": {"fps": 10.0, "quality_filter": "bicubic"},
}
CUSTOM_PRESET = "Custom"


def config_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_DIR_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_DIR_NAME


def settings_path() -> Path:
    return config_dir() / SETTINGS_FILE_NAME


def load_settings() -> dict[str, object]:
    values = dict(DEFAULT_CONFIG)
    values["preset"] = "Balanced"
    try:
        with settings_path().open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return values
    if isinstance(loaded, dict):
        for key in values:
            if key in loaded:
                values[key] = loaded[key]
    return values


def save_settings(values: dict[str, object]) -> None:
    folder = config_dir()
    folder.mkdir(parents=True, exist_ok=True)
    with settings_path().open("w", encoding="utf-8") as handle:
        json.dump(values, handle, indent=2, sort_keys=True)


def local_ipv4_addresses() -> list[str]:
    addresses: set[str] = set()
    try:
        hostname = socket.gethostname()
        for result in socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_DGRAM):
            address = result[4][0]
            if not address.startswith("127."):
                addresses.add(address)
    except OSError:
        pass

    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            address = probe.getsockname()[0]
            if not address.startswith("127."):
                addresses.add(address)
        finally:
            probe.close()
    except OSError:
        pass

    return sorted(addresses)


def monitor_choices() -> list[str]:
    choices: list[str] = []
    try:
        with mss() as screen:
            for index, monitor in enumerate(screen.monitors):
                label = f"{index}  {monitor['width']}x{monitor['height']}  {monitor['left']},{monitor['top']}"
                if index == 0:
                    label += "  virtual"
                choices.append(label)
    except Exception:
        choices.append(str(DEFAULT_CONFIG["monitor"]))
    return choices


def parse_monitor(value: str) -> int:
    try:
        return int(value.split(maxsplit=1)[0])
    except (ValueError, IndexError):
        return int(DEFAULT_CONFIG["monitor"])


class QueueWriter(io.TextIOBase):
    def __init__(self, log_queue: queue.Queue[tuple[str, str | None]]) -> None:
        super().__init__()
        self.log_queue = log_queue

    def write(self, text: str) -> int:
        if text:
            self.log_queue.put(("log", text))
        return len(text)

    def flush(self) -> None:
        return None


class RemoteGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Cardputer-Adv Remote")
        self.minsize(760, 620)

        self.settings = load_settings()
        self.log_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()
        self.stop_event: threading.Event | None = None
        self.server_thread: threading.Thread | None = None
        self.running = False
        self.closing = False

        self._build_vars()
        self._build_ui()
        self._refresh_ips()
        self._set_running(False)
        self.after(100, self._drain_log_queue)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _build_vars(self) -> None:
        self.preset_var = tk.StringVar(value=str(self.settings.get("preset", "Balanced")))
        self.bind_var = tk.StringVar(value=str(self.settings.get("bind", DEFAULT_CONFIG["bind"])))
        self.local_ip_var = tk.StringVar(value="")
        self.frame_port_var = tk.StringVar(value=str(self.settings.get("frame_port", DEFAULT_CONFIG["frame_port"])))
        self.input_port_var = tk.StringVar(value=str(self.settings.get("input_port", DEFAULT_CONFIG["input_port"])))
        self.width_var = tk.StringVar(value=str(self.settings.get("width", DEFAULT_CONFIG["width"])))
        self.height_var = tk.StringVar(value=str(self.settings.get("height", DEFAULT_CONFIG["height"])))
        self.fps_var = tk.StringVar(value=self._format_float(self.settings.get("fps", DEFAULT_CONFIG["fps"])))
        self.monitor_var = tk.StringVar(value=str(self.settings.get("monitor", DEFAULT_CONFIG["monitor"])))
        self.quality_var = tk.StringVar(value=str(self.settings.get("quality_filter", DEFAULT_CONFIG["quality_filter"])))
        self.backend_var = tk.StringVar(value=str(self.settings.get("input_backend", DEFAULT_CONFIG["input_backend"])))
        self.timeout_var = tk.StringVar(value=self._format_float(self.settings.get("input_timeout", DEFAULT_CONFIG["input_timeout"])))
        self.mouse_hz_var = tk.StringVar(value=self._format_float(self.settings.get("mouse_pump_hz", DEFAULT_CONFIG["mouse_pump_hz"])))
        self.mouse_hold_var = tk.StringVar(value=self._format_float(self.settings.get("mouse_hold_ms", DEFAULT_CONFIG["mouse_hold_ms"])))
        self.mouse_scale_var = tk.StringVar(value=self._format_float(self.settings.get("mouse_scale", DEFAULT_CONFIG["mouse_scale"])))
        self.status_var = tk.StringVar(value="Stopped")
        self.admin_var = tk.StringVar(value=f"Admin: {'yes' if is_admin() else 'no'}")

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        header = ttk.Frame(self, padding=(14, 12, 14, 8))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        title = ttk.Label(header, text="Cardputer-Adv Remote", font=("", 16, "bold"))
        title.grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self.admin_var).grid(row=0, column=1, sticky="e")
        ttk.Label(header, textvariable=self.status_var).grid(row=1, column=0, sticky="w", pady=(4, 0))

        controls = ttk.Frame(self, padding=(14, 0, 14, 10))
        controls.grid(row=1, column=0, sticky="ew")
        controls.columnconfigure(0, weight=1)
        controls.columnconfigure(1, weight=1)

        stream = ttk.LabelFrame(controls, text="Stream")
        stream.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        network = ttk.LabelFrame(controls, text="Network / Input")
        network.grid(row=0, column=1, sticky="nsew", padx=(7, 0))

        for frame in (stream, network):
            frame.columnconfigure(1, weight=1)

        self.preset_combo = self._combo(stream, "Mode", self.preset_var, list(PRESETS) + [CUSTOM_PRESET], 0)
        self.preset_combo.bind("<<ComboboxSelected>>", self._preset_changed)
        self._spin(stream, "FPS", self.fps_var, 1, 60, 1, 1)
        self.monitor_combo = self._combo(stream, "Monitor", self.monitor_var, monitor_choices(), 2)
        self._combo(stream, "Quality", self.quality_var, list(QUALITY_FILTER_CHOICES), 3)
        self._spin(stream, "Width", self.width_var, 80, 480, 1, 4)
        self._spin(stream, "Height", self.height_var, 45, 320, 1, 5)

        self._entry(network, "Bind IP", self.bind_var, 0)
        ip_row = ttk.Frame(network)
        ip_row.grid(row=1, column=1, sticky="ew", padx=(6, 8), pady=4)
        ip_row.columnconfigure(0, weight=1)
        self.ip_combo = ttk.Combobox(ip_row, textvariable=self.local_ip_var, state="readonly", values=())
        self.ip_combo.grid(row=0, column=0, sticky="ew")
        self.refresh_button = ttk.Button(ip_row, text="Refresh", command=self._refresh_ips)
        self.refresh_button.grid(row=0, column=1, padx=(6, 0))
        ttk.Label(network, text="PC IP").grid(row=1, column=0, sticky="w", padx=(8, 0), pady=4)

        self._spin(network, "Frame port", self.frame_port_var, 1, 65535, 1, 2)
        self._spin(network, "Input port", self.input_port_var, 1, 65535, 1, 3)
        self._combo(network, "Input", self.backend_var, list(INPUT_BACKEND_CHOICES), 4)
        self._spin(network, "Timeout", self.timeout_var, 1, 30, 0.5, 5)
        self._spin(network, "Mouse Hz", self.mouse_hz_var, 30, 240, 10, 6)
        self._spin(network, "Hold ms", self.mouse_hold_var, 20, 200, 5, 7)
        self._spin(network, "Mouse scale", self.mouse_scale_var, 0.1, 5.0, 0.1, 8)

        buttons = ttk.Frame(network)
        buttons.grid(row=9, column=0, columnspan=2, sticky="ew", padx=8, pady=(10, 8))
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        self.start_button = ttk.Button(buttons, text="Start", command=self._start)
        self.start_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.stop_button = ttk.Button(buttons, text="Stop", command=self._stop)
        self.stop_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        log_frame = ttk.LabelFrame(self, text="Log", padding=(10, 8, 10, 10))
        log_frame.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 14))
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, height=12, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scroll.set)

    def _entry(self, parent: ttk.Frame, label: str, variable: tk.StringVar, row: int) -> ttk.Entry:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(8, 0), pady=4)
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, sticky="ew", padx=(6, 8), pady=4)
        return entry

    def _spin(
        self,
        parent: ttk.Frame,
        label: str,
        variable: tk.StringVar,
        from_: float,
        to: float,
        increment: float,
        row: int,
    ) -> ttk.Spinbox:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(8, 0), pady=4)
        spin = ttk.Spinbox(parent, textvariable=variable, from_=from_, to=to, increment=increment)
        spin.grid(row=row, column=1, sticky="ew", padx=(6, 8), pady=4)
        return spin

    def _combo(
        self,
        parent: ttk.Frame,
        label: str,
        variable: tk.StringVar,
        values: list[str],
        row: int,
    ) -> ttk.Combobox:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(8, 0), pady=4)
        combo = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly")
        if variable.get() not in values and values:
            monitor = str(variable.get())
            match = next((choice for choice in values if choice.split(maxsplit=1)[0] == monitor), values[0])
            variable.set(match)
        combo.grid(row=row, column=1, sticky="ew", padx=(6, 8), pady=4)
        return combo

    def _refresh_ips(self) -> None:
        addresses = local_ipv4_addresses()
        self.ip_combo.configure(values=addresses)
        self.local_ip_var.set(addresses[0] if addresses else "No LAN IPv4 found")

    def _preset_changed(self, _event: object | None = None) -> None:
        preset = self.preset_var.get()
        values = PRESETS.get(preset)
        if not values:
            return
        self.fps_var.set(self._format_float(values["fps"]))
        self.quality_var.set(str(values["quality_filter"]))

    def _snapshot(self) -> dict[str, object]:
        return {
            "preset": self.preset_var.get(),
            "bind": self.bind_var.get().strip() or str(DEFAULT_CONFIG["bind"]),
            "frame_port": self._int_value(self.frame_port_var, "Frame port", 1, 65535),
            "input_port": self._int_value(self.input_port_var, "Input port", 1, 65535),
            "width": self._int_value(self.width_var, "Width", 1, 4096),
            "height": self._int_value(self.height_var, "Height", 1, 4096),
            "fps": self._float_value(self.fps_var, "FPS", 0.1, 120.0),
            "monitor": parse_monitor(self.monitor_var.get()),
            "quality_filter": self.quality_var.get(),
            "input_timeout": self._float_value(self.timeout_var, "Timeout", 0.5, 120.0),
            "input_backend": self.backend_var.get(),
            "mouse_pump_hz": self._float_value(self.mouse_hz_var, "Mouse Hz", 1.0, 500.0),
            "mouse_hold_ms": self._float_value(self.mouse_hold_var, "Hold ms", 1.0, 1000.0),
            "mouse_scale": self._float_value(self.mouse_scale_var, "Mouse scale", 0.05, 20.0),
            "no_admin_relaunch": False,
        }

    def _start(self) -> None:
        if self.running:
            return
        try:
            values = self._snapshot()
            save_settings(values)
        except ValueError as exc:
            messagebox.showerror("Invalid setting", str(exc), parent=self)
            return
        except OSError as exc:
            messagebox.showerror("Settings", f"Could not save settings:\n{exc}", parent=self)
            return

        self.stop_event = threading.Event()
        args = make_server_args(**values)
        self._append_log(f"Settings saved to {settings_path()}\n")
        self.server_thread = threading.Thread(target=self._server_main, args=(args, self.stop_event), daemon=True)
        self.server_thread.start()
        self._set_running(True)

    def _stop(self) -> None:
        if self.stop_event is not None:
            self.stop_event.set()
        self.status_var.set("Stopping")

    def _server_main(self, args: argparse.Namespace, stop_event: threading.Event) -> None:
        writer = QueueWriter(self.log_queue)
        try:
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                run_server(args, stop_event)
        except Exception as exc:
            self.log_queue.put(("log", f"\nERROR: {exc}\n"))
        finally:
            self.log_queue.put(("stopped", None))

    def _drain_log_queue(self) -> None:
        try:
            while True:
                kind, payload = self.log_queue.get_nowait()
                if kind == "log" and payload is not None:
                    self._append_log(payload)
                elif kind == "stopped":
                    self._set_running(False)
                    if self.closing:
                        self.destroy()
                        return
        except queue.Empty:
            pass
        self.after(100, self._drain_log_queue)

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_running(self, running: bool) -> None:
        self.running = running
        self.status_var.set("Running" if running else "Stopped")
        self.start_button.configure(state="disabled" if running else "normal")
        self.stop_button.configure(state="normal" if running else "disabled")
        for widget in self._config_widgets():
            if isinstance(widget, ttk.Combobox):
                widget.configure(state="disabled" if running else "readonly")
            else:
                widget.configure(state="disabled" if running else "normal")
        self.ip_combo.configure(state="disabled" if running else "readonly")
        self.refresh_button.configure(state="disabled" if running else "normal")

    def _config_widgets(self) -> list[tk.Widget]:
        widgets: list[tk.Widget] = []
        for child in self.winfo_children():
            widgets.extend(self._walk_widgets(child))
        return [
            widget
            for widget in widgets
            if isinstance(widget, (ttk.Entry, ttk.Spinbox, ttk.Combobox)) and widget is not self.ip_combo
        ]

    def _walk_widgets(self, widget: tk.Widget) -> list[tk.Widget]:
        found = [widget]
        for child in widget.winfo_children():
            found.extend(self._walk_widgets(child))
        return found

    def _close(self) -> None:
        if self.running and self.stop_event is not None:
            self.closing = True
            self._stop()
            self.after(1500, self.destroy)
            return
        self.destroy()

    @staticmethod
    def _format_float(value: object) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = 0.0
        if number.is_integer():
            return str(int(number))
        return f"{number:g}"

    @staticmethod
    def _int_value(variable: tk.StringVar, label: str, minimum: int, maximum: int) -> int:
        try:
            value = int(variable.get())
        except ValueError as exc:
            raise ValueError(f"{label} must be a number.") from exc
        if not minimum <= value <= maximum:
            raise ValueError(f"{label} must be between {minimum} and {maximum}.")
        return value

    @staticmethod
    def _float_value(variable: tk.StringVar, label: str, minimum: float, maximum: float) -> float:
        try:
            value = float(variable.get())
        except ValueError as exc:
            raise ValueError(f"{label} must be a number.") from exc
        if not minimum <= value <= maximum:
            raise ValueError(f"{label} must be between {minimum:g} and {maximum:g}.")
        return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open the Cardputer-Adv Remote Windows control panel.")
    parser.add_argument("--no-admin-relaunch", action="store_true", help="Do not relaunch through UAC on Windows.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_admin(make_server_args(no_admin_relaunch=args.no_admin_relaunch))
    app = RemoteGui()
    app.mainloop()


if __name__ == "__main__":
    main()
