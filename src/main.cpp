#include <Arduino.h>
#include <M5Cardputer.h>
#include <Preferences.h>
#include <WiFi.h>

#ifndef OPT_AS_WIN
#define OPT_AS_WIN 0
#endif

namespace {

constexpr uint16_t kDefaultFramePort = 5050;
constexpr uint16_t kDefaultInputPort = 5051;
constexpr uint16_t kFrameWidth = 240;
constexpr uint16_t kFrameHeight = 135;
constexpr uint32_t kConnectRetryMs = 3000;
constexpr uint32_t kWifiConnectTimeoutMs = 12000;
constexpr uint32_t kMenuBootWindowMs = 1800;
constexpr uint32_t kMagic = 0x41575243;  // "CRWA" little endian
constexpr uint16_t kFrameProtocolVersion = 1;
constexpr uint16_t kInputProtocolVersion = 2;
constexpr size_t kFrameBytes = kFrameWidth * kFrameHeight * sizeof(uint16_t);
constexpr uint32_t kStatusRedrawMs = 1000;
constexpr uint32_t kFrameTimeoutMs = 2500;
constexpr uint32_t kInputKeepaliveMs = 1000;
constexpr uint32_t kMouseReportIntervalMs = 25;
constexpr uint32_t kMouseWheelIntervalMs = 120;
constexpr uint8_t kMaxHidKeys = 6;
constexpr uint8_t kMouseReportFlag = 0x80;
constexpr uint8_t kMouseModeActiveFlag = 1 << 3;
constexpr uint8_t kMouseHideCrosshairFlag = 1 << 4;
constexpr uint8_t kMouseButtonLeft = 1 << 0;
constexpr uint8_t kMouseButtonRight = 1 << 1;
constexpr int8_t kMouseStep = 8;
constexpr int8_t kMouseFastStep = 18;
constexpr int8_t kGameLookStep = 16;
constexpr uint8_t kHidE = 0x08;
constexpr uint8_t kHidG = 0x0A;
constexpr uint8_t kHidL = 0x0F;
constexpr uint8_t kHidW = 0x1A;
constexpr uint8_t kHidApostrophe = 0x34;
constexpr uint8_t kHidComma = 0x36;
constexpr uint8_t kHidPeriod = 0x37;
constexpr uint8_t kHidSlash = 0x38;
constexpr uint8_t kHidSemicolon = 0x33;
constexpr uint8_t kHidArrowRight = 0x4F;
constexpr uint8_t kHidArrowLeft = 0x50;
constexpr uint8_t kHidArrowDown = 0x51;
constexpr uint8_t kHidArrowUp = 0x52;
constexpr char kConfigNamespace[] = "remote_cfg";

struct RuntimeConfig {
    String ssid;
    String password;
    String host;
    uint16_t framePort = kDefaultFramePort;
    uint16_t inputPort = kDefaultInputPort;

    bool hasWifi() const {
        return ssid.length() > 0;
    }

    bool hasHost() const {
        return host.length() > 0;
    }

