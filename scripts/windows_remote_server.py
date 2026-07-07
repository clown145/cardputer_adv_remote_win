#!/usr/bin/env python3
"""Desktop-side capture and input bridge for Cardputer-Adv Remote."""

from __future__ import annotations

import argparse
import ctypes
import os
import socket
import struct
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Iterable

from PIL import Image, ImageDraw
from mss import mss
from pynput.keyboard import Controller as KeyboardController, Key
from pynput.mouse import Button, Controller as MouseController

try:
    import numpy as np
except ImportError:  # Keep source check/debug runs usable without the optional fast path installed.
    np = None


MAGIC = 0x41575243  # "CRWA" little endian
FRAME_VERSION = 1
INPUT_VERSIONS = {1, 2}
FORMAT_RGB565 = 1
FORMAT_TILE_DELTA = 2
FRAME_HEADER = struct.Struct("<IHHHHII")
TILE_DELTA_HEADER = struct.Struct("<HH")
TILE_HEADER = struct.Struct("<HHHH")
INPUT_REPORT = struct.Struct("<IHHBB6B")
TILE_WIDTH = 16
TILE_HEIGHT = 15
MOUSE_REPORT_FLAG = 0x80
MOUSE_MODE_ACTIVE = 0x08
MOUSE_HIDE_CROSSHAIR = 0x10
MOUSE_BUTTONS = {
    0: Button.left,
    1: Button.right,
    2: Button.middle,
}
QUALITY_FILTER_CHOICES = ("nearest", "bilinear", "bicubic")
INPUT_BACKEND_CHOICES = ("win32", "pynput")
HOST_OS_WINDOWS = "windows"
HOST_OS_MACOS = "macos"
HOST_OS_GENERIC = "generic"
HOST_OS_CHOICES = (HOST_OS_WINDOWS, HOST_OS_MACOS, HOST_OS_GENERIC)
DISCOVERY_MAGIC = "CARDPUTER_REMOTE"
DISCOVERY_PORT = 5052
DISCOVERY_VERSION = 1
DISCOVERY_BROADCAST_INTERVAL = 2.0


def default_host_os() -> str:
    if sys.platform == "darwin":
        return HOST_OS_MACOS
    if os.name == "nt":
        return HOST_OS_WINDOWS
    return HOST_OS_GENERIC


def default_input_backend() -> str:
    return "win32" if os.name == "nt" else "pynput"


def available_input_backends() -> tuple[str, ...]:
    return INPUT_BACKEND_CHOICES if os.name == "nt" else ("pynput",)


DEFAULT_CONFIG = {
    "bind": "0.0.0.0",
    "frame_port": 5050,
    "input_port": 5051,
    "width": 240,
    "height": 135,
    "fps": 6.0,
    "monitor": 1,
    "quality_filter": "bilinear",
    "input_timeout": 4.0,
    "host_os": default_host_os(),
    "input_backend": default_input_backend(),
    "mouse_pump_hz": 120.0,
    "mouse_hold_ms": 70.0,
    "mouse_scale": 1.0,
    "keyframe_interval": 5.0,
    "no_admin_relaunch": False,
}


