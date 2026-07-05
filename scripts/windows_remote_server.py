#!/usr/bin/env python3
"""Windows-side capture and input bridge for Cardputer-Adv Remote."""

from __future__ import annotations

import argparse
import socket
import struct
import threading
import time
from dataclasses import dataclass
from typing import Iterable

from PIL import Image, ImageDraw
from mss import mss
from pynput.keyboard import Controller as KeyboardController, Key
from pynput.mouse import Button, Controller as MouseController


MAGIC = 0x41575243  # "CRWA" little endian
FRAME_VERSION = 1
INPUT_VERSIONS = {1, 2}
FORMAT_RGB565 = 1
FRAME_HEADER = struct.Struct("<IHHHHII")
INPUT_REPORT = struct.Struct("<IHHBB6B")
MOUSE_REPORT_FLAG = 0x80
MOUSE_MODE_ACTIVE = 0x08
MOUSE_BUTTONS = {
    0: Button.left,
    1: Button.right,
    2: Button.middle,
}


HID_TO_PYNPUT = {
    0x04: "a",
    0x05: "b",
    0x06: "c",
    0x07: "d",
    0x08: "e",
    0x09: "f",
    0x0A: "g",
    0x0B: "h",
    0x0C: "i",
    0x0D: "j",
    0x0E: "k",
    0x0F: "l",
    0x10: "m",
    0x11: "n",
    0x12: "o",
    0x13: "p",
    0x14: "q",
    0x15: "r",
    0x16: "s",
    0x17: "t",
    0x18: "u",
    0x19: "v",
    0x1A: "w",
    0x1B: "x",
    0x1C: "y",
    0x1D: "z",
    0x1E: "1",
    0x1F: "2",
    0x20: "3",
    0x21: "4",
    0x22: "5",
    0x23: "6",
    0x24: "7",
    0x25: "8",
    0x26: "9",
    0x27: "0",
    0x28: Key.enter,
    0x29: Key.esc,
    0x2A: Key.backspace,
    0x2B: Key.tab,
    0x2C: Key.space,
    0x2D: "-",
    0x2E: "=",
    0x2F: "[",
    0x30: "]",
    0x31: "\\",
    0x33: ";",
    0x34: "'",
    0x35: "`",
    0x36: ",",
    0x37: ".",
    0x38: "/",
    0x39: Key.caps_lock,
    0x3A: Key.f1,
    0x3B: Key.f2,
    0x3C: Key.f3,
    0x3D: Key.f4,
    0x3E: Key.f5,
    0x3F: Key.f6,
    0x40: Key.f7,
    0x41: Key.f8,
    0x42: Key.f9,
    0x43: Key.f10,
    0x44: Key.f11,
    0x45: Key.f12,
    0x4C: Key.delete,
    0x4F: Key.right,
    0x50: Key.left,
    0x51: Key.down,
    0x52: Key.up,
}

MODIFIER_BITS = {
    0: Key.ctrl_l,
    1: Key.shift_l,
    2: Key.alt_l,
    3: Key.cmd_l,
    4: Key.ctrl_r,
    5: Key.shift_r,
    6: Key.alt_r,
    7: Key.cmd_r,
}
MODIFIER_KEYS = frozenset(MODIFIER_BITS.values())

@dataclass(frozen=True)
class KeyState:
    modifiers: int
    keys: tuple[int, ...]

    @property
    def modifier_objects(self) -> set[object]:
        pressed: set[object] = set()
        for bit, key in MODIFIER_BITS.items():
            if self.modifiers & (1 << bit):
                pressed.add(key)
        return pressed

    @property
    def key_objects(self) -> set[object]:
        pressed: set[object] = set()
        for hid in self.keys:
            key = HID_TO_PYNPUT.get(hid)
            if key is not None:
                pressed.add(key)
        return pressed


