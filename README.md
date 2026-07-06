# Cardputer-Adv Windows Remote

Cardputer-Adv Windows Remote turns an M5Stack Cardputer-Adv into a tiny Wi-Fi remote controller for a Windows PC. The native C++ firmware receives a low-resolution live screen stream from Windows, shows it on the Cardputer display, and sends keyboard/mouse reports back to the Windows bridge.

It is useful when you want a pocket remote keyboard, emergency desktop access, a tiny game helper, or a small wireless terminal controller. It is not a secure RDP/VNC replacement: the stream is raw RGB565 over TCP, there is no encryption or authentication, and it should only be used on a trusted LAN.

## What It Does

- Streams the selected Windows monitor to the Cardputer-Adv screen at `240x135`.
- Lets you configure Wi-Fi, Windows IP, and ports directly on the Cardputer-Adv.
- Saves device configuration in ESP32 NVS under `remote_cfg`; nothing is stored in the flash root.
- Saves Windows GUI settings in `%APPDATA%\CardputerAdvRemote\settings.json`.
- Sends most Cardputer keys as keyboard input to Windows.
- Maps `Opt` to the Windows key by default.
- Provides keyboard mode, mouse mode, and game mode.
- Provides a Windows GUI exe with a UAC administrator manifest for better game/elevated-window input compatibility.

## Downloaded Release Files

GitHub Releases publish raw files, not zip bundles:

- `cardputer_adv_remote_win.exe`: Windows GUI bridge.
- `cardputer_adv_remote_win.exe.sha256`: SHA-256 checksum for the exe.
- `cardputer_adv_remote_win_merged.bin`: merged `0x0` flashable Cardputer-Adv firmware.
- `cardputer_adv_remote_win_merged.bin.sha256`: SHA-256 checksum for the firmware.

The regular `Build` workflow still provides CI artifacts for debugging, but releases are the preferred way to download end-user files.

## Quick Start

1. Download `cardputer_adv_remote_win.exe` and `cardputer_adv_remote_win_merged.bin` from a GitHub Release.
2. Flash `cardputer_adv_remote_win_merged.bin` to the Cardputer-Adv at address `0x0`.
3. Run `cardputer_adv_remote_win.exe` on Windows and accept the UAC prompt.
4. In the GUI, choose the stream mode, FPS, monitor, and `Input = win32`, then click `Start`.
5. On the Cardputer-Adv, scan/select Wi-Fi, enter the Wi-Fi password, enter the Windows PC LAN IP shown by the GUI, and connect.

Cardputer-Adv uses native USB on ESP32-S3. If upload cannot enter bootloader automatically, hold `BtnG0`, tap `BtnRST`, keep holding `BtnG0` for about one second, then release it and flash again.

## Build From Source

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

Direct server mode is still available for debugging:

```powershell
python scripts\windows_remote_server.py --width 240 --height 135 --fps 6
python scripts\windows_remote_server.py --input-backend win32
```

## Device Setup

On first boot, the setup menu opens automatically. On later boots, hold `M` during startup to reopen setup.

Setup menu controls:

| Key | Action |
| --- | --- |
| `;` / `.` | Move up/down |
| `,` / `/` | Move left/right where supported |
| `Fn+;` / `Fn+,` / `Fn+.` / `Fn+/` | Arrow layer: up/left/down/right |
| `Enter` | Select or save text |
| `Backspace` | Delete while editing text |
| `Esc` | Cancel text editing |

Setup steps:

1. Choose `Scan/select WiFi`.
2. Select your SSID.
3. Type the Wi-Fi password. `Aa`/shift input is supported, so mixed-case passwords work.
4. Choose `Set Windows IP`.
5. Enter the Windows PC LAN IP shown in the GUI, for example `192.168.1.100`.
6. Keep ports at `5050/5051` unless you also change them in the Windows GUI.
7. Choose `Connect`.

## Windows GUI

The GUI can adjust stream mode, FPS, monitor, scaling filter, ports, input backend, and game mouse tuning.

Important options:

- `Input = win32`: recommended. Uses Win32 `SendInput` with keyboard scancodes. Use this for games and elevated apps.
- `Input = pynput`: fallback path for normal desktop control if Win32 input is not wanted.
- `Fast / Game`: 30 FPS, nearest scaling, lower latency.
- `Balanced`: 15 FPS, bilinear scaling.
- `Stable`: 8 FPS, useful on weak Wi-Fi.
- `Sharp`: 10 FPS, bicubic scaling.
- `Mouse Hz`, `Hold ms`, `Mouse scale`: hidden-crosshair game mouse-look tuning. These only affect game mode mouse-look.