HID_TO_SCANCODE = {
    0x04: (0x1E, False),
    0x05: (0x30, False),
    0x06: (0x2E, False),
    0x07: (0x20, False),
    0x08: (0x12, False),
    0x09: (0x21, False),
    0x0A: (0x22, False),
    0x0B: (0x23, False),
    0x0C: (0x17, False),
    0x0D: (0x24, False),
    0x0E: (0x25, False),
    0x0F: (0x26, False),
    0x10: (0x32, False),
    0x11: (0x31, False),
    0x12: (0x18, False),
    0x13: (0x19, False),
    0x14: (0x10, False),
    0x15: (0x13, False),
    0x16: (0x1F, False),
    0x17: (0x14, False),
    0x18: (0x16, False),
    0x19: (0x2F, False),
    0x1A: (0x11, False),
    0x1B: (0x2D, False),
    0x1C: (0x15, False),
    0x1D: (0x2C, False),
    0x1E: (0x02, False),
    0x1F: (0x03, False),
    0x20: (0x04, False),
    0x21: (0x05, False),
    0x22: (0x06, False),
    0x23: (0x07, False),
    0x24: (0x08, False),
    0x25: (0x09, False),
    0x26: (0x0A, False),
    0x27: (0x0B, False),
    0x28: (0x1C, False),
    0x29: (0x01, False),
    0x2A: (0x0E, False),
    0x2B: (0x0F, False),
    0x2C: (0x39, False),
    0x2D: (0x0C, False),
    0x2E: (0x0D, False),
    0x2F: (0x1A, False),
    0x30: (0x1B, False),
    0x31: (0x2B, False),
    0x33: (0x27, False),
    0x34: (0x28, False),
    0x35: (0x29, False),
    0x36: (0x33, False),
    0x37: (0x34, False),
    0x38: (0x35, False),
    0x39: (0x3A, False),
    0x3A: (0x3B, False),
    0x3B: (0x3C, False),
    0x3C: (0x3D, False),
    0x3D: (0x3E, False),
    0x3E: (0x3F, False),
    0x3F: (0x40, False),
    0x40: (0x41, False),
    0x41: (0x42, False),
    0x42: (0x43, False),
    0x43: (0x44, False),
    0x44: (0x57, False),
    0x45: (0x58, False),
    0x4C: (0x53, True),
    0x4F: (0x4D, True),
    0x50: (0x4B, True),
    0x51: (0x50, True),
    0x52: (0x48, True),
}