    bool complete() const {
        return hasWifi() && hasHost();
    }
};

struct __attribute__((packed)) FrameHeader {
    uint32_t magic;
    uint16_t version;
    uint16_t width;
    uint16_t height;
    uint16_t format;
    uint32_t frame_id;
    uint32_t payload_len;
};

struct __attribute__((packed)) InputReport {
    uint32_t magic;
    uint16_t version;
    uint16_t sequence;
    uint8_t modifiers;
    uint8_t key_count;
    uint8_t keys[kMaxHidKeys];
};

WiFiClient frameClient;
WiFiClient inputClient;

RuntimeConfig appConfig;
uint16_t frameBuffer[kFrameWidth * kFrameHeight];
uint16_t lastSequence = 0;
uint32_t lastFrameId = 0;
uint32_t lastFrameAt = 0;
uint32_t lastInputAt = 0;
uint32_t lastConnectAttemptAt = 0;
uint32_t lastStatusAt = 0;
uint32_t lastMouseReportAt = 0;
uint32_t lastMouseWheelAt = 0;
uint8_t lastMouseButtons = 0;
bool hadFrame = false;
bool mouseMode = false;
bool mouseToggleHeld = false;
bool gameMode = false;
bool gameToggleHeld = false;
bool inputJustConnected = false;

InputReport lastReport = {};

void drawStatus(const char* line1, const char* line2 = nullptr, const char* line3 = nullptr) {
    auto& display = M5Cardputer.Display;
    display.fillScreen(TFT_BLACK);
    display.setTextColor(TFT_GREEN, TFT_BLACK);
    display.setTextSize(1);
    display.setTextDatum(top_left);
    display.setCursor(4, 4);
    display.println("Cardputer-Adv Remote");
    display.setTextColor(TFT_WHITE, TFT_BLACK);
    display.println();
    display.println(line1);
    if (line2) {
        display.println(line2);
    }
    if (line3) {
        display.println(line3);
    }
    display.println();
    display.printf("Board: %d\n", static_cast<int>(M5.getBoard()));
    display.printf("WiFi: %s\n", WiFi.isConnected() ? WiFi.localIP().toString().c_str() : "offline");
    if (WiFi.isConnected()) {
        display.printf("SSID: %s\n", WiFi.SSID().c_str());
    }
    display.printf("Host: %s\n", appConfig.host.length() ? appConfig.host.c_str() : "not set");
    display.printf("Mode: %s\n", gameMode ? "game" : (mouseMode ? "mouse" : "keyboard"));
    display.printf("Frames: %lu\n", static_cast<unsigned long>(lastFrameId));
}

void waitForKeyRelease() {
    do {
        M5Cardputer.update();
        delay(20);
    } while (M5Cardputer.Keyboard.isPressed());
}

struct KeySnapshot {
    bool enter = false;
    bool backspace = false;
    bool esc = false;
    bool up = false;
    bool left = false;
    bool down = false;
    bool right = false;
    char chars[8] = {};
    uint8_t charCount = 0;

    bool hasAction() const {
        return enter || backspace || esc || up || left || down || right || charCount > 0;
    }

