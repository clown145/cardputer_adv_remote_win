#include <Arduino.h>
#include <M5Cardputer.h>
#include <Preferences.h>
#include <WiFi.h>

namespace {

constexpr uint16_t kDefaultFramePort = 5050;
constexpr uint16_t kDefaultInputPort = 5051;
constexpr uint16_t kFrameWidth = 240;
constexpr uint16_t kFrameHeight = 135;
constexpr uint32_t kConnectRetryMs = 3000;
constexpr uint32_t kWifiConnectTimeoutMs = 12000;
constexpr uint32_t kMenuBootWindowMs = 1800;
constexpr uint32_t kMagic = 0x41575243;  // "CRWA" little endian
constexpr uint16_t kProtocolVersion = 1;
constexpr size_t kFrameBytes = kFrameWidth * kFrameHeight * sizeof(uint16_t);
constexpr uint32_t kStatusRedrawMs = 1000;
constexpr uint32_t kFrameTimeoutMs = 2500;
constexpr uint32_t kInputKeepaliveMs = 1000;
constexpr uint8_t kMaxHidKeys = 6;
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
bool hadFrame = false;

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
    bool down = false;
    char chars[8] = {};
    uint8_t charCount = 0;

    bool hasAction() const {
        return enter || backspace || esc || up || down || charCount > 0;
    }
};

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
            key.down = state.down;
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
        display.println("W/S or arrows, Enter");

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
        if (key.up || (key.charCount > 0 && (key.chars[0] == 'w' || key.chars[0] == 'W'))) {
            selected = max(0, selected - 1);
        }
        if (key.down || (key.charCount > 0 && (key.chars[0] == 's' || key.chars[0] == 'S'))) {
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
        if (key.up || (key.charCount > 0 && (key.chars[0] == 'w' || key.chars[0] == 'W'))) {
            selected = max(0, selected - 1);
        } else if (key.down || (key.charCount > 0 && (key.chars[0] == 's' || key.chars[0] == 'S'))) {
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
            sendHello(inputClient, "INPUT");
        }
    }

    if (!frameClient.connected() || !inputClient.connected()) {
        drawStatus("Waiting for Windows host", frameClient.connected() ? "Frame: ok" : "Frame: reconnect",
                   inputClient.connected() ? "Input: ok" : "Input: reconnect");
    } else {
        drawStatus("Connected to host", "Waiting for frames...");
    }
}

void drawFrame() {
    const int screenW = M5Cardputer.Display.width();
    const int screenH = M5Cardputer.Display.height();
    const int x = max(0, (screenW - kFrameWidth) / 2);
    const int y = max(0, (screenH - kFrameHeight) / 2);
    M5Cardputer.Display.pushImage(x, y, kFrameWidth, kFrameHeight, frameBuffer);
    hadFrame = true;
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

    if (header.magic != kMagic || header.version != kProtocolVersion || header.width != kFrameWidth ||
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

InputReport buildInputReport() {
    InputReport report = {};
    report.magic = kMagic;
    report.version = kProtocolVersion;
    report.sequence = ++lastSequence;

    auto& state = M5Cardputer.Keyboard.keysState();
    report.modifiers = state.modifiers;

    uint8_t index = 0;
    for (const uint8_t key : state.hid_keys) {
        if (index >= kMaxHidKeys) {
            break;
        }
        if (key == 0 || key >= 0x80) {
            continue;
        }
        report.keys[index++] = key;
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

void sendInputReportIfNeeded(bool force = false) {
    if (!inputClient.connected()) {
        return;
    }

    const InputReport report = buildInputReport();
    if (!force && sameKeys(report, lastReport)) {
        return;
    }

    if (writeExact(inputClient, reinterpret_cast<const uint8_t*>(&report), sizeof(report))) {
        lastReport = report;
        lastInputAt = millis();
    } else {
        inputClient.stop();
    }
}

void processKeyboard() {
    M5Cardputer.update();
    sendInputReportIfNeeded(false);

    if (inputClient.connected() && millis() - lastInputAt > kInputKeepaliveMs) {
        sendInputReportIfNeeded(true);
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
