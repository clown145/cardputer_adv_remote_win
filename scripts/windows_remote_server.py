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

from PIL import Image
from mss import mss
from pynput.keyboard import Controller, Key


MAGIC = 0x41575243  # "CRWA" little endian
VERSION = 1
FORMAT_RGB565 = 1
FRAME_HEADER = struct.Struct("<IHHHHII")
INPUT_REPORT = struct.Struct("<IHHBB6B")


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


class KeyboardBridge:
    def __init__(self) -> None:
        self.keyboard = Controller()
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
    return parser.parse_args()


def recv_line(conn: socket.socket, limit: int = 120) -> str:
    data = bytearray()
    while len(data) < limit:
        chunk = conn.recv(1)
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


def capture_frames(width: int, height: int, monitor_index: int, resize_filter: int) -> Iterable[bytes]:
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
            yield rgb_to_rgb565_bytes(canvas)


def frame_server(args: argparse.Namespace, stop: threading.Event) -> None:
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
        while not stop.is_set():
            conn = accept_client(server, "FRAME", args.width, args.height)
            try:
                for payload in capture_frames(args.width, args.height, args.monitor, resize_filter):
                    if stop.is_set():
                        break
                    frame_id = (frame_id + 1) & 0xFFFFFFFF
                    header = FRAME_HEADER.pack(
                        MAGIC,
                        VERSION,
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


def decode_input_report(data: bytes) -> KeyState | None:
    magic, version, sequence, modifiers, key_count, *keys = INPUT_REPORT.unpack(data)
    if magic != MAGIC or version != VERSION:
        print(f"INPUT: bad report magic/version: {magic:#x}/{version}", flush=True)
        return None
    key_count = min(key_count, len(keys))
    return KeyState(modifiers=modifiers, keys=tuple(k for k in keys[:key_count] if k))


def input_server(args: argparse.Namespace, bridge: KeyboardBridge, stop: threading.Event) -> None:
    with socket.create_server((args.bind, args.input_port), reuse_port=False) as server:
        server.listen(1)
        print(f"INPUT: listening on {args.bind}:{args.input_port}", flush=True)
        while not stop.is_set():
            conn = accept_client(server, "INPUT", args.width, args.height)
            try:
                while not stop.is_set():
                    data = conn.recv(INPUT_REPORT.size)
                    if not data:
                        break
                    while len(data) < INPUT_REPORT.size:
                        more = conn.recv(INPUT_REPORT.size - len(data))
                        if not more:
                            raise ConnectionError("short input report")
                        data += more
                    state = decode_input_report(data)
                    if state is not None:
                        bridge.apply(state)
            except (ConnectionError, OSError) as exc:
                print(f"INPUT: disconnected ({exc})", flush=True)
            finally:
                bridge.release_all()
                conn.close()


def main() -> None:
    args = parse_args()
    stop = threading.Event()
    bridge = KeyboardBridge()

    print("Cardputer-Adv Windows Remote server")
    print(f"Resolution: {args.width}x{args.height} at {args.fps:g} FPS")
    print("Tip: run as Administrator if you need to control elevated windows.")

    threads = [
        threading.Thread(target=frame_server, args=(args, stop), daemon=True),
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