MODIFIER_SCANCODES = {
    0: (0x1D, False),
    1: (0x2A, False),
    2: (0x38, False),
    3: (0x5B, True),
    4: (0x1D, True),
    5: (0x36, False),
    6: (0x38, True),
    7: (0x5C, True),
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

MACOS_MODIFIER_BITS = {
    **MODIFIER_BITS,
    3: Key.alt_l,
    7: Key.alt_r,
}


def pynput_modifier_bits(host_os: str) -> dict[int, object]:
    if host_os == HOST_OS_MACOS:
        return MACOS_MODIFIER_BITS
    return MODIFIER_BITS

@dataclass(frozen=True)
class KeyState:
    modifiers: int
    keys: tuple[int, ...]

    def modifier_objects(self, modifier_bits: dict[int, object]) -> set[object]:
        pressed: set[object] = set()
        for bit, key in modifier_bits.items():
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
    crosshair: bool
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


@dataclass(frozen=True)
class FramePacket:
    format: int
    payload: bytes
    tile_count: int = 0


class KeyboardBridge:
    def __init__(self, host_os: str) -> None:
        self.keyboard = KeyboardController()
        self.current: set[object] = set()
        self.modifier_bits = pynput_modifier_bits(host_os)
        self.modifier_keys = frozenset(self.modifier_bits.values())
        self.lock = threading.Lock()

    def apply(self, state: KeyState) -> None:
        target_modifiers = state.modifier_objects(self.modifier_bits)
        target_keys = state.key_objects
        target = target_modifiers | target_keys
        with self.lock:
            current_modifiers = self.current & self.modifier_keys
            current_keys = self.current - self.modifier_keys

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
            current_modifiers = self.current & self.modifier_keys
            current_keys = self.current - self.modifier_keys
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

        if state.crosshair:
            self.mode_active.set()
        else:
            self.mode_active.clear()
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
    def __init__(self, mouse_mode_active: threading.Event, host_os: str) -> None:
        self.keyboard = KeyboardBridge(host_os)
        self.mouse = MouseBridge(mouse_mode_active)

    def apply(self, state: KeyState | MouseState) -> None:
        if isinstance(state, KeyState):
            self.keyboard.apply(state)
        else:
            self.mouse.apply(state)

    def release_all(self) -> None:
        self.keyboard.release_all()
        self.mouse.release_all()

    def close(self) -> None:
        self.release_all()


WORD = ctypes.c_uint16
DWORD = ctypes.c_uint32
LONG = ctypes.c_int32
UINT = ctypes.c_uint32
ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", WORD),
        ("wScan", WORD),
        ("dwFlags", DWORD),
        ("time", DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", LONG),
        ("dy", LONG),
        ("mouseData", DWORD),
        ("dwFlags", DWORD),
        ("time", DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (
        ("uMsg", DWORD),
        ("wParamL", WORD),
        ("wParamH", WORD),
    )


class INPUT_UNION(ctypes.Union):
    _fields_ = (
        ("ki", KEYBDINPUT),
        ("mi", MOUSEINPUT),
        ("hi", HARDWAREINPUT),
    )


class INPUT(ctypes.Structure):
    _fields_ = (
        ("type", DWORD),
        ("union", INPUT_UNION),
    )


class Win32SendInput:
    INPUT_MOUSE = 0
    INPUT_KEYBOARD = 1

    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_SCANCODE = 0x0008

    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_RIGHTDOWN = 0x0008
    MOUSEEVENTF_RIGHTUP = 0x0010
    MOUSEEVENTF_MIDDLEDOWN = 0x0020
    MOUSEEVENTF_MIDDLEUP = 0x0040
    MOUSEEVENTF_WHEEL = 0x0800
    WHEEL_DELTA = 120
    DF_ALLOWOTHERACCOUNTHOOK = 0x0001
    GENERIC_ALL = 0x10000000

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("win32 input backend is only available on Windows")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.SendInput.argtypes = (UINT, ctypes.POINTER(INPUT), ctypes.c_int)
        self.user32.SendInput.restype = UINT
        self.user32.OpenInputDesktop.argtypes = (DWORD, ctypes.c_bool, DWORD)
        self.user32.OpenInputDesktop.restype = ctypes.c_void_p
        self.user32.SetThreadDesktop.argtypes = (ctypes.c_void_p,)
        self.user32.SetThreadDesktop.restype = ctypes.c_bool
        self.user32.CloseDesktop.argtypes = (ctypes.c_void_p,)
        self.user32.CloseDesktop.restype = ctypes.c_bool
        self.thread_state = threading.local()
        self.send_lock = threading.Lock()

    def key(self, scan_code: int, down: bool, extended: bool = False) -> None:
        flags = self.KEYEVENTF_SCANCODE
        if extended:
            flags |= self.KEYEVENTF_EXTENDEDKEY
        if not down:
            flags |= self.KEYEVENTF_KEYUP
        event = INPUT(
            type=self.INPUT_KEYBOARD,
            union=INPUT_UNION(ki=KEYBDINPUT(0, scan_code, flags, 0, 0)),
        )
        self._send(event)

    def mouse(self, flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> None:
        event = INPUT(
            type=self.INPUT_MOUSE,
            union=INPUT_UNION(mi=MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, 0)),
        )
        self._send(event)

    def _send(self, event: INPUT) -> None:
        with self.send_lock:
            for attempt in range(2):
                sent = self.user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event))
                if sent == 1:
                    return

                error = ctypes.get_last_error()
                desktop = self._sync_thread_desktop()
                previous = getattr(self.thread_state, "desktop", None)
                if attempt == 0 and desktop and desktop != previous:
                    self.thread_state.desktop = desktop
                    continue
                raise ctypes.WinError(error)

    def _sync_thread_desktop(self) -> int:
        desktop = self.user32.OpenInputDesktop(self.DF_ALLOWOTHERACCOUNTHOOK, False, self.GENERIC_ALL)
        if not desktop:
            error = ctypes.get_last_error()
            print(f"INPUT: OpenInputDesktop failed ({error})", flush=True)
            return 0

        value = int(desktop)
        if not self.user32.SetThreadDesktop(desktop):
            error = ctypes.get_last_error()
            print(f"INPUT: SetThreadDesktop failed ({error})", flush=True)
        self.user32.CloseDesktop(desktop)
        return value


class Win32KeyboardBridge:
    def __init__(self, sender: Win32SendInput) -> None:
        self.sender = sender
        self.current: set[tuple[int, bool]] = set()
        self.lock = threading.Lock()

    def apply(self, state: KeyState) -> None:
        target_modifiers = self._modifier_scancodes(state.modifiers)
        target_keys = self._key_scancodes(state.keys)
        target = target_modifiers | target_keys
        with self.lock:
            current_modifiers = self.current & set(MODIFIER_SCANCODES.values())
            current_keys = self.current - set(MODIFIER_SCANCODES.values())

            for scan_code, extended in current_keys - target_keys:
                self.sender.key(scan_code, False, extended)
            for scan_code, extended in current_modifiers - target_modifiers:
                self.sender.key(scan_code, False, extended)
            for scan_code, extended in target_modifiers - current_modifiers:
                self.sender.key(scan_code, True, extended)
            for scan_code, extended in target_keys - current_keys:
                self.sender.key(scan_code, True, extended)
            self.current = target

    def release_all(self) -> None:
        with self.lock:
            current_modifiers = self.current & set(MODIFIER_SCANCODES.values())
            current_keys = self.current - set(MODIFIER_SCANCODES.values())
            for scan_code, extended in list(current_keys):
                self.sender.key(scan_code, False, extended)
            for scan_code, extended in list(current_modifiers):
                self.sender.key(scan_code, False, extended)
            self.current.clear()

    @staticmethod
    def _modifier_scancodes(modifiers: int) -> set[tuple[int, bool]]:
        return {scan for bit, scan in MODIFIER_SCANCODES.items() if modifiers & (1 << bit)}

    @staticmethod
    def _key_scancodes(keys: tuple[int, ...]) -> set[tuple[int, bool]]:
        return {HID_TO_SCANCODE[hid] for hid in keys if hid in HID_TO_SCANCODE}


class Win32MouseBridge:
    BUTTON_EVENTS = {
        0: (Win32SendInput.MOUSEEVENTF_LEFTDOWN, Win32SendInput.MOUSEEVENTF_LEFTUP),
        1: (Win32SendInput.MOUSEEVENTF_RIGHTDOWN, Win32SendInput.MOUSEEVENTF_RIGHTUP),
        2: (Win32SendInput.MOUSEEVENTF_MIDDLEDOWN, Win32SendInput.MOUSEEVENTF_MIDDLEUP),
    }

    def __init__(self, sender: Win32SendInput, mode_active: threading.Event, args: argparse.Namespace) -> None:
        self.sender = sender
        self.mode_active = mode_active
        self.current_buttons: set[int] = set()
        self.lock = threading.Lock()
        self.velocity_lock = threading.Lock()
        self.velocity_dx = 0
        self.velocity_dy = 0
        self.velocity_until = 0.0
        self.pump_interval = 1.0 / max(float(args.mouse_pump_hz), 1.0)
        self.hold_seconds = max(float(args.mouse_hold_ms), 1.0) / 1000.0
        self.mouse_scale = max(float(args.mouse_scale), 0.05)
        self.stop_event = threading.Event()
        self.pump_thread = threading.Thread(target=self._pump_mouse_moves, daemon=True)
        self.pump_thread.start()

    def apply(self, state: MouseState) -> None:
        if not state.active:
            self.mode_active.clear()
            self.release_all()
            return

        if state.crosshair:
            self.mode_active.set()
        else:
            self.mode_active.clear()
        target_buttons = {bit for bit in self.BUTTON_EVENTS if state.buttons & (1 << bit)}
        with self.lock:
            for bit in self.current_buttons - target_buttons:
                self.sender.mouse(self.BUTTON_EVENTS[bit][1])
            for bit in target_buttons - self.current_buttons:
                self.sender.mouse(self.BUTTON_EVENTS[bit][0])
            self.current_buttons = target_buttons

            if state.dx or state.dy:
                if state.crosshair:
                    self.sender.mouse(self.sender.MOUSEEVENTF_MOVE, dx=state.dx, dy=state.dy)
                else:
                    self._set_velocity(state.dx, state.dy)
            if state.wheel:
                self.sender.mouse(self.sender.MOUSEEVENTF_WHEEL, data=state.wheel * self.sender.WHEEL_DELTA)

    def release_all(self) -> None:
        self.mode_active.clear()
        self._clear_velocity()
        with self.lock:
            for bit in list(self.current_buttons):
                self.sender.mouse(self.BUTTON_EVENTS[bit][1])
            self.current_buttons.clear()

    def close(self) -> None:
        self.stop_event.set()
        self.release_all()
        self.pump_thread.join(timeout=1.0)

    def _set_velocity(self, dx: int, dy: int) -> None:
        with self.velocity_lock:
            self.velocity_dx = dx
            self.velocity_dy = dy
            self.velocity_until = time.perf_counter() + self.hold_seconds

    def _clear_velocity(self) -> None:
        with self.velocity_lock:
            self.velocity_dx = 0
            self.velocity_dy = 0
            self.velocity_until = 0.0

    def _pump_mouse_moves(self) -> None:
        while not self.stop_event.wait(self.pump_interval):
            with self.velocity_lock:
                if time.perf_counter() > self.velocity_until:
                    self.velocity_dx = 0
                    self.velocity_dy = 0
                dx = self._scaled_delta(self.velocity_dx)
                dy = self._scaled_delta(self.velocity_dy)
            if dx or dy:
                try:
                    self.sender.mouse(self.sender.MOUSEEVENTF_MOVE, dx=dx, dy=dy)
                except OSError as exc:
                    print(f"INPUT: mouse pump failed ({exc})", flush=True)
                    self._clear_velocity()

    def _scaled_delta(self, value: int) -> int:
        if value == 0:
            return 0
        scaled = int(round(value * self.mouse_scale))
        if scaled == 0:
            return 1 if value > 0 else -1
        return scaled


class Win32InputBridge:
    def __init__(self, mouse_mode_active: threading.Event, args: argparse.Namespace) -> None:
        sender = Win32SendInput()
        self.keyboard = Win32KeyboardBridge(sender)
        self.mouse = Win32MouseBridge(sender, mouse_mode_active, args)

    def apply(self, state: KeyState | MouseState) -> None:
        if isinstance(state, KeyState):
            self.keyboard.apply(state)
        else:
            self.mouse.apply(state)

    def release_all(self) -> None:
        self.keyboard.release_all()
        self.mouse.release_all()

    def close(self) -> None:
        self.keyboard.release_all()
        self.mouse.close()


def make_server_args(**overrides: object) -> argparse.Namespace:
    values = dict(DEFAULT_CONFIG)
    values.update(overrides)
    return argparse.Namespace(**values)


def discovery_probe_packet(args: argparse.Namespace) -> bytes:
    return (
        f"{DISCOVERY_MAGIC} DISCOVER {DISCOVERY_VERSION} {args.width} {args.height}\n"
    ).encode("ascii")


def discovery_host_packet(args: argparse.Namespace) -> bytes:
    return (
        f"{DISCOVERY_MAGIC} HOST {DISCOVERY_VERSION} {args.width} {args.height} "
        f"{args.frame_port} {args.input_port}\n"
    ).encode("ascii")


def discovery_server(args: argparse.Namespace, stop: threading.Event) -> None:
    probe = discovery_probe_packet(args)
    host_packet = discovery_host_packet(args)
    seen: dict[str, float] = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except OSError:
            pass
        try:
            server.bind(("0.0.0.0", DISCOVERY_PORT))
        except OSError as exc:
            print(f"DISCOVERY: disabled ({exc})", flush=True)
            return
        server.settimeout(0.5)
        print(f"DISCOVERY: listening on UDP {DISCOVERY_PORT}", flush=True)
        next_broadcast = 0.0
        while not stop.is_set():
            now = time.monotonic()
            if now >= next_broadcast:
                try:
                    server.sendto(probe, ("255.255.255.255", DISCOVERY_PORT))
                except OSError as exc:
                    print(f"DISCOVERY: broadcast failed ({exc})", flush=True)
                next_broadcast = now + DISCOVERY_BROADCAST_INTERVAL

            try:
                data, addr = server.recvfrom(256)
            except socket.timeout:
                continue
            except OSError as exc:
                if not stop.is_set():
                    print(f"DISCOVERY: socket error ({exc})", flush=True)
                break

            text = data.decode("ascii", errors="replace").strip()
            parts = text.split()
            if len(parts) < 5 or parts[0] != DISCOVERY_MAGIC:
                continue
            if parts[1] != "ADV":
                continue
            try:
                version = int(parts[2])
                width = int(parts[3])
                height = int(parts[4])
            except ValueError:
                continue
            if version != DISCOVERY_VERSION:
                continue
            if width != args.width or height != args.height:
                print(
                    f"DISCOVERY: {addr[0]}:{addr[1]} announced {width}x{height}, expected {args.width}x{args.height}",
                    flush=True,
                )
                continue

            if now - seen.get(addr[0], 0.0) >= 10.0:
                print(f"DISCOVERY: ADV {addr[0]}:{addr[1]}", flush=True)
                seen[addr[0]] = now

            try:
                server.sendto(host_packet, addr)
            except OSError as exc:
                print(f"DISCOVERY: reply to {addr[0]} failed ({exc})", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve desktop screen and keyboard control to a Cardputer-Adv.")
    parser.add_argument("--bind", default=DEFAULT_CONFIG["bind"], help="IP/interface to listen on.")
    parser.add_argument("--frame-port", type=int, default=DEFAULT_CONFIG["frame_port"])
    parser.add_argument("--input-port", type=int, default=DEFAULT_CONFIG["input_port"])
    parser.add_argument("--width", type=int, default=DEFAULT_CONFIG["width"])
    parser.add_argument("--height", type=int, default=DEFAULT_CONFIG["height"])
    parser.add_argument("--fps", type=float, default=DEFAULT_CONFIG["fps"])
    parser.add_argument("--monitor", type=int, default=DEFAULT_CONFIG["monitor"], help="mss monitor index. 1 is usually the primary display.")
    parser.add_argument("--quality-filter", choices=QUALITY_FILTER_CHOICES, default=DEFAULT_CONFIG["quality_filter"])
    parser.add_argument("--input-timeout", type=float, default=DEFAULT_CONFIG["input_timeout"], help="Seconds without input reports before reconnect.")
    parser.add_argument("--host-os", choices=HOST_OS_CHOICES, default=DEFAULT_CONFIG["host_os"], help="Host key mapping for the bridge. On Windows, Cardputer Opt maps to Win; on macOS, it maps to Option.")
    parser.add_argument("--input-backend", choices=available_input_backends(), default=DEFAULT_CONFIG["input_backend"])
    parser.add_argument("--mouse-pump-hz", type=float, default=DEFAULT_CONFIG["mouse_pump_hz"], help="Hidden-crosshair mouse pump rate for game mode.")
    parser.add_argument("--mouse-hold-ms", type=float, default=DEFAULT_CONFIG["mouse_hold_ms"], help="How long each game mouse delta is replayed.")
    parser.add_argument("--mouse-scale", type=float, default=DEFAULT_CONFIG["mouse_scale"], help="Multiplier for game mouse deltas.")
    parser.add_argument("--keyframe-interval", type=float, default=DEFAULT_CONFIG["keyframe_interval"], help="Seconds between full RGB565 keyframes. Use 0 to send only the initial keyframe.")
    parser.add_argument("--no-admin-relaunch", action="store_true", help="Do not relaunch through UAC on Windows.")
    return parser.parse_args()


def is_admin() -> bool:
    if os.name != "nt":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def relaunch_as_admin() -> bool:
    if os.name != "nt":
        return False

    if getattr(sys, "frozen", False):
        executable = sys.executable
        params = subprocess.list2cmdline(sys.argv[1:])
    else:
        executable = sys.executable
        params = subprocess.list2cmdline(sys.argv)

    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, params, os.getcwd(), 1)
    return result > 32


def ensure_admin(args: argparse.Namespace) -> None:
    if os.name != "nt" or args.no_admin_relaunch or is_admin():
        return
    print("Administrator privileges are required for reliable game input. Requesting UAC elevation...")
    if relaunch_as_admin():
        raise SystemExit(0)
    print("UAC elevation was cancelled or failed; continuing without administrator privileges.", flush=True)


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


def accept_client(
    server: socket.socket,
    channel: str,
    expected_width: int,
    expected_height: int,
    stop: threading.Event,
) -> socket.socket | None:
    while not stop.is_set():
        try:
            conn, addr = server.accept()
        except socket.timeout:
            continue
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
    return None


def rgb_to_rgb565_bytes(image: Image.Image) -> bytes:
    rgb = image.convert("RGB")
    if np is not None:
        pixels = np.asarray(rgb, dtype=np.uint8)
        red = pixels[:, :, 0].astype(np.uint16)
        green = pixels[:, :, 1].astype(np.uint16)
        blue = pixels[:, :, 2].astype(np.uint16)
        rgb565 = ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)
        return rgb565.astype("<u2", copy=False).tobytes()

    out = bytearray(rgb.width * rgb.height * 2)
    offset = 0
    for r, g, b in rgb.getdata():
        value = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        out[offset] = value & 0xFF
        out[offset + 1] = value >> 8
        offset += 2
    return bytes(out)


