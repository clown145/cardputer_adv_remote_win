# Cardputer-Adv Desktop Remote

[中文文档](README.zh-CN.md)

Native firmware and a desktop GUI bridge for using an M5Stack Cardputer-Adv as a tiny Wi-Fi remote controller.

The desktop app captures the screen, downscales it to `240x135`, streams RGB565 keyframes plus tile deltas to the Cardputer-Adv, and injects keyboard/mouse input sent back by the device. Use it only on a trusted LAN.

## Use

1. Download the latest release assets.
2. Flash `cardputer_adv_remote_win_merged.bin` to the Cardputer-Adv at address `0x0`.
3. Run the desktop app (`cardputer_adv_remote_win.exe` on Windows, `cardputer_adv_remote_macos.app` on macOS).
4. In the GUI, choose the input backend that matches your desktop OS (`win32` on Windows, `pynput` on macOS/Linux), then choose monitor/FPS/mode and click `Start`.
5. On the Cardputer-Adv, scan Wi-Fi, enter the Wi-Fi password, then connect. The desktop app will announce itself on the LAN and the Cardputer saves the host IP automatically.

If the Cardputer-Adv cannot enter download mode automatically, hold `BtnG0`, tap `BtnRST`, keep holding `BtnG0` for about one second, then release it and flash again.

## Build

Firmware:

```bash
python -m pip install platformio
pio run -e cardputer_adv
pio run -e cardputer_adv -t upload
```

Windows GUI:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r scripts\requirements-windows.txt
python scripts\windows_remote_gui.py
```

macOS GUI:

```bash
python3 scripts/macos_remote_gui.py
```

Server-only debug mode:

```powershell
python scripts\windows_remote_server.py --width 240 --height 135 --fps 6 --input-backend win32
```

## Device Setup

The setup menu opens on first boot. Hold `m` during startup to reopen it later.

| Key | Setup action |
| --- | --- |
| `W` / `S` or `;` / `.` | Up / down |
| `A` / `D` or `,` / `/` | Left / right |
| `Fn+;` / `Fn+,` / `Fn+.` / `Fn+/` | Up / left / down / right |
| `Enter` | Select or save |
| `Backspace` | Delete text |
| `Esc` | Cancel editing |

Setup flow:

1. `Scan/select WiFi`
2. Select SSID
3. Enter password
4. `Set Host IP`
5. Optional manual override if discovery is unavailable
6. Keep ports `5050/5051` unless changed in the desktop GUI
7. `Connect`

## Desktop GUI

Recommended settings:

- `Input = win32` for games and elevated windows on Windows.
- `Fast / Game` for lower latency.
- Run as Administrator on Windows when controlling games.

Other settings:

- `Input = pynput`: fallback desktop input path for macOS and Linux.
- `Host OS`: choose `windows` or `macos` so `Opt` maps correctly.
- `Balanced`: 15 FPS, bilinear scaling.
- `Stable`: 8 FPS.
- `Sharp`: 10 FPS, bicubic scaling.
- `Mouse Hz`, `Hold ms`, `Mouse scale`: game-mode mouse-look tuning.
- Video uses RGB565 keyframes plus `16x15` tile deltas to reduce LAN bandwidth on mostly static desktops.
- Discovery is automatic on UDP `5052`; the host probes the LAN, the Cardputer replies, and the host IP is stored after Wi-Fi joins.
- On macOS, the window uses the native red/yellow/green title-bar buttons and follows system dark mode when `Appearance = System`.

## Controls

### Keyboard Mode

Default mode.

| Cardputer-Adv key | Host output |
| --- | --- |
| Letters, numbers, punctuation | Same key |
| `Space`, `Tab`, `Enter`, `Backspace` | Same key |
| `Ctrl`, `Shift`, `Alt` | Same modifier |
| `Opt` | Win key on Windows, Option on macOS |
| `Fn+;` / `Fn+,` / `Fn+.` / `Fn+/` | Up / left / down / right |
| `Fn+M` | Toggle mouse mode |
| `Fn+G` | Toggle game mode |

### Mouse Mode

Desktop pointer mode. The host bridge draws a crosshair in the stream while this mode is active.

| Cardputer-Adv key | Mouse action |
| --- | --- |
| `Fn+M` | Toggle mouse mode |
| `;` / `.` / `,` / `/` | Move up / down / left / right |
| `Shift` while moving | Faster movement |
| `Fn+;` / `Fn+.` | Scroll up / down |
| Hold `Enter` or `Space` | Hold left button |
| `Backspace` or `Fn+Backspace` | Right button |

### Game Mode

Hidden-crosshair mouse-look mode. On Windows, use `Input = win32` and run the desktop GUI as Administrator for games; on macOS, grant Accessibility permission and use `pynput`.

| Cardputer-Adv key | Game action |
| --- | --- |
| `Fn+G` | Toggle game mode |
| `W` / `E` | Send `E` / `W` |
| `;` / `.` / `,` / `/` | Look up / down / left / right |
| Arrow layer | Look up / down / left / right |
| `L` | Left mouse button |
| `'` | Right mouse button |
| `Fn+L` / `Fn+'` | Send keyboard `L` / `'` |
| `Fn+;` / `Fn+.` | Scroll up / down |

## License

GPL-3.0. See [LICENSE](LICENSE).
