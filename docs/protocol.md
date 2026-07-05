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

The Cardputer sends fixed-size reports whenever the keyboard state changes, plus a periodic keepalive.

```c
struct InputReport {
    uint32_t magic;       // 0x41575243, "CRWA"
    uint16_t version;     // 1
    uint16_t sequence;
    uint8_t modifiers;    // USB HID modifier bitmap
    uint8_t key_count;    // 0..6
    uint8_t keys[6];      // USB HID key codes
};
```

`modifiers` follows the USB HID keyboard bitmap:

- bit 0: left ctrl
- bit 1: left shift
- bit 2: left alt
- bit 3: left GUI
- bit 4: right ctrl
- bit 5: right shift
- bit 6: right alt
- bit 7: right GUI