Allow the GUI through Windows Defender Firewall for private networks. Run it as Administrator if you need games or elevated windows to receive input.

## Control Modes

### Keyboard Mode

This is the default mode. Most physical keys are sent as keyboard reports.

| Cardputer-Adv key | Windows output |
| --- | --- |
| Letters/numbers/punctuation | Same key |
| `Space`, `Tab`, `Enter`, `Backspace` | Same key |
| `Ctrl`, `Shift`, `Alt` | Same modifier |
| `Opt` | Windows key |
| `Fn+;` / `Fn+,` / `Fn+.` / `Fn+/` | Up / Left / Down / Right |
| `Fn` layer F-keys, Escape, Delete | As exposed by the M5Cardputer library |
| `Fn+M` | Toggle mouse mode |
| `Fn+G` | Toggle game mode |

### Mouse Mode

Mouse mode is for controlling the Windows desktop. The Windows bridge draws a black/white/black crosshair over the streamed frame to show the current pointer location.

| Cardputer-Adv key | Mouse action |
| --- | --- |
| `Fn+M` | Toggle mouse mode |
| `;` | Move up |
| `.` | Move down |
| `,` | Move left |
| `/` | Move right |
| `Shift` while moving | Faster movement |
| `Fn+;` | Scroll up |
| `Fn+.` | Scroll down |
| Hold `Enter` or `Space` | Hold left button; move while held to drag |
| `Backspace` or `Fn+Backspace` | Right button |

### Game Mode

Game mode hides the crosshair and treats direction keys as mouse-look. Use it with `Input = win32` and the Windows GUI running as Administrator.

| Cardputer-Adv key | Game-mode action |
| --- | --- |
| `Fn+G` | Toggle game mode |
| Physical `W` | Sends `E` |
| Physical `E` | Sends `W` |
| `;` or arrow up | Look up |
| `.` or arrow down | Look down |
| `,` or arrow left | Look left |
| `/` or arrow right | Look right |
| `L` | Left mouse button |
| `'` | Right mouse button |
| `Fn+L` | Send literal keyboard `L` |
| `Fn+'` | Send literal keyboard `'` |
| `Fn+;` | Scroll up |
| `Fn+.` | Scroll down |

The `GAME` and `MOUSE` badges only appear briefly after toggling modes.

## Release Workflow

The `Release` workflow publishes raw release assets. To create a release:

```bash
git tag v0.1.0
git push origin v0.1.0
```

The workflow builds the firmware and Windows GUI, creates or updates the GitHub Release for the tag, and uploads:

- `cardputer_adv_remote_win.exe`
- `cardputer_adv_remote_win.exe.sha256`
- `cardputer_adv_remote_win_merged.bin`
- `cardputer_adv_remote_win_merged.bin.sha256`

No zip file is attached to the release.

## Project Layout

- `src/main.cpp`: Arduino/PlatformIO firmware for Cardputer-Adv.
- `scripts/windows_remote_server.py`: Windows capture and input bridge.
- `scripts/windows_remote_gui.py`: Windows GUI control panel.
- `scripts/requirements-windows.txt`: Python dependencies for the Windows bridge.
- `docs/protocol.md`: wire protocol details.

## Troubleshooting

- If the Cardputer opens setup on boot, complete Wi-Fi and Windows IP on the device.
- If it shows `Waiting for Windows host`, confirm the Windows GUI is running, the saved Windows IP is correct, and the firewall allows inbound TCP ports `5050` and `5051`.
- If keys do nothing, set `Input = win32`, run the GUI as Administrator, and focus a simple text window first.
- If games receive clicks but not keyboard input, run the GUI as Administrator.
- If game camera look does not move, confirm `Input = win32` and try `Fast / Game`; some games filter injected mouse input differently from desktop pointer movement.
- If the screen is garbled or rejected, make sure the Windows bridge uses `240x135`.
- If upload fails on Cardputer-Adv, use the back-side `BtnG0` + `BtnRST` bootloader sequence.

## License

This project is licensed under the GNU General Public License v3.0. See `LICENSE`.

---

# Cardputer-Adv Windows Remote 中文说明

Cardputer-Adv Windows Remote 可以把 M5Stack Cardputer-Adv 变成一个无线控制 Windows 电脑的小终端。原生 C++ 固件会接收 Windows 端发来的低分辨率实时画面，在 Cardputer 屏幕上显示，并把 Cardputer 键盘和鼠标控制数据发回 Windows。

它适合做口袋远程键盘、应急桌面控制、小型游戏辅助控制器，或者无线终端控制器。它不是安全版 RDP/VNC：画面是 TCP 上的原始 RGB565 数据，没有加密和认证，只建议在可信局域网里使用。

