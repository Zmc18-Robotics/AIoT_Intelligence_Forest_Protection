// ============================================
// ESP32-CAM : Streaming TCP + Kontrol Senter via WebSocket
// Board: AI-THINKER ESP32-CAM
// Proyek: Anti Drone Turret Systems
// ============================================
#include "esp_camera.h"
#include <ArduinoJson.h>
#include <WebSocketsServer.h>
#include <WiFi.h>

// ─── KONFIGURASI WIFI ───────────────────────────────────
#define WIFI_SSID "Absolute Solver"
#define WIFI_PASS "CynIsMyRobo18z"

// ─── PIN KAMERA (AI-THINKER) ────────────────────────────
#define PWDN_GPIO_NUM 32
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM 0
#define SIOD_GPIO_NUM 26
#define SIOC_GPIO_NUM 27
#define Y9_GPIO_NUM 35
#define Y8_GPIO_NUM 34
#define Y7_GPIO_NUM 39
#define Y6_GPIO_NUM 36
#define Y5_GPIO_NUM 21
#define Y4_GPIO_NUM 19
#define Y3_GPIO_NUM 18
#define Y2_GPIO_NUM 5
#define VSYNC_GPIO_NUM 25
#define HREF_GPIO_NUM 23
#define PCLK_GPIO_NUM 22

// ─── PIN SENTER ─────────────────────────────────────────
#define PIN_FLASH 4

// ─── OBJEK SERVER ───────────────────────────────────────
WiFiServer tcpServer(80);
WebSocketsServer wsServer(81);

bool flashOn = true; // default ON
bool serialStreamActive = false;
String serialBuffer = "";

// ─── DEKLARASI FUNGSI ───────────────────────────────────
void webSocketEvent(uint8_t num, WStype_t type, uint8_t *payload,
                    size_t length);

// ────────────────────────────────────────────────────────
void setup() {
  Serial.begin(460800); // Dipercepat menjadi 460800 untuk streaming video via COM
  Serial.println("\n=== ESP32-CAM START ===");

  // Konfigurasi kamera
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size = FRAMESIZE_QVGA; // 320x240, bisa diganti ke FRAMESIZE_VGA
  config.jpeg_quality = 10;
  config.fb_count = 2;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Kamera gagal: 0x%x\n", err);
    return;
  }
  Serial.println("Kamera OK");

  // ── Senter dinyalakan SETELAH camera init ──────────────
  pinMode(PIN_FLASH, OUTPUT);
  digitalWrite(PIN_FLASH, HIGH); // Nyalakan senter awal
  Serial.println("Senter disiapkan");

  // Koneksi WiFi
  WiFi.setAutoReconnect(true);
  WiFi.setSleep(false); // MATIKAN WIFI SLEEP: Mengatasi lag parah dan putus saat video streaming
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi OK");
  Serial.print("IP ESP32-CAM: ");
  Serial.println(WiFi.localIP());

  // Mulai server TCP (streaming gambar)
  tcpServer.begin();

  // Mulai server WebSocket (kontrol senter)
  wsServer.begin();
  wsServer.onEvent(webSocketEvent);
  Serial.println("Server siap (TCP:80, WS:81)");
}

// ────────────────────────────────────────────────────────
void loop() {
  // WebSocket selalu diproses dulu
  wsServer.loop();

  // --- Tangani perintah Serial (Senter & Stream) ---
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      serialBuffer.trim();
      if (serialBuffer == "START_SERIAL_STREAM") {
        serialStreamActive = true;
      } else if (serialBuffer == "STOP_SERIAL_STREAM") {
        serialStreamActive = false;
      } else if (serialBuffer.startsWith("FLASH:")) {
        int state = serialBuffer.substring(6).toInt();
        flashOn = (state != 0);
        digitalWrite(PIN_FLASH, flashOn ? HIGH : LOW);
        if (!serialStreamActive) {
          Serial.printf("[Senter] %s\n", flashOn ? "ON" : "OFF");
        }
      }
      serialBuffer = "";
    } else {
      if (serialBuffer.length() < 100) {
        serialBuffer += c;
      }
    }
  }

  // --- Streaming Serial (jika diaktifkan) ---
  if (serialStreamActive) {
    camera_fb_t *fb = esp_camera_fb_get();
    if (fb) {
      uint8_t header[4] = {0xAA, 0xBB, 0xCC, 0xDD}; // Magic header
      uint32_t len = fb->len;
      uint8_t lenBuf[4] = {(uint8_t)((len >> 24) & 0xFF),
                           (uint8_t)((len >> 16) & 0xFF),
                           (uint8_t)((len >> 8) & 0xFF), 
                           (uint8_t)(len & 0xFF)};

      Serial.write(header, 4);
      Serial.write(lenBuf, 4);
      Serial.write(fb->buf, len);
      
      esp_camera_fb_return(fb);
      
      // Beri sedikit nafas untuk RTOS agar task WiFi tidak kelaparan (Watchdog)
      delay(5);
    }
  }

  // --- Tangani client TCP (streaming gambar) ---
  WiFiClient client = tcpServer.accept();
  if (client) {
    Serial.println("[TCP] Client terhubung");
    client.setNoDelay(true);

    while (client.connected()) {
      wsServer.loop();

      camera_fb_t *fb = esp_camera_fb_get();
      if (!fb) {
        delay(10);
        continue;
      }

      uint32_t len = fb->len;
      uint8_t lenBuf[4] = {(uint8_t)((len >> 24) & 0xFF),
                           (uint8_t)((len >> 16) & 0xFF),
                           (uint8_t)((len >> 8) & 0xFF), (uint8_t)(len & 0xFF)};

      bool ok =
          (client.write(lenBuf, 4) == 4) && (client.write(fb->buf, len) == len);

      esp_camera_fb_return(fb);

      if (!ok)
        break;
    }

    Serial.println("[TCP] Client putus");
    client.stop();
  }
}

// ────────────────────────────────────────────────────────
// Event WebSocket (menerima perintah senter dari Python)
void webSocketEvent(uint8_t num, WStype_t type, uint8_t *payload,
                    size_t length) {
  if (type == WStype_CONNECTED) {
    Serial.printf("[WS] Client #%d terhubung\n", num);
    return;
  }
  if (type == WStype_DISCONNECTED) {
    Serial.printf("[WS] Client #%d putus\n", num);
    return;
  }
  if (type != WStype_TEXT)
    return;

  // Parse JSON
  StaticJsonDocument<128> doc;
  DeserializationError error = deserializeJson(doc, payload);
  if (error) {
    Serial.print("[WS] JSON gagal: ");
    Serial.println(error.c_str());
    return;
  }

  const char *cmd = doc["cmd"];
  if (!cmd)
    return;

  if (strcmp(cmd, "flash") == 0) {
    int state = doc["state"] | 0;
    flashOn = (state != 0);
    digitalWrite(PIN_FLASH, flashOn ? HIGH : LOW);
    Serial.printf("[Senter] %s\n", flashOn ? "ON" : "OFF");
  }
}