@dataclass(frozen=True)
class MouseState:
    active: bool
    buttons: int
    dx: int
    dy: int
    wheel: int

    @property
    def button_objects(self) -> set[Button]:
        pressed: set[Button] = set()
        for bit, button in MOUSE_BUTTONS.items():
            if self.buttons & (1 << bit):
                pressed.add(button)
        return pressed


class KeyboardBridge:
    def __init__(self) -> None:
        self.keyboard = KeyboardController()
        self.current: set[object] = set()
        self.lock = threading.Lock()

    def apply(self, state: KeyState) -> None:
        target_modifiers = state.modifier_objects
        target_keys = state.key_objects
        target = target_modifiers | target_keys
        with self.lock:
            current_modifiers = self.current & MODIFIER_KEYS
            current_keys = self.current - MODIFIER_KEYS

            for key in current_keys - target_keys:
                self.keyboard.release(key)
            for key in current_modifiers - target_modifiers:
                self.keyboard.release(key)
            for key in target_modifiers - current_modifiers:
                self.keyboard.press(key)
            for key in target_keys - current_keys:
                self.keyboard.press(key)
            self.current = target

    def release_all(self) -> None:
        with self.lock:
            current_modifiers = self.current & MODIFIER_KEYS
            current_keys = self.current - MODIFIER_KEYS
            for key in list(current_keys):
                self.keyboard.release(key)
            for key in list(current_modifiers):
                self.keyboard.release(key)
            self.current.clear()


class MouseBridge:
    def __init__(self, mode_active: threading.Event) -> None:
        self.mouse = MouseController()
        self.mode_active = mode_active
        self.current_buttons: set[Button] = set()
        self.lock = threading.Lock()

    def apply(self, state: MouseState) -> None:
        if not state.active:
            self.mode_active.clear()
            self.release_all()
            return

        self.mode_active.set()
        target_buttons = state.button_objects
        with self.lock:
            for button in self.current_buttons - target_buttons:
                self.mouse.release(button)
            for button in target_buttons - self.current_buttons:
                self.mouse.press(button)
            self.current_buttons = target_buttons

            if state.dx or state.dy:
                self.mouse.move(state.dx, state.dy)
            if state.wheel:
                self.mouse.scroll(0, state.wheel)

    def release_all(self) -> None:
        self.mode_active.clear()
        with self.lock:
            for button in list(self.current_buttons):
                self.mouse.release(button)
            self.current_buttons.clear()


class InputBridge:
    def __init__(self, mouse_mode_active: threading.Event) -> None:
        self.keyboard = KeyboardBridge()
        self.mouse = MouseBridge(mouse_mode_active)

    def apply(self, state: KeyState | MouseState) -> None:
        if isinstance(state, KeyState):
            self.mouse.release_all()
            self.keyboard.apply(state)
        else:
            self.mouse.apply(state)

    def release_all(self) -> None:
        self.keyboard.release_all()
        self.mouse.release_all()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve Windows screen and keyboard control to a Cardputer-Adv.")
    parser.add_argument("--bind", default="0.0.0.0", help="IP/interface to listen on.")
    parser.add_argument("--frame-port", type=int, default=5050)
    parser.add_argument("--input-port", type=int, default=5051)
    parser.add_argument("--width", type=int, default=240)
    parser.add_argument("--height", type=int, default=135)
    parser.add_argument("--fps", type=float, default=6.0)
    parser.add_argument("--monitor", type=int, default=1, help="mss monitor index. 1 is usually the primary display.")
    parser.add_argument("--quality-filter", choices=("nearest", "bilinear", "bicubic"), default="bilinear")
    parser.add_argument("--input-timeout", type=float, default=4.0, help="Seconds without input reports before reconnect.")
    return parser.parse_args()


def recv_line(conn: socket.socket, limit: int = 120) -> str:
    data = bytearray()
    while len(data) < limit:
        try:
            chunk = conn.recv(1)
        except socket.timeout:
            break
        if not chunk:
            break
        data.extend(chunk)
        if chunk == b"\n":
            break
    return data.decode("ascii", errors="replace").strip()


