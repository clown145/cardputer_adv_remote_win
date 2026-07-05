# Protocol

The Cardputer opens two TCP client connections to the Windows host:

- `FRAME_PORT` default `5050`: Windows sends frames to Cardputer.
- `INPUT_PORT` default `5051`: Cardputer sends keyboard reports to Windows.

Both connections begin with an ASCII line:

```text
CARDPUTER_REMOTE FRAME 240 135\n
CARDPUTER_REMOTE INPUT 240 135\n
```

The Windows server rejects the connection if the channel or resolution does not match its command-line options.

## Frame Stream

All multi-byte fields are little-endian.

```c
struct FrameHeader {
    uint32_t magic;       // 0x41575243, "CRWA"
    uint16_t version;     // 1
    uint16_t width;       // default 240
    uint16_t height;      // default 135
    uint16_t format;      // 1 = RGB565 little-endian
    uint32_t frame_id;
    uint32_t payload_len; // width * height * 2
};
```

Payload is a packed RGB565 image in little-endian byte order, directly suitable for `M5GFX::pushImage` on ESP32.

## Input Stream

The Cardputer sends fixed-size input reports whenever keyboard state changes, whenever mouse motion/button state is active, plus a periodic keepalive. Keyboard reports remain compatible with protocol version 1. Mouse reports use input protocol version 2.

```c
struct InputReport {
    uint32_t magic;       // 0x41575243, "CRWA"
    uint16_t version;     // 1 for keyboard-only, 2 for keyboard/mouse
    uint16_t sequence;
    uint8_t modifiers;    // Keyboard: USB HID modifier bitmap. Mouse: reserved.
    uint8_t key_count;    // Keyboard: 0..6. Mouse: 0x80 | button bits.
    uint8_t keys[6];      // Keyboard: USB HID key codes. Mouse: dx, dy, wheel, reserved...
};
```

For keyboard reports, `modifiers` follows the USB HID keyboard bitmap:

- bit 0: left ctrl
- bit 1: left shift
- bit 2: left alt
- bit 3: left GUI
- bit 4: right ctrl
- bit 5: right shift
- bit 6: right alt
- bit 7: right GUI

For mouse reports, `key_count & 0x80` marks the report as mouse input. `key_count & 0x08` marks mouse mode as active; when that bit is clear, the host releases mouse buttons and hides the crosshair. The low bits of `key_count` are mouse buttons:

- bit 0: left button
- bit 1: right button
- bit 2: middle button

Mouse motion fields are signed 8-bit values stored in `keys`:

- `keys[0]`: relative X movement
- `keys[1]`: relative Y movement
- `keys[2]`: vertical wheel delta
