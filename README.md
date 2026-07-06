# Cardputer-Adv Windows Remote

[Chinese documentation](README.zh-CN.md)

Native firmware and a Windows GUI bridge for using an M5Stack Cardputer-Adv as a tiny Wi-Fi remote controller for a Windows PC.

The Windows app captures the screen, downscales it to `240x135`, streams RGB565 frames to the Cardputer-Adv, and injects keyboard/mouse input sent back by the device. Use it only on a trusted LAN.

## Use

1. Download the latest release assets.
2. Flash `cardputer_adv_remote_win_merged.bin` to the Cardputer-Adv at address `0x0`.
3. Run `cardputer_adv_remote_win.exe` on Windows and accept the UAC prompt.
4. In the GUI, set `Input = win32`, choose monitor/FPS/mode, then click `Start`.
5. On the Cardputer-Adv, scan Wi-Fi, enter the Wi-Fi password, enter the Windows LAN IP shown by the GUI, then connect.

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

Server-only debug mode:

```powershell
python scripts\windows_remote_server.py --width 240 --height 135 --fps 6 --input-backend win32
```

## Device Setup

The setup menu opens on first boot. Hold `M` during startup to reopen it later.

| Key | Setup action |
| --- | --- |
| `;` / `.` | Up / down |
| `,` / `/` | Left / right |
| `Fn+;` / `Fn+,` / `Fn+.` / `Fn+/` | Up / left / down / right |
| `Enter` | Select or save |
| `Backspace` | Delete text |
| `Esc` | Cancel editing |

Setup flow:

1. `Scan/select WiFi`
2. Select SSID
3. Enter password
4. `Set Windows IP`
5. Enter the PC LAN IP
6. Keep ports `5050/5051` unless changed in the Windows GUI
7. `Connect`

## Windows GUI

Recommended settings:

- `Input = win32` for games and elevated windows.
- `Fast / Game` for lower latency.
- Run as Administrator when controlling games.

Other settings:

- `Input = pynput`: fallback desktop input path.
- `Balanced`: 15 FPS, bilinear scaling.
- `Stable`: 8 FPS.
- `Sharp`: 10 FPS, bicubic scaling.
- `Mouse Hz`, `Hold ms`, `Mouse scale`: game-mode mouse-look tuning.

## Controls

### Keyboard Mode

Default mode.

| Cardputer-Adv key | Windows output |
| --- | --- |
| Letters, numbers, punctuation | Same key |
| `Space`, `Tab`, `Enter`, `Backspace` | Same key |
| `Ctrl`, `Shift`, `Alt` | Same modifier |
| `Opt` | Windows key |
| `Fn+;` / `Fn+,` / `Fn+.` / `Fn+/` | Up / left / down / right |
| `Fn+M` | Toggle mouse mode |
| `Fn+G` | Toggle game mode |

### Mouse Mode

Desktop pointer mode. The Windows bridge draws a crosshair in the stream while this mode is active.

| Cardputer-Adv key | Mouse action |
| --- | --- |
| `Fn+M` | Toggle mouse mode |
| `;` / `.` / `,` / `/` | Move up / down / left / right |
| `Shift` while moving | Faster movement |
| `Fn+;` / `Fn+.` | Scroll up / down |
| Hold `Enter` or `Space` | Hold left button |
| `Backspace` or `Fn+Backspace` | Right button |

### Game Mode

Hidden-crosshair mouse-look mode. Use `Input = win32`; run the Windows GUI as Administrator for games.

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

## Release

Create a tag to publish a release:

```bash
git tag v0.1.0
git push origin v0.1.0
```

The `Release` workflow uploads the exe, firmware bin, and their `.sha256` files directly to the GitHub Release. It does not attach zip files.

## License

GPL-3.0. See [LICENSE](LICENSE).