## 这个固件有什么用

- 把 Windows 选中的显示器画面串流到 Cardputer-Adv，默认分辨率 `240x135`。
- Wi-Fi、Windows IP、端口都可以直接在 Cardputer-Adv 上配置。
- 设备配置保存在 ESP32 NVS 的 `remote_cfg` 命名空间，不放在 flash 根目录。
- Windows GUI 配置保存在 `%APPDATA%\CardputerAdvRemote\settings.json`。
- 大部分 Cardputer 按键会转成 Windows 键盘输入。
- `Opt` 默认映射成 Windows 键。
- 支持键盘模式、鼠标模式、游戏模式。
- Windows GUI exe 带 UAC 管理员权限清单，更容易被游戏和管理员窗口识别。

## Release 下载文件

GitHub Release 发布的是裸文件，不是 zip 压缩包：

- `cardputer_adv_remote_win.exe`：Windows GUI 桥接程序。
- `cardputer_adv_remote_win.exe.sha256`：exe 的 SHA-256 校验。
- `cardputer_adv_remote_win_merged.bin`：从 `0x0` 刷入的合并固件。
- `cardputer_adv_remote_win_merged.bin.sha256`：固件的 SHA-256 校验。

普通 `Build` 工作流仍然会保留 CI artifact 用于调试，但最终用户建议从 Release 下载。

## 快速使用

1. 从 GitHub Release 下载 `cardputer_adv_remote_win.exe` 和 `cardputer_adv_remote_win_merged.bin`。
2. 把 `cardputer_adv_remote_win_merged.bin` 刷到 Cardputer-Adv 的 `0x0` 地址。
3. 在 Windows 上运行 `cardputer_adv_remote_win.exe`，同意 UAC 弹窗。
4. 在 GUI 里选择画面模式、FPS、显示器，并确认 `Input = win32`，然后点 `Start`。
5. 在 Cardputer-Adv 上扫描/选择 Wi-Fi，输入 Wi-Fi 密码，再输入 GUI 显示的 Windows 电脑局域网 IP，最后连接。

Cardputer-Adv 是 ESP32-S3 原生 USB。如果自动进不了下载模式，按住背面的 `BtnG0`，点按 `BtnRST`，继续按住 `BtnG0` 大约一秒后松开，再重新刷写。

## 从源码构建

固件：

```bash
python -m pip install platformio
pio run -e cardputer_adv
pio run -e cardputer_adv -t upload
```