def accept_client(server: socket.socket, channel: str, expected_width: int, expected_height: int) -> socket.socket:
    while True:
        conn, addr = server.accept()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        conn.settimeout(5.0)
        hello = recv_line(conn)
        print(f"{channel}: connection from {addr[0]}:{addr[1]} -> {hello}", flush=True)
        parts = hello.split()
        if len(parts) == 4 and parts[:2] == ["CARDPUTER_REMOTE", channel]:
            try:
                width = int(parts[2])
                height = int(parts[3])
            except ValueError:
                width = height = -1
            if width == expected_width and height == expected_height:
                conn.settimeout(None)
                return conn
            print(f"{channel}: rejected resolution {width}x{height}", flush=True)
        else:
            print(f"{channel}: rejected bad hello", flush=True)
        conn.close()


def rgb_to_rgb565_bytes(image: Image.Image) -> bytes:
    rgb = image.convert("RGB")
    out = bytearray(rgb.width * rgb.height * 2)
    offset = 0
    for r, g, b in rgb.getdata():
        value = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        out[offset] = value & 0xFF
        out[offset + 1] = value >> 8
        offset += 2
    return bytes(out)


def draw_cursor_crosshair(
    canvas: Image.Image,
    monitor: dict[str, int],
    image_x: int,
    image_y: int,
    image_w: int,
    image_h: int,
    mouse: MouseController,
) -> None:
    cursor_x, cursor_y = mouse.position
    monitor_left = monitor["left"]
    monitor_top = monitor["top"]
    monitor_w = monitor["width"]
    monitor_h = monitor["height"]

    if not (monitor_left <= cursor_x < monitor_left + monitor_w and monitor_top <= cursor_y < monitor_top + monitor_h):
        return

    frame_x = image_x + int((cursor_x - monitor_left) * image_w / monitor_w)
    frame_y = image_y + int((cursor_y - monitor_top) * image_h / monitor_h)
    frame_x = max(0, min(canvas.width - 1, frame_x))
    frame_y = max(0, min(canvas.height - 1, frame_y))

    draw = ImageDraw.Draw(canvas)
    black = (0, 0, 0)
    white = (255, 255, 255)

    for x in (frame_x - 1, frame_x + 1):
        if 0 <= x < canvas.width:
            draw.line((x, 0, x, canvas.height - 1), fill=black)
    for y in (frame_y - 1, frame_y + 1):
        if 0 <= y < canvas.height:
            draw.line((0, y, canvas.width - 1, y), fill=black)
    draw.line((frame_x, 0, frame_x, canvas.height - 1), fill=white)
    draw.line((0, frame_y, canvas.width - 1, frame_y), fill=white)


def capture_frames(
    width: int,
    height: int,
    monitor_index: int,
    resize_filter: int,
    mouse: MouseController,
    mouse_mode_active: threading.Event,
) -> Iterable[bytes]:
    with mss() as screen:
        if monitor_index < 0 or monitor_index >= len(screen.monitors):
            raise SystemExit(f"Monitor {monitor_index} does not exist. Available: 0..{len(screen.monitors) - 1}")
        monitor = screen.monitors[monitor_index]
        while True:
            shot = screen.grab(monitor)
            image = Image.frombytes("RGB", shot.size, shot.rgb)
            image.thumbnail((width, height), resize_filter)

            canvas = Image.new("RGB", (width, height), "black")
            x = (width - image.width) // 2
            y = (height - image.height) // 2
            canvas.paste(image, (x, y))
            if mouse_mode_active.is_set():
                draw_cursor_crosshair(canvas, monitor, x, y, image.width, image.height, mouse)
            yield rgb_to_rgb565_bytes(canvas)


