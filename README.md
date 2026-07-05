# Cardputer-Adv Windows Remote

C++ native firmware for M5Stack Cardputer-Adv plus a Windows-side Python bridge. The Windows bridge captures the screen, downscales it to the Cardputer display, streams RGB565 frames over Wi-Fi, and injects keyboard events received from the Cardputer keyboard.

This is a practical first version, not a full RDP/VNC replacement. Expect low-resolution remote control around 3-10 FPS depending on Wi-Fi and host load. It is best for terminals, dialogs, simple desktop control, and emergency "tiny remote keyboard plus screen" use.

## Project Layout

- `src/main.cpp` - Arduino/PlatformIO firmware for Cardputer-Adv.
- `scripts/windows_remote_server.py` - Windows capture and keyboard injection service.
- `scripts/requirements-windows.txt` - Python dependencies for the Windows service.
- `docs/protocol.md` - wire protocol details.

## Firmware Setup

1. Install PlatformIO.

   ```powershell
   python -m pip install platformio
   ```

2. Build and upload.

   ```bash
   pio run -e cardputer_adv
   pio run -e cardputer_adv -t upload
   ```

Cardputer-Adv uses native USB on ESP32-S3. If upload cannot enter bootloader automatically, hold `BtnG0`, tap `BtnRST`, keep holding `BtnG0` for about one second, then release it and run upload again.

## Device Setup

Configuration is entered on the Cardputer-Adv itself and saved in ESP32 NVS under the `remote_cfg` namespace. You do not edit a firmware header to change Wi-Fi or Windows IP.

On first boot, the setup menu opens automatically. On later boots, hold `M` during startup to reopen setup.

Menu controls:

- `;` / `.`: move up/down in menus.
- `,` / `/`: left/right direction keys where a screen uses them.
- Fn-arrow keys also work as arrows.
- `Enter`: select or save text.
- `Backspace`: delete text while editing.
- `Esc`: cancel text editing.

Setup steps:

1. Choose `Scan/select WiFi`, select your SSID, then type the Wi-Fi password.
2. Choose `Set Windows IP`, then type the Windows PC LAN IP, for example `192.168.1.100`.
3. Keep ports at `5050/5051` unless you also change the Windows server command.
4. Choose `Connect`.

## Windows Setup

Run these commands in PowerShell on the Windows PC:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r scripts\requirements-windows.txt
python scripts\windows_remote_server.py --width 240 --height 135 --fps 6
```

Allow the Python process through Windows Defender Firewall for private networks. Run PowerShell as Administrator if you need to control elevated windows.

Useful options:

```powershell
python scripts\windows_remote_server.py --monitor 1 --fps 8
python scripts\windows_remote_server.py --bind 192.168.1.100 --frame-port 5050 --input-port 5051
python scripts\windows_remote_server.py --width 240 --height 135 --quality-filter nearest
```

The firmware and server resolutions must match. The default is `240x135`, which fits the Cardputer landscape screen while keeping bandwidth modest.

While mouse mode is active, the Windows server draws the current mouse position into each frame as a full-screen crosshair: black/white/black vertical and horizontal pixel lines.

## Wi-Fi Behavior

On boot, the firmware loads the saved SSID/password from device NVS and connects automatically. To change Wi-Fi, hold `M` during startup, scan again, and save the new network.

## Controls

Most physical keys are sent as USB HID-style keyboard reports:

- Regular letters, numbers, punctuation, Space, Tab, Enter, Backspace.
- `Fn` layer for arrows, Escape, Delete, and F1-F12 as exposed by the M5Cardputer library. On Cardputer-Adv, `Fn+;`, `Fn+,`, `Fn+.`, and `Fn+/` are up/left/down/right.
- Ctrl, Shift, and Alt modifiers are preserved.
- `Opt` is not mapped in this recovery build.

Mouse mode:

- `Fn+M`: toggle mouse mode.
- `;` / `.` / `,` / `/`: move the pointer up/down/left/right.
- `Fn+;` / `Fn+.`: scroll up/down unless a mouse button is held.
- Hold `Enter` or Space while moving: left mouse button drag.
- Backspace or `Fn+Backspace`: right mouse button.

## Troubleshooting

- If the Cardputer opens setup on boot, complete Wi-Fi and Windows IP on the device.
- If the Cardputer shows "Waiting for Windows host", confirm the Windows script is running, the saved Windows IP is correct, and the PC firewall allows inbound TCP ports `5050` and `5051`.
- If the display connects but keys do nothing, run the Windows script as Administrator and focus a normal text window first. The input connection times out and reconnects automatically if the Cardputer reboots.
- If the screen is garbled or rejected, make sure the Windows server uses `--width 240 --height 135`.
- If upload fails on Cardputer-Adv, use the back-side `BtnG0` + `BtnRST` bootloader sequence described above.

## Current Limitations

- No encryption or authentication. Use only on a trusted LAN.
- Screen stream is raw RGB565 over TCP, so it favors simplicity over bandwidth.
- Only one Cardputer client is served at a time.