    bool hasChar(char target) const {
        for (uint8_t i = 0; i < charCount; ++i) {
            if (chars[i] == target) {
                return true;
            }
        }
        return false;
    }
};

bool navUp(const KeySnapshot& key) {
    return key.up || key.hasChar(';');
}

bool navLeft(const KeySnapshot& key) {
    return key.left || key.hasChar(',');
}

bool navDown(const KeySnapshot& key) {
    return key.down || key.hasChar('.');
}

bool navRight(const KeySnapshot& key) {
    return key.right || key.hasChar('/');
}

KeySnapshot waitKeyPress() {
    waitForKeyRelease();
    while (true) {
        M5Cardputer.update();
        if (M5Cardputer.Keyboard.isPressed()) {
            auto& state = M5Cardputer.Keyboard.keysState();
            KeySnapshot key;
            key.enter = state.enter;
            key.backspace = state.backspace || state.del;
            key.esc = state.esc;
            key.up = state.up;
            key.left = state.left;
            key.down = state.down;
            key.right = state.right;
            for (const char c : state.word) {
                if (key.charCount >= sizeof(key.chars)) {
                    break;
                }
                if (c >= 32 && c <= 126) {
                    key.chars[key.charCount++] = c;
                }
            }
            if (key.hasAction()) {
                return key;
            }
        }
        delay(20);
    }
}

void drawTextInput(const char* title, const String& value, bool secret) {
    auto& display = M5Cardputer.Display;
    display.fillScreen(TFT_BLACK);
    display.setTextDatum(top_left);
    display.setTextSize(1);
    display.setTextColor(TFT_GREEN, TFT_BLACK);
    display.setCursor(4, 4);
    display.println(title);
    display.setTextColor(TFT_WHITE, TFT_BLACK);
    display.println();

    String shown = value;
    if (secret) {
        shown = "";
        for (size_t i = 0; i < value.length(); ++i) {
            shown += '*';
        }
    }
    display.println(shown.length() ? shown : "<empty>");
    display.println();
    display.setTextColor(TFT_DARKGREY, TFT_BLACK);
    display.println("Enter=save  Esc=cancel");
    display.println("Bksp=delete");
}

String editText(const char* title, const String& initial, bool secret) {
    String value = initial;
    while (true) {
        drawTextInput(title, value, secret);
        const KeySnapshot key = waitKeyPress();
        if (key.esc) {
            return initial;
        }
        if (key.enter) {
            return value;
        }
        if (key.backspace && value.length() > 0) {
            value.remove(value.length() - 1);
        }
        for (uint8_t i = 0; i < key.charCount; ++i) {
            if (value.length() < 63) {
                value += key.chars[i];
            }
        }
    }
}

void drawPrompt(const char* title, const char* line1, const char* line2 = nullptr) {
    auto& display = M5Cardputer.Display;
    display.fillScreen(TFT_BLACK);
    display.setTextDatum(top_left);
    display.setTextSize(1);
    display.setTextColor(TFT_GREEN, TFT_BLACK);
    display.setCursor(4, 4);
    display.println(title);
    display.setTextColor(TFT_WHITE, TFT_BLACK);
    display.println();
    display.println(line1);
    if (line2) {
        display.println(line2);
    }
    display.println();
    display.setTextColor(TFT_DARKGREY, TFT_BLACK);
    display.println("Press Enter");
    while (!waitKeyPress().enter) {
        delay(20);
    }
}

void loadRuntimeConfig() {
    Preferences prefs;
    if (!prefs.begin(kConfigNamespace, true)) {
        return;
    }
    appConfig.ssid = prefs.getString("ssid", "");
    appConfig.password = prefs.getString("pass", "");
    appConfig.host = prefs.getString("host", "");
    appConfig.framePort = prefs.getUShort("frame", kDefaultFramePort);
    appConfig.inputPort = prefs.getUShort("input", kDefaultInputPort);
    prefs.end();
}

void saveRuntimeConfig() {
    Preferences prefs;
    if (!prefs.begin(kConfigNamespace, false)) {
        return;
    }
    prefs.putString("ssid", appConfig.ssid);
    prefs.putString("pass", appConfig.password);
    prefs.putString("host", appConfig.host);
    prefs.putUShort("frame", appConfig.framePort);
    prefs.putUShort("input", appConfig.inputPort);
    prefs.end();
}

void clearRuntimeConfig() {
    Preferences prefs;
    if (prefs.begin(kConfigNamespace, false)) {
        prefs.clear();
        prefs.end();
    }
    appConfig = RuntimeConfig();
}

bool readExact(WiFiClient& client, uint8_t* out, size_t len, uint32_t timeoutMs) {
    size_t offset = 0;
    const uint32_t started = millis();

    while (offset < len && client.connected()) {
        const int available = client.available();
        if (available > 0) {
            const size_t want = min(static_cast<size_t>(available), len - offset);
            const int got = client.read(out + offset, want);
            if (got > 0) {
                offset += static_cast<size_t>(got);
                continue;
            }
        }

        M5Cardputer.update();
        delay(1);
        if (millis() - started > timeoutMs) {
            return false;
        }
    }

    return offset == len;
}

bool writeExact(WiFiClient& client, const uint8_t* data, size_t len) {
    size_t offset = 0;
    while (offset < len && client.connected()) {
        const size_t written = client.write(data + offset, len - offset);
        if (written == 0) {
            delay(1);
            continue;
        }
        offset += written;
    }
    return offset == len;
}

bool sendHello(WiFiClient& client, const char* channel) {
    char hello[96];
    const int n = snprintf(hello, sizeof(hello), "CARDPUTER_REMOTE %s %u %u\n", channel, kFrameWidth, kFrameHeight);
    return n > 0 && writeExact(client, reinterpret_cast<const uint8_t*>(hello), static_cast<size_t>(n));
}

bool waitForWifi(uint32_t timeoutMs) {
    const uint32_t started = millis();
    while (millis() - started < timeoutMs) {
        M5Cardputer.update();
        if (WiFi.isConnected()) {
            return true;
        }
        delay(100);
    }
    return WiFi.isConnected();
}

bool connectWifiCredential(const char* ssid, const char* password, const char* source) {
    if (!ssid || !ssid[0]) {
        return false;
    }

    WiFi.disconnect(false, false);
    delay(100);
    WiFi.begin(ssid, password);

    char line[96];
    snprintf(line, sizeof(line), "%s: %s", source, ssid);
    drawStatus("Connecting WiFi...", line);

    if (!waitForWifi(kWifiConnectTimeoutMs)) {
        WiFi.disconnect(false, false);
        return false;
    }

    drawStatus("WiFi connected", WiFi.localIP().toString().c_str(), WiFi.SSID().c_str());
    return true;
}

bool connectConfiguredWifi() {
    if (!appConfig.hasWifi()) {
        return false;
    }
    return connectWifiCredential(appConfig.ssid.c_str(), appConfig.password.c_str(), "Saved");
}

int selectScannedWifi(int networkCount) {
    int selected = 0;
    while (true) {
        auto& display = M5Cardputer.Display;
        display.fillScreen(TFT_BLACK);
        display.setTextDatum(top_left);
        display.setTextSize(1);
        display.setCursor(4, 4);
        display.setTextColor(TFT_GREEN, TFT_BLACK);
        display.println("Select WiFi");
        display.setTextColor(TFT_DARKGREY, TFT_BLACK);
        display.println(";/. or arrows, Enter");

        const int visibleRows = 8;
        int start = selected - visibleRows / 2;
        if (start < 0) {
            start = 0;
        }
        if (start > max(0, networkCount - visibleRows)) {
            start = max(0, networkCount - visibleRows);
        }

        for (int row = 0; row < visibleRows && start + row < networkCount; ++row) {
            const int index = start + row;
            display.setTextColor(index == selected ? TFT_BLACK : TFT_WHITE, index == selected ? TFT_GREEN : TFT_BLACK);
            String ssid = WiFi.SSID(index);
            if (ssid.length() > 22) {
                ssid = ssid.substring(0, 22);
            }
            display.printf("%c %-22s %d\n", index == selected ? '>' : ' ', ssid.c_str(), WiFi.RSSI(index));
        }

        const KeySnapshot key = waitKeyPress();
        if (key.esc) {
            return -1;
        }
        if (key.enter) {
            return selected;
        }
        if (navUp(key)) {
            selected = max(0, selected - 1);
        }
        if (navDown(key)) {
            selected = min(networkCount - 1, selected + 1);
        }
    }
}

void configureWifiOnDevice() {
    WiFi.mode(WIFI_STA);
    WiFi.disconnect(false, false);
    drawStatus("Scanning WiFi...", "Please wait");
    const int networkCount = WiFi.scanNetworks(false, true);
    if (networkCount <= 0) {
        WiFi.scanDelete();
        drawPrompt("WiFi", "No networks found");
        return;
    }

    const int selected = selectScannedWifi(networkCount);
    if (selected < 0) {
        WiFi.scanDelete();
        return;
    }

    const String selectedSsid = WiFi.SSID(selected);
    const bool sameSsid = selectedSsid == appConfig.ssid;
    appConfig.ssid = selectedSsid;
    WiFi.scanDelete();
    appConfig.password = editText("WiFi Password", sameSsid ? appConfig.password : "", true);
    saveRuntimeConfig();
    drawPrompt("WiFi Saved", appConfig.ssid.c_str());
}

void configureHostOnDevice() {
    appConfig.host = editText("Windows IP", appConfig.host.length() ? appConfig.host : "192.168.1.", false);
    saveRuntimeConfig();
}

uint16_t editPort(const char* title, uint16_t current) {
    const String text = editText(title, String(current), false);
    const long value = text.toInt();
    if (value <= 0 || value > 65535) {
        drawPrompt("Invalid Port", "Keeping old value");
        return current;
    }
    return static_cast<uint16_t>(value);
}

void configurePortsOnDevice() {
    appConfig.framePort = editPort("Frame Port", appConfig.framePort);
    appConfig.inputPort = editPort("Input Port", appConfig.inputPort);
    saveRuntimeConfig();
}

void drawConfigMenu(int selected) {
    static const char* items[] = {
        "Scan/select WiFi",
        "Set Windows IP",
        "Set ports",
        "Connect",
        "Clear saved config",
    };

    auto& display = M5Cardputer.Display;
    display.fillScreen(TFT_BLACK);
    display.setTextDatum(top_left);
    display.setTextSize(1);
    display.setCursor(4, 4);
    display.setTextColor(TFT_GREEN, TFT_BLACK);
    display.println("Setup");
    display.setTextColor(TFT_DARKGREY, TFT_BLACK);
    display.printf("WiFi: %s\n", appConfig.ssid.length() ? appConfig.ssid.c_str() : "not set");
    display.printf("Host: %s\n", appConfig.host.length() ? appConfig.host.c_str() : "not set");
    display.printf("Ports: %u/%u\n", appConfig.framePort, appConfig.inputPort);

    for (int i = 0; i < 5; ++i) {
        display.setTextColor(i == selected ? TFT_BLACK : TFT_WHITE, i == selected ? TFT_GREEN : TFT_BLACK);
        display.printf("%c %s\n", i == selected ? '>' : ' ', items[i]);
    }
}

void runConfigMenu() {
    int selected = 0;
    while (true) {
        drawConfigMenu(selected);
        const KeySnapshot key = waitKeyPress();
        if (navUp(key)) {
            selected = max(0, selected - 1);
        } else if (navDown(key)) {
            selected = min(4, selected + 1);
        } else if (key.enter) {
            if (selected == 0) {
                configureWifiOnDevice();
            } else if (selected == 1) {
                configureHostOnDevice();
            } else if (selected == 2) {
                configurePortsOnDevice();
            } else if (selected == 3) {
                if (appConfig.complete()) {
                    return;
                }
                drawPrompt("Not Ready", "Set WiFi and Windows IP");
            } else if (selected == 4) {
                clearRuntimeConfig();
                drawPrompt("Config Cleared", "Setup again to connect");
            }
        }
    }
}

bool bootSetupRequested() {
    drawStatus("Hold M for setup", "Auto connect starting...");
    const uint32_t started = millis();
    while (millis() - started < kMenuBootWindowMs) {
        M5Cardputer.update();
        if (M5Cardputer.Keyboard.isKeyPressed('m') || M5Cardputer.Keyboard.isKeyPressed('M')) {
            waitForKeyRelease();
            return true;
        }
        delay(50);
    }
    return false;
}

void ensureWifi() {
    if (WiFi.isConnected()) {
        return;
    }

    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);