Windows GUI：

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r scripts\requirements-windows.txt
python scripts\windows_remote_gui.py
```

也可以直接运行服务端脚本用于调试：

```powershell
python scripts\windows_remote_server.py --width 240 --height 135 --fps 6
python scripts\windows_remote_server.py --input-backend win32
```

## 设备端配置

第一次开机会自动进入设置菜单。之后如果想重新设置，开机时按住 `M`。

设置菜单按键：

| 按键 | 作用 |
| --- | --- |
| `;` / `.` | 上/下移动 |
| `,` / `/` | 在支持的界面里左/右移动 |
| `Fn+;` / `Fn+,` / `Fn+.` / `Fn+/` | 方向键层：上/左/下/右 |
| `Enter` | 选择或保存文本 |
| `Backspace` | 编辑文本时删除 |
| `Esc` | 取消文本编辑 |

设置步骤：

1. 选择 `Scan/select WiFi`。
2. 选择你的 SSID。
3. 输入 Wi-Fi 密码。支持 `Aa`/Shift 输入，所以大小写密码可以正常输入。
4. 选择 `Set Windows IP`。
5. 输入 GUI 显示的 Windows 电脑局域网 IP，例如 `192.168.1.100`。
6. 端口默认保持 `5050/5051`，除非你也改了 Windows GUI 里的端口。
7. 选择 `Connect`。

## Windows GUI

GUI 可以调整画面模式、FPS、显示器、缩放滤镜、端口、输入后端和游戏鼠标参数。

重要选项：

- `Input = win32`：推荐。使用 Win32 `SendInput` 和键盘 scancode。游戏和管理员窗口用这个。
- `Input = pynput`：普通桌面控制的备用输入路径。
- `Fast / Game`：30 FPS，nearest 缩放，延迟更低。
- `Balanced`：15 FPS，bilinear 缩放。
- `Stable`：8 FPS，Wi-Fi 较差时使用。
- `Sharp`：10 FPS，bicubic 缩放。
- `Mouse Hz`、`Hold ms`、`Mouse scale`：游戏模式隐藏准星时的鼠标视角参数，只影响游戏模式。

首次运行时允许 Windows Defender 防火墙放行专用网络。需要控制游戏或管理员窗口时，请用管理员权限运行 GUI。

## 控制模式

### 键盘模式

默认就是键盘模式。大部分物理按键会直接发成键盘输入。

| Cardputer-Adv 按键 | Windows 输出 |
| --- | --- |
| 字母/数字/标点 | 相同按键 |
| `Space`、`Tab`、`Enter`、`Backspace` | 相同按键 |
| `Ctrl`、`Shift`、`Alt` | 相同修饰键 |
| `Opt` | Windows 键 |
| `Fn+;` / `Fn+,` / `Fn+.` / `Fn+/` | 上 / 左 / 下 / 右 |
| `Fn` 层的 F 键、Escape、Delete | 按 M5Cardputer 库暴露的按键发送 |
| `Fn+M` | 切换鼠标模式 |
| `Fn+G` | 切换游戏模式 |

### 鼠标模式

鼠标模式用于控制 Windows 桌面。Windows 端会在传回来的画面上画黑/白/黑十字线，标出当前鼠标位置。

| Cardputer-Adv 按键 | 鼠标动作 |
| --- | --- |
| `Fn+M` | 切换鼠标模式 |
| `;` | 上移 |
| `.` | 下移 |
| `,` | 左移 |
| `/` | 右移 |
| 移动时按住 `Shift` | 更快移动 |
| `Fn+;` | 向上滚轮 |
| `Fn+.` | 向下滚轮 |
| 按住 `Enter` 或 `Space` | 按住左键；同时移动就是拖动 |
| `Backspace` 或 `Fn+Backspace` | 右键 |

### 游戏模式

游戏模式会隐藏十字线，把方向键当成鼠标视角控制。建议配合 `Input = win32`，并以管理员权限运行 Windows GUI。

| Cardputer-Adv 按键 | 游戏模式动作 |
| --- | --- |
| `Fn+G` | 切换游戏模式 |
| 物理 `W` | 发送 `E` |
| 物理 `E` | 发送 `W` |
| `;` 或方向上 | 视角上移 |
| `.` 或方向下 | 视角下移 |
| `,` 或方向左 | 视角左移 |
| `/` 或方向右 | 视角右移 |
| `L` | 鼠标左键 |
| `'` | 鼠标右键 |
| `Fn+L` | 发送键盘 `L` |
| `Fn+'` | 发送键盘 `'` |
| `Fn+;` | 向上滚轮 |
| `Fn+.` | 向下滚轮 |

`GAME` 和 `MOUSE` 角标只会在切换模式后短暂显示。

## 发版工作流

`Release` 工作流会发布裸文件。创建 release 的方式：

```bash
git tag v0.1.0
git push origin v0.1.0
```

工作流会构建固件和 Windows GUI，为这个 tag 创建或更新 GitHub Release，并上传：

- `cardputer_adv_remote_win.exe`
- `cardputer_adv_remote_win.exe.sha256`
- `cardputer_adv_remote_win_merged.bin`
- `cardputer_adv_remote_win_merged.bin.sha256`

Release 里不会附带 zip 压缩包。

## 项目结构

- `src/main.cpp`：Cardputer-Adv 的 Arduino/PlatformIO 固件。
- `scripts/windows_remote_server.py`：Windows 截屏和输入桥。
- `scripts/windows_remote_gui.py`：Windows GUI 控制面板。
- `scripts/requirements-windows.txt`：Windows 桥接程序依赖。
- `docs/protocol.md`：通信协议说明。

## 排查问题

- 如果 Cardputer 开机进入设置界面，先完成 Wi-Fi 和 Windows IP 配置。
- 如果显示 `Waiting for Windows host`，确认 Windows GUI 正在运行、保存的 Windows IP 正确，并且防火墙允许 TCP `5050` 和 `5051` 入站。
- 如果按键完全没反应，确认 `Input = win32`，用管理员权限运行 GUI，并先聚焦一个普通文本窗口测试。
- 如果游戏能点鼠标但键盘不进游戏，通常是 GUI 没有管理员权限。
- 如果游戏视角不动，确认 `Input = win32` 并试试 `Fast / Game`；有些游戏对注入鼠标输入和桌面鼠标移动的处理不同。
- 如果画面花屏或被拒绝，确认 Windows 端分辨率是 `240x135`。
- 如果 Cardputer-Adv 上传失败，使用背面的 `BtnG0` + `BtnRST` 下载模式流程。

## 协议

本项目使用 GNU General Public License v3.0。详见 `LICENSE`。
