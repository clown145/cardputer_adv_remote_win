# Cardputer-Adv Desktop Remote

[English documentation](README.md)

这是给 M5Stack Cardputer-Adv 用的桌面端远程控制固件和 GUI。电脑端截屏，把画面缩到 `240x135` 后用 RGB565 关键帧加 tile delta 发给 Cardputer-Adv；Cardputer-Adv 显示画面，并把键盘/鼠标控制发回电脑端。

只建议在可信局域网使用。

## 使用

1. 从最新 Release 下载文件。
2. 把 `cardputer_adv_remote_win_merged.bin` 刷到 Cardputer-Adv 的 `0x0` 地址。
3. 运行桌面端程序（Windows 用 `cardputer_adv_remote_win.exe`，macOS 用 `cardputer_adv_remote_macos.app`）。
4. GUI 里选择和桌面系统匹配的输入后端（Windows 用 `win32`，macOS/Linux 用 `pynput`），设置显示器、FPS、模式，然后点 `Start`。
5. Cardputer-Adv 上扫描 Wi-Fi，输入 Wi-Fi 密码，然后连接。桌面端会在局域网里自动广播自己的 IP，Cardputer 会自动保存。

如果 Cardputer-Adv 不能自动进下载模式，按住背面的 `BtnG0`，点按 `BtnRST`，继续按住 `BtnG0` 大约一秒后松开，再刷。

## 构建

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

macOS GUI：

```bash
python3 scripts/macos_remote_gui.py
```

只运行服务端脚本调试：

```powershell
python scripts\windows_remote_server.py --width 240 --height 135 --fps 6 --input-backend win32
```

## 设备设置

第一次开机会自动进入设置菜单。之后开机时按住 `m` 可以重新进入。

| 按键 | 设置菜单动作 |
| --- | --- |
| `W` / `S` 或 `;` / `.` | 上 / 下 |
| `A` / `D` 或 `,` / `/` | 左 / 右 |
| `Fn+;` / `Fn+,` / `Fn+.` / `Fn+/` | 上 / 左 / 下 / 右 |
| `Enter` | 选择或保存 |
| `Backspace` | 删除文本 |
| `Esc` | 取消编辑 |

设置流程：

1. `Scan/select WiFi`
2. 选择 SSID
3. 输入密码
4. `Set Host IP`
5. 发现不可用时才手动覆盖
6. 端口默认 `5050/5051`，除非桌面 GUI 里也改了
7. `Connect`

## 桌面 GUI

推荐设置：

- Windows 上游戏和管理员窗口用 `Input = win32`。
- 想低延迟用 `Fast / Game`。
- Windows 上控制游戏时用管理员权限运行 GUI。

其他设置：

- `Input = pynput`：macOS 和 Linux 的桌面输入备用路径。
- `Host OS`：选 `windows` 或 `macos`，这样 `Opt` 映射才会对。
- `Balanced`：15 FPS，bilinear 缩放。
- `Stable`：8 FPS。
- `Sharp`：10 FPS，bicubic 缩放。
- `Mouse Hz`、`Hold ms`、`Mouse scale`：游戏模式鼠标视角参数。
- 视频流使用 RGB565 关键帧加 `16x15` tile delta，桌面大部分静止时能减少局域网带宽。
- 发现功能默认开启，使用 UDP `5052` 由电脑主动探测局域网，Cardputer 响应后会自动保存主机 IP。
- macOS 上会使用系统原生红黄绿窗口按钮，并在 `Appearance = System` 时跟随系统深色模式。

## 控制

### 键盘模式

默认模式。

| Cardputer-Adv 按键 | 主机输出 |
| --- | --- |
| 字母、数字、标点 | 相同按键 |
| `Space`、`Tab`、`Enter`、`Backspace` | 相同按键 |
| `Ctrl`、`Shift`、`Alt` | 相同修饰键 |
| `Opt` | Windows 键（macOS 上是 Option） |
| `Fn+;` / `Fn+,` / `Fn+.` / `Fn+/` | 上 / 左 / 下 / 右 |
| `Fn+M` | 切换鼠标模式 |
| `Fn+G` | 切换游戏模式 |

### 鼠标模式

桌面鼠标模式。进入这个模式后，主机会在画面里画十字线标出鼠标位置。

| Cardputer-Adv 按键 | 鼠标动作 |
| --- | --- |
| `Fn+M` | 切换鼠标模式 |
| `;` / `.` / `,` / `/` | 上 / 下 / 左 / 右移动 |
| 移动时按住 `Shift` | 更快移动 |
| `Fn+;` / `Fn+.` | 向上 / 向下滚轮 |
| 按住 `Enter` 或 `Space` | 按住左键 |
| `Backspace` 或 `Fn+Backspace` | 右键 |

### 游戏模式

隐藏十字线的鼠标视角模式。Windows 上游戏里用 `Input = win32`，桌面 GUI 用管理员权限运行；macOS 上授予 Accessibility 权限并使用 `pynput`。

| Cardputer-Adv 按键 | 游戏动作 |
| --- | --- |
| `Fn+G` | 切换游戏模式 |
| `W` / `E` | 发送 `E` / `W` |
| `;` / `.` / `,` / `/` | 视角上 / 下 / 左 / 右 |
| 方向键层 | 视角上 / 下 / 左 / 右 |
| `L` | 鼠标左键 |
| `'` | 鼠标右键 |
| `Fn+L` / `Fn+'` | 发送键盘 `L` / `'` |
| `Fn+;` / `Fn+.` | 向上 / 向下滚轮 |

## 协议

GPL-3.0。见 [LICENSE](LICENSE)。
