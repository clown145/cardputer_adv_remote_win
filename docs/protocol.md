# Protocol

The Cardputer opens two TCP client connections to the desktop host:

- `FRAME_PORT` default `5050`: Windows sends frames to Cardputer.
- `INPUT_PORT` default `5051`: Cardputer sends keyboard reports to Windows.

Both connections begin with an ASCII line:

```text
CARDPUTER_REMOTE FRAME 240 135\n
CARDPUTER_REMOTE INPUT 240 135\n
```

The host server rejects the connection if the channel or resolution does not match its command-line options.

## Discovery

The Cardputer and desktop host also use UDP port `5052` for automatic LAN discovery.

- The host broadcasts `CARDPUTER_REMOTE DISCOVER 1 240 135\n`.
- The Cardputer replies with `CARDPUTER_REMOTE ADV 1 240 135\n`.
- The host replies to that device with `CARDPUTER_REMOTE HOST 1 240 135 5050 5051\n`.
- The Cardputer stores the sender IP plus frame/input ports when it receives a valid host offer.

## Frame Stream

All multi-byte fields are little-endian.

```c
struct FrameHeader {
    uint32_t magic;       // 0x41575243, "CRWA"
    uint16_t version;     // 1
    uint16_t width;       // default 240
    uint16_t height;      // default 135
    uint16_t format;      // 1 = RGB565 full frame, 2 = tile delta
    uint32_t frame_id;
    uint32_t payload_len;
};
```

Format `1` payload is a packed RGB565 image in little-endian byte order, directly suitable for `M5GFX::pushImage` on ESP32. It is used for the first frame, periodic keyframes, and whenever a delta would be larger than a full frame.

Format `2` payload is a tile delta stream. The host currently uses `16x15` tiles:

```c
struct TileDeltaHeader {
    uint16_t tile_count;
    uint16_t reserved;    // 0
};

struct TileHeader {
    uint16_t x;
    uint16_t y;
    uint16_t width;
    uint16_t height;
};
```

The payload starts with `TileDeltaHeader`, followed by `tile_count` tile records. Each record is `TileHeader` plus `width * height * 2` bytes of little-endian RGB565 tile data in row-major order. A delta frame with `tile_count == 0` is a no-change keepalive frame.

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

For mouse reports, `key_count & 0x80` marks the report as mouse input. `key_count & 0x08` marks mouse input as active; when that bit is clear, the host releases mouse buttons and hides the crosshair. `key_count & 0x10` keeps mouse input active while hiding the crosshair, used by game mode. The low bits of `key_count` are mouse buttons:

- bit 0: left button
- bit 1: right button
- bit 2: middle button

Mouse motion fields are signed 8-bit values stored in `keys`:

- `keys[0]`: relative X movement
- `keys[1]`: relative Y movement
- `keys[2]`: vertical wheel delta