    while (!WiFi.isConnected()) {
        if (!appConfig.complete()) {
            runConfigMenu();
        }
        if (connectConfiguredWifi()) {
            return;
        }
        drawStatus("WiFi failed", "Press Enter for setup");
        waitKeyPress();
        runConfigMenu();
    }
}

void ensureConnections() {
    if (!WiFi.isConnected()) {
        frameClient.stop();
        inputClient.stop();
        ensureWifi();
    }

    if (frameClient.connected() && inputClient.connected()) {
        return;
    }

    if (millis() - lastConnectAttemptAt < kConnectRetryMs) {
        return;
    }
    lastConnectAttemptAt = millis();

    if (!frameClient.connected()) {
        frameClient.stop();
        if (frameClient.connect(appConfig.host.c_str(), appConfig.framePort)) {
            frameClient.setNoDelay(true);
            sendHello(frameClient, "FRAME");
        }
    }

    if (!inputClient.connected()) {
        inputClient.stop();
        if (inputClient.connect(appConfig.host.c_str(), appConfig.inputPort)) {
            inputClient.setNoDelay(true);
            if (sendHello(inputClient, "INPUT")) {
                lastReport = {};
                lastInputAt = 0;
                lastMouseButtons = 0;
                inputJustConnected = true;
            } else {
                inputClient.stop();
            }
        }
    }

    if (!frameClient.connected() || !inputClient.connected()) {
        drawStatus("Waiting for Windows host", frameClient.connected() ? "Frame: ok" : "Frame: reconnect",
                   inputClient.connected() ? "Input: ok" : "Input: reconnect");
    } else {
        drawStatus("Connected to host", "Waiting for frames...");
    }
}