def frame_server(args: argparse.Namespace, stop: threading.Event, mouse_mode_active: threading.Event) -> None:
    resize_filter = {
        "nearest": Image.Resampling.NEAREST,
        "bilinear": Image.Resampling.BILINEAR,
        "bicubic": Image.Resampling.BICUBIC,
    }[args.quality_filter]

    with socket.create_server((args.bind, args.frame_port), reuse_port=False) as server:
        server.listen(1)
        print(f"FRAME: listening on {args.bind}:{args.frame_port}", flush=True)
        frame_id = 0
        interval = 1.0 / max(args.fps, 0.1)
        mouse = MouseController()
        while not stop.is_set():
            conn = accept_client(server, "FRAME", args.width, args.height)
            try:
                for payload in capture_frames(args.width, args.height, args.monitor, resize_filter, mouse, mouse_mode_active):
                    if stop.is_set():
                        break
                    frame_id = (frame_id + 1) & 0xFFFFFFFF
                    header = FRAME_HEADER.pack(
                        MAGIC,
                        FRAME_VERSION,
                        args.width,
                        args.height,
                        FORMAT_RGB565,
                        frame_id,
                        len(payload),
                    )
                    started = time.perf_counter()
                    conn.sendall(header + payload)
                    elapsed = time.perf_counter() - started
                    time.sleep(max(0.0, interval - elapsed))
            except (ConnectionError, OSError) as exc:
                print(f"FRAME: disconnected ({exc})", flush=True)
            finally:
                conn.close()


def to_i8(value: int) -> int:
    return value - 256 if value & 0x80 else value


def recv_exact(conn: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        if not chunk:
            raise ConnectionError("input connection closed")
        data.extend(chunk)
    return bytes(data)


def decode_input_report(data: bytes) -> KeyState | MouseState | None:
    magic, version, sequence, modifiers, key_count, *keys = INPUT_REPORT.unpack(data)
    if magic != MAGIC or version not in INPUT_VERSIONS:
        print(f"INPUT: bad report magic/version: {magic:#x}/{version}", flush=True)
        return None
    if key_count & MOUSE_REPORT_FLAG:
        active = bool(key_count & MOUSE_MODE_ACTIVE)
        buttons = key_count & 0x07
        return MouseState(active=active, buttons=buttons, dx=to_i8(keys[0]), dy=to_i8(keys[1]), wheel=to_i8(keys[2]))
    key_count = min(key_count, len(keys))
    return KeyState(modifiers=modifiers, keys=tuple(k for k in keys[:key_count] if k))


def input_server(args: argparse.Namespace, bridge: InputBridge, stop: threading.Event) -> None:
    with socket.create_server((args.bind, args.input_port), reuse_port=False) as server:
        server.listen(1)
        print(f"INPUT: listening on {args.bind}:{args.input_port}", flush=True)
        while not stop.is_set():
            conn = accept_client(server, "INPUT", args.width, args.height)
            conn.settimeout(args.input_timeout)
            try:
                while not stop.is_set():
                    data = recv_exact(conn, INPUT_REPORT.size)
                    state = decode_input_report(data)
                    if state is not None:
                        bridge.apply(state)
            except socket.timeout:
                print(f"INPUT: disconnected (no reports for {args.input_timeout:g}s)", flush=True)
            except (ConnectionError, OSError) as exc:
                print(f"INPUT: disconnected ({exc})", flush=True)
            finally:
                bridge.release_all()
                conn.close()


def main() -> None:
    args = parse_args()
    stop = threading.Event()
    mouse_mode_active = threading.Event()
    bridge = InputBridge(mouse_mode_active)

    print("Cardputer-Adv Windows Remote server")
    print(f"Resolution: {args.width}x{args.height} at {args.fps:g} FPS")
    print("Tip: run as Administrator if you need to control elevated windows.")

    threads = [
        threading.Thread(target=frame_server, args=(args, stop, mouse_mode_active), daemon=True),
        threading.Thread(target=input_server, args=(args, bridge, stop), daemon=True),
    ]
    for thread in threads:
        thread.start()

    try:
        while all(thread.is_alive() for thread in threads):
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("\nStopping...", flush=True)
    finally:
        stop.set()
        bridge.release_all()


if __name__ == "__main__":
    main()