def encode_tile_delta_frame(frame: bytes, previous: bytes, width: int, height: int) -> FramePacket:
    parts: list[bytes] = [TILE_DELTA_HEADER.pack(0, 0)]
    tile_count = 0
    stride = width * 2

    for y in range(0, height, TILE_HEIGHT):
        tile_h = min(TILE_HEIGHT, height - y)
        for x in range(0, width, TILE_WIDTH):
            tile_w = min(TILE_WIDTH, width - x)
            row_len = tile_w * 2
            row_parts: list[bytes] = []
            changed = False
            for row in range(y, y + tile_h):
                start = row * stride + x * 2
                end = start + row_len
                row_data = frame[start:end]
                if row_data != previous[start:end]:
                    changed = True
                row_parts.append(row_data)
            if not changed:
                continue

            tile_count += 1
            parts.append(TILE_HEADER.pack(x, y, tile_w, tile_h))
            parts.extend(row_parts)

    if tile_count == 0:
        return FramePacket(FORMAT_TILE_DELTA, TILE_DELTA_HEADER.pack(0, 0), tile_count)

    parts[0] = TILE_DELTA_HEADER.pack(tile_count, 0)
    payload = b"".join(parts)
    if len(payload) >= len(frame):
        return FramePacket(FORMAT_RGB565, frame, tile_count)
    return FramePacket(FORMAT_TILE_DELTA, payload, tile_count)


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
    keyframe_interval: float,
) -> Iterable[FramePacket]:
    with mss() as screen:
        if monitor_index < 0 or monitor_index >= len(screen.monitors):
            raise SystemExit(f"Monitor {monitor_index} does not exist. Available: 0..{len(screen.monitors) - 1}")
        monitor = screen.monitors[monitor_index]
        previous_frame: bytes | None = None
        last_keyframe_at = 0.0
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
            frame = rgb_to_rgb565_bytes(canvas)
            now = time.perf_counter()
            force_keyframe = previous_frame is None or (
                keyframe_interval > 0 and now - last_keyframe_at >= keyframe_interval
            )
            if force_keyframe:
                packet = FramePacket(FORMAT_RGB565, frame)
                last_keyframe_at = now
            else:
                packet = encode_tile_delta_frame(frame, previous_frame, width, height)
                if packet.format == FORMAT_RGB565:
                    last_keyframe_at = now
            previous_frame = frame
            yield packet