void drawModeBadge() {
    if ((!mouseMode && !gameMode) || !hadFrame) {
        return;
    }
    const char* label = gameMode ? "GAME" : "MOUSE";
    const uint16_t color = gameMode ? TFT_ORANGE : TFT_CYAN;
    auto& display = M5Cardputer.Display;
    display.setTextDatum(top_left);
    display.setTextSize(1);
    display.fillRect(M5Cardputer.Display.width() - 44, 0, 44, 12, TFT_BLACK);
    display.setTextColor(color, TFT_BLACK);
    display.setCursor(M5Cardputer.Display.width() - 42, 1);
    display.print(label);
}

void drawFrame() {
    const int screenW = M5Cardputer.Display.width();
    const int screenH = M5Cardputer.Display.height();
    const int x = max(0, (screenW - kFrameWidth) / 2);
    const int y = max(0, (screenH - kFrameHeight) / 2);
    const bool oldSwapBytes = M5Cardputer.Display.getSwapBytes();
    M5Cardputer.Display.setSwapBytes(true);
    M5Cardputer.Display.pushImage(x, y, kFrameWidth, kFrameHeight, frameBuffer);
    M5Cardputer.Display.setSwapBytes(oldSwapBytes);
    hadFrame = true;
    drawModeBadge();
}

void processFrameStream() {
    if (!frameClient.connected() || frameClient.available() < static_cast<int>(sizeof(FrameHeader))) {
        return;
    }

    FrameHeader header = {};
    if (!readExact(frameClient, reinterpret_cast<uint8_t*>(&header), sizeof(header), kFrameTimeoutMs)) {
        frameClient.stop();
        return;
    }

    if (header.magic != kMagic || header.version != kFrameProtocolVersion || header.width != kFrameWidth ||
        header.height != kFrameHeight || header.format != 1 || header.payload_len != kFrameBytes) {
        drawStatus("Bad frame header", "Check server resolution");
        frameClient.stop();
        return;
    }

    if (!readExact(frameClient, reinterpret_cast<uint8_t*>(frameBuffer), kFrameBytes, kFrameTimeoutMs)) {
        frameClient.stop();
        return;
    }

    lastFrameId = header.frame_id;
    lastFrameAt = millis();
    drawFrame();
}

bool keyPressed(char normal, char shifted);

InputReport makeInputReportBase() {
    InputReport report = {};
    report.magic = kMagic;
    report.version = kInputProtocolVersion;
    report.sequence = ++lastSequence;
    return report;
}

bool gameTogglePressed() {
    auto& state = M5Cardputer.Keyboard.keysState();
    return state.fn && keyPressed('g', 'G');
}

bool mouseTogglePressed() {
    auto& state = M5Cardputer.Keyboard.keysState();
    return state.fn && keyPressed('m', 'M');
}

uint8_t remapGameKey(uint8_t key) {
    if (key == kHidW) {
        return kHidE;
    }
    if (key == kHidE) {
        return kHidW;
    }
    return key;
}

bool suppressGameKeyboardKey(uint8_t key, bool suppressToggleKey) {
    if (suppressToggleKey && key == kHidG) {
        return true;
    }
    switch (key) {
        case kHidL:
        case kHidApostrophe:
        case kHidSemicolon:
        case kHidComma:
        case kHidPeriod:
        case kHidSlash:
        case kHidArrowRight:
        case kHidArrowLeft:
        case kHidArrowDown:
        case kHidArrowUp:
            return true;
        default:
            return false;
    }
}

InputReport buildKeyboardReport() {
    InputReport report = makeInputReportBase();

    auto& state = M5Cardputer.Keyboard.keysState();
    report.modifiers = state.modifiers;
#if OPT_AS_WIN
    if (state.opt) {
        report.modifiers |= (1 << 3);  // USB HID left GUI, Windows key on the PC side.
    }
#endif

    uint8_t index = 0;
    for (const uint8_t key : state.hid_keys) {
        if (index >= kMaxHidKeys) {
            break;
        }
        if (key == 0 || key >= 0x80) {
            continue;
        }
        if (gameMode) {
            if (suppressGameKeyboardKey(key, gameTogglePressed())) {
                continue;
            }
            report.keys[index++] = remapGameKey(key);
        } else {
            report.keys[index++] = key;
        }
    }
    report.key_count = index;
    return report;
}

bool sameKeys(const InputReport& a, const InputReport& b) {
    if (a.modifiers != b.modifiers || a.key_count != b.key_count) {
        return false;
    }
    for (uint8_t i = 0; i < kMaxHidKeys; ++i) {
        if (a.keys[i] != b.keys[i]) {
            return false;
        }
    }
    return true;
}

bool sendInputReport(const InputReport& report) {
    if (!inputClient.connected()) {
        return false;
    }

    if (writeExact(inputClient, reinterpret_cast<const uint8_t*>(&report), sizeof(report))) {
        lastInputAt = millis();
        return true;
    }

    inputClient.stop();
    return false;
}

void sendKeyboardReportIfNeeded(bool force = false) {
    const InputReport report = buildKeyboardReport();
    if (!force && sameKeys(report, lastReport)) {
        return;
    }

    if (sendInputReport(report)) {
        lastReport = report;
    }
}

void sendKeyboardReleaseReport() {
    const InputReport report = makeInputReportBase();
    if (sendInputReport(report)) {
        lastReport = report;
    }
}