def frame_server(args: argparse.Namespace, stop: threading.Event, mouse_mode_active: threading.Event) -> None:
    resize_filter = {
        "nearest": Image.Resampling.NEAREST,
        "bilinear": Image.Resampling.BILINEAR,
        "bicubic": Image.Resampling.BICUBIC,
    }[args.quality_filter]

    with socket.create_server((args.bind, args.frame_port), reuse_port=False) as server:
        server.settimeout(0.5)
        server.listen(1)
        print(f"FRAME: listening on {args.bind}:{args.frame_port}", flush=True)
        frame_id = 0
        interval = 1.0 / max(args.fps, 0.1)
        mouse = MouseController()
        while not stop.is_set():
            conn = accept_client(server, "FRAME", args.width, args.height, stop)
            if conn is None:
                break
            try:
                for packet in capture_frames(
                    args.width,
                    args.height,
                    args.monitor,
                    resize_filter,
                    mouse,
                    mouse_mode_active,
                    args.keyframe_interval,
                ):
                    if stop.is_set():
                        break
                    frame_id = (frame_id + 1) & 0xFFFFFFFF
                    header = FRAME_HEADER.pack(
                        MAGIC,
                        FRAME_VERSION,
                        args.width,
                        args.height,
                        packet.format,
                        frame_id,
                        len(packet.payload),
                    )
                    started = time.perf_counter()
                    conn.sendall(header + packet.payload)
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
        crosshair = active and not bool(key_count & MOUSE_HIDE_CROSSHAIR)
        buttons = key_count & 0x07
        return MouseState(
            active=active,
            crosshair=crosshair,
            buttons=buttons,
            dx=to_i8(keys[0]),
            dy=to_i8(keys[1]),
            wheel=to_i8(keys[2]),
        )
    key_count = min(key_count, len(keys))
    return KeyState(modifiers=modifiers, keys=tuple(k for k in keys[:key_count] if k))