bool sendMouseReport(int8_t dx, int8_t dy, int8_t wheel, uint8_t buttons, bool active = true, bool showCrosshair = true) {
    InputReport report = makeInputReportBase();
    report.key_count = kMouseReportFlag | (active ? kMouseModeActiveFlag : 0) |
                       (showCrosshair ? 0 : kMouseHideCrosshairFlag) | (buttons & 0x07);
    report.keys[0] = static_cast<uint8_t>(dx);
    report.keys[1] = static_cast<uint8_t>(dy);
    report.keys[2] = static_cast<uint8_t>(wheel);

    if (sendInputReport(report)) {
        lastMouseButtons = buttons;
        lastMouseReportAt = millis();
        return true;
    }
    return false;
}

bool keyPressed(char normal, char shifted) {
    return M5Cardputer.Keyboard.isKeyPressed(normal) || M5Cardputer.Keyboard.isKeyPressed(shifted);
}

void resetMouseRuntimeState() {
    lastMouseButtons = 0;
    lastMouseReportAt = 0;
    lastMouseWheelAt = 0;
}

void setMouseMode(bool enabled) {
    mouseMode = enabled;
    if (enabled) {
        gameMode = false;
    }
    resetMouseRuntimeState();
    sendKeyboardReleaseReport();
    sendMouseReport(0, 0, 0, 0, enabled);
    drawStatus(enabled ? "Mouse mode" : "Keyboard mode", enabled ? ";.,/ move  Fn+;/. wheel" : "Fn+M toggles mouse");
}

bool handleMouseToggle() {
    const bool togglePressed = mouseTogglePressed();
    const bool toggled = togglePressed && !mouseToggleHeld;
    mouseToggleHeld = togglePressed;
    if (toggled) {
        setMouseMode(!mouseMode);
    }
    return togglePressed;
}

void setGameMode(bool enabled) {
    gameMode = enabled;
    if (enabled) {
        mouseMode = false;
    }
    resetMouseRuntimeState();
    sendKeyboardReleaseReport();
    sendMouseReport(0, 0, 0, 0, enabled, false);
    drawStatus(enabled ? "Game mode" : "Keyboard mode", enabled ? ";.,/ look  L/' click" : "Fn+G toggles game");
}

bool handleGameToggle() {
    const bool togglePressed = gameTogglePressed();
    const bool toggled = togglePressed && !gameToggleHeld;
    gameToggleHeld = togglePressed;
    if (toggled) {
        setGameMode(!gameMode);
    }
    return togglePressed;
}

void processInputReconnect() {
    if (!inputJustConnected || !inputClient.connected()) {
        return;
    }
    inputJustConnected = false;
    sendKeyboardReleaseReport();
    if (mouseMode) {
        sendMouseReport(0, 0, 0, 0, true);
    } else if (gameMode) {
        sendMouseReport(0, 0, 0, 0, true, false);
    }
}

void processMouseInput() {
    if (!inputClient.connected()) {
        return;
    }

    auto& state = M5Cardputer.Keyboard.keysState();
    const uint32_t now = millis();

    uint8_t buttons = 0;
    if (state.enter || state.space) {
        buttons |= kMouseButtonLeft;
    }
    if (state.backspace || state.del) {
        buttons |= kMouseButtonRight;
    }

    const bool dragging = buttons != 0;
    const bool scrollUp = state.fn && state.up && !dragging;
    const bool scrollDown = state.fn && state.down && !dragging;
    const bool moveUp = (state.up || keyPressed(';', ':')) && !scrollUp;
    const bool moveDown = (state.down || keyPressed('.', '>')) && !scrollDown;
    const bool moveLeft = state.left || keyPressed(',', '<');
    const bool moveRight = state.right || keyPressed('/', '?');
    const int8_t step = state.shift ? kMouseFastStep : kMouseStep;

    int8_t dx = 0;
    int8_t dy = 0;
    if (moveLeft != moveRight) {
        dx = moveLeft ? -step : step;
    }
    if (moveUp != moveDown) {
        dy = moveUp ? -step : step;
    }

    if (now - lastMouseReportAt < kMouseReportIntervalMs) {
        dx = 0;
        dy = 0;
    }

    int8_t wheel = 0;
    if (scrollUp != scrollDown && now - lastMouseWheelAt >= kMouseWheelIntervalMs) {
        wheel = scrollUp ? 1 : -1;
        lastMouseWheelAt = now;
    }

    const bool buttonsChanged = buttons != lastMouseButtons;
    const bool keepalive = now - lastInputAt > kInputKeepaliveMs;
    if (dx || dy || wheel || buttonsChanged || keepalive) {
        sendMouseReport(dx, dy, wheel, buttons, true);
    }
}

void processGameInput() {
    if (!inputClient.connected()) {
        return;
    }

    sendKeyboardReportIfNeeded(false);

    auto& state = M5Cardputer.Keyboard.keysState();
    const uint32_t now = millis();

    uint8_t buttons = 0;
    if (keyPressed('l', 'L')) {
        buttons |= kMouseButtonLeft;
    }
    if (keyPressed('\'', '"')) {
        buttons |= kMouseButtonRight;
    }

    const bool scrollUp = state.fn && state.up;
    const bool scrollDown = state.fn && state.down;
    const bool lookUp = (state.up || keyPressed(';', ':')) && !scrollUp;
    const bool lookDown = (state.down || keyPressed('.', '>')) && !scrollDown;
    const bool lookLeft = state.left || keyPressed(',', '<');
    const bool lookRight = state.right || keyPressed('/', '?');

    int8_t dx = 0;
    int8_t dy = 0;
    if (lookLeft != lookRight) {
        dx = lookLeft ? -kGameLookStep : kGameLookStep;
    }
    if (lookUp != lookDown) {
        dy = lookUp ? -kGameLookStep : kGameLookStep;
    }

    if (now - lastMouseReportAt < kMouseReportIntervalMs) {
        dx = 0;
        dy = 0;
    }

    int8_t wheel = 0;
    if (scrollUp != scrollDown && now - lastMouseWheelAt >= kMouseWheelIntervalMs) {
        wheel = scrollUp ? 1 : -1;
        lastMouseWheelAt = now;
    }

    const bool buttonsChanged = buttons != lastMouseButtons;
    const bool keepalive = now - lastInputAt > kInputKeepaliveMs;
    if (dx || dy || wheel || buttonsChanged || keepalive) {
        sendMouseReport(dx, dy, wheel, buttons, true, false);
    }
}

void processKeyboard() {
    M5Cardputer.update();
    processInputReconnect();

    if (handleGameToggle()) {
        return;
    }

    if (handleMouseToggle()) {
        return;
    }

    if (mouseMode) {
        processMouseInput();
        return;
    }

    if (gameMode) {
        processGameInput();
        return;
    }

    sendKeyboardReportIfNeeded(false);

    if (inputClient.connected() && millis() - lastInputAt > kInputKeepaliveMs) {
        sendKeyboardReportIfNeeded(true);
    }
}

void maybeDrawOverlay() {
    if (!hadFrame) {
        return;
    }
    if (millis() - lastFrameAt < 3000 || millis() - lastStatusAt < kStatusRedrawMs) {
        return;
    }
    lastStatusAt = millis();
    M5Cardputer.Display.setTextDatum(top_left);
    M5Cardputer.Display.setTextColor(TFT_YELLOW, TFT_BLACK);
    M5Cardputer.Display.fillRect(0, 0, M5Cardputer.Display.width(), 12, TFT_BLACK);
    M5Cardputer.Display.setCursor(2, 1);
    M5Cardputer.Display.print(frameClient.connected() ? "Waiting for frame" : "Frame disconnected");
}

}  // namespace

void setup() {
    auto cfg = M5.config();
    cfg.serial_baudrate = 115200;
    cfg.internal_mic = false;
    cfg.internal_spk = false;
    cfg.fallback_board = m5::board_t::board_M5CardputerADV;
    M5Cardputer.begin(cfg, true);
    M5Cardputer.Display.setRotation(1);
    M5Cardputer.Display.setBrightness(180);
    M5Cardputer.Display.fillScreen(TFT_BLACK);

    Serial.println("Cardputer-Adv Windows Remote");
    loadRuntimeConfig();
    if (!appConfig.complete() || bootSetupRequested()) {
        runConfigMenu();
    }
    ensureWifi();
}

void loop() {
    ensureConnections();
    processFrameStream();
    processKeyboard();
    maybeDrawOverlay();
    delay(1);
}