def input_server(args: argparse.Namespace, bridge: InputBridge | Win32InputBridge, stop: threading.Event) -> None:
    with socket.create_server((args.bind, args.input_port), reuse_port=False) as server:
        server.settimeout(0.5)
        server.listen(1)
        print(f"INPUT: listening on {args.bind}:{args.input_port}", flush=True)
        while not stop.is_set():
            conn = accept_client(server, "INPUT", args.width, args.height, stop)
            if conn is None:
                break
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


def create_input_bridge(args: argparse.Namespace, mouse_mode_active: threading.Event) -> InputBridge | Win32InputBridge:
    if args.input_backend == "win32":
        return Win32InputBridge(mouse_mode_active, args)
    return InputBridge(mouse_mode_active, args.host_os)


def run_server(args: argparse.Namespace, stop: threading.Event | None = None) -> None:
    if stop is None:
        stop = threading.Event()
    mouse_mode_active = threading.Event()
    bridge = create_input_bridge(args, mouse_mode_active)

    print("Cardputer-Adv Remote desktop server")
    print(f"Resolution: {args.width}x{args.height} at {args.fps:g} FPS")
    print(f"Monitor: {args.monitor}")
    print(f"Quality filter: {args.quality_filter}")
    print(f"Frame codec: RGB565 keyframes + {TILE_WIDTH}x{TILE_HEIGHT} tile delta")
    print(f"Keyframe interval: {args.keyframe_interval:g}s")
    print(f"Host key mapping: {args.host_os}")
    print(f"Input backend: {args.input_backend}")
    print(f"Game mouse: {args.mouse_pump_hz:g} Hz, hold {args.mouse_hold_ms:g} ms, scale {args.mouse_scale:g}")
    print(f"Discovery: UDP {DISCOVERY_PORT}")
    print(f"Administrator: {'yes' if is_admin() else 'no'}")
    if os.name == "nt":
        print("Tip: run as Administrator if you need to control elevated windows.")
    elif sys.platform == "darwin":
        print("Tip: grant Screen Recording and Accessibility permissions to control macOS.")

    threads = [
        threading.Thread(target=discovery_server, args=(args, stop), daemon=True),
        threading.Thread(target=frame_server, args=(args, stop, mouse_mode_active), daemon=True),
        threading.Thread(target=input_server, args=(args, bridge, stop), daemon=True),
    ]
    for thread in threads:
        thread.start()

    try:
        while not stop.is_set() and all(thread.is_alive() for thread in threads):
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("\nStopping...", flush=True)
    finally:
        stop.set()
        bridge.close()
        for thread in threads:
            thread.join(timeout=1.0)


def main() -> None:
    args = parse_args()
    ensure_admin(args)
    run_server(args)


if __name__ == "__main__":
    main()
