/**
 * =====================================================================
 * AIoT Intelligence Forest Protection - Main Actuator & Sensor Node
 * =====================================================================
 * Board: ESP32 DevKit V1
 * Components:
 *   - 2x Servos (Tower Wilayah 1 & Wilayah 2 Fire Extinguishers)
 *   - 2x Relays (Water Pump 1 & Water Pump 2)
 *   - 1x HC-SR04 Ultrasonic (Incursion Detector 1-8cm)
 *   - 1x Passive Buzzer (Warning / Alarm Siren)
 *   - 1x RGB LED Common Cathode
 *   - 1x Flame Sensor DO (Hardware Safety Backup)
 *
 * Safe Pin Layout (Avoids strapping pins 0, 2, 4, 12, 15 & Flash 6-11 & JTAG 13,14):
 *   - Servo 1 (Tower Wilayah 1) : GPIO 16 (PWM)  ← moved from 13 (JTAG MTCK conflict)
 *   - Servo 2 (Tower Wilayah 2) : GPIO 17 (PWM)  ← moved from 14 (JTAG MTMS conflict)
 *   - Relay 1 (Pump Zone 1)     : GPIO 25 (Digital Output)
 *   - Relay 2 (Pump Zone 2)     : GPIO 26 (Digital Output)
 *   - Ultrasonic TRIG           : GPIO 33 (Digital Output)
 *   - Ultrasonic ECHO           : GPIO 32 (Digital Input)
 *   - Flame Sensor DO           : GPIO 35 (Input-Only Pin)
 *   - Passive Buzzer            : GPIO 18 (PWM Tone)
 *   - RGB LED RED               : GPIO 19 (Digital Output)
 *   - RGB LED GREEN             : GPIO 21 (Digital Output)
 *   - RGB LED BLUE              : GPIO 22 (Digital Output)
 */

#include <WiFi.h>
#include <WebServer.h>
#include <ESP32Servo.h>
#include <ArduinoJson.h>
#include "soc/soc.h"           // Brownout detector control
#include "soc/rtc_cntl_reg.h"  // RTC register for brownout

// ================= NETWORK CONFIGURATION =================
const char* ssid             = "Absolute Solver";
const char* password         = "CynIsMyRobo18z";
const char* python_server_ip = "192.168.1.100";
const uint16_t python_server_port = 8888;

WiFiClient  tcpClient;
WebServer   localWebServer(80);

// ================= PIN DEFINITIONS =================
// NOTE: GPIO 13 & 14 are JTAG pins (MTCK/MTMS) — they receive spurious pulses
// during USB/boot which makes servos jitter uncontrollably. Use 16 & 17 instead.
#define PIN_SERVO_TOWER1  16
#define PIN_SERVO_TOWER2  17
#define PIN_RELAY_1       25
#define PIN_RELAY_2       26
#define PIN_US_TRIG       33
#define PIN_US_ECHO       32
#define PIN_FLAME_SENSOR  35
#define PIN_BUZZER        18
#define PIN_RGB_RED       19
#define PIN_RGB_GREEN     21
#define PIN_RGB_BLUE      22

#define RELAY_ACTIVE_STATE LOW
#define RELAY_OFF_STATE    HIGH

// ================= HARDWARE OBJECTS =================
Servo servoTower1;
Servo servoTower2;

// ================= RUNTIME STATE =================
float         currentDistance        = 100.0;
unsigned long lastDistanceMeasureTime = 0;
const unsigned long distanceMeasureInterval = 60;

unsigned long lastTelemetryTime   = 0;
const unsigned long telemetryInterval = 80;

bool          buzzerAlarmActive   = false;
unsigned long lastBuzzerToggleTime = 0;
bool          buzzerToneState     = false;

// ===========================================================
// HELPER FUNCTIONS  (defined FIRST — no forward decls needed)
// ===========================================================

void setRGBColor(bool r, bool g, bool b) {
  digitalWrite(PIN_RGB_RED,   r ? HIGH : LOW);
  digitalWrite(PIN_RGB_GREEN, g ? HIGH : LOW);
  digitalWrite(PIN_RGB_BLUE,  b ? HIGH : LOW);
}

void setRelay(int relayNum, bool state) {
  if      (relayNum == 1) digitalWrite(PIN_RELAY_1, state ? RELAY_ACTIVE_STATE : RELAY_OFF_STATE);
  else if (relayNum == 2) digitalWrite(PIN_RELAY_2, state ? RELAY_ACTIVE_STATE : RELAY_OFF_STATE);
}

float measureUltrasonicDistance() {
  digitalWrite(PIN_US_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_US_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_US_TRIG, LOW);
  long duration = pulseIn(PIN_US_ECHO, HIGH, 25000);
  if (duration <= 0) return 100.0;
  return (duration * 0.0343) / 2.0;
}

void playBuzzerTone(int frequency, int durationMs) {
  tone(PIN_BUZZER, frequency, durationMs);
  delay(durationMs);
  noTone(PIN_BUZZER);
}

// ── Boot chime ──────────────────────────────────────────────────────────────
// Phase 1 : two soft "lock-confirm" ticks  (like a smart door lock)
// Phase 2 : smooth ascending arpeggio      (like elevator arrival / DJI arm)
// Phase 3 : final settling tone            (system ready)
void playBootMelody() {
  // Phase 1 — double soft tick (880 Hz = A5, short & clean)
  tone(PIN_BUZZER, 880, 60);  delay(100);
  tone(PIN_BUZZER, 880, 60);  delay(130);

  // Phase 2 — ascending arpeggio: G4 → C5 → E5 → G5 → C6
  //           (same chord family used in lift chimes & DJI Mavic arming)
  const int arp[]  = {392, 523, 659, 784, 1047};
  const int dur[]  = { 90,  90,  90,  90,  180};
  for (int i = 0; i < 5; i++) {
    tone(PIN_BUZZER, arp[i], dur[i]);
    delay(dur[i] + 25);
    noTone(PIN_BUZZER);
    delay(10); // tiny breathe between notes
  }

  // Phase 3 — soft resolve: D6 (1175 Hz), fades to silence
  tone(PIN_BUZZER, 1175, 250); delay(260);
  noTone(PIN_BUZZER);
}


// Slow servo home sweep — confirms servo is alive and horn is correctly seated
void servoBootSweep(Servo &srv) {
  for (int a = 90; a <= 120; a += 3) { srv.write(a); delay(20); }
  for (int a = 120; a >= 60; a -= 3) { srv.write(a); delay(20); }
  for (int a = 60; a <= 90; a += 3)  { srv.write(a); delay(20); }
}

void connectToWiFi() {
  Serial.printf("[WIFI] Connecting to %s", ssid);
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(400);
    Serial.print(".");
  }
  Serial.println("\n[WIFI] Connected! IP: " + WiFi.localIP().toString());
}

// ===========================================================
// EMBEDDED WEB SERVER (uses helpers above — all already defined)
// ===========================================================
const char INDEX_HTML[] PROGMEM = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ESP32 Forest Node Control</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: Arial, sans-serif; background: #0f172a; color: #f8fafc; padding: 20px; }
    .card { background: #1e293b; max-width: 500px; margin: auto; padding: 24px; border-radius: 14px; box-shadow: 0 4px 24px rgba(0,0,0,0.6); }
    h2 { color: #38bdf8; margin-bottom: 16px; }
    h3 { color: #94a3b8; font-size: 14px; margin: 16px 0 8px; text-transform: uppercase; letter-spacing: 1px; }
    .stat-box { background: #334155; padding: 12px 16px; border-radius: 8px; margin-bottom: 8px; font-size: 16px; }
    .stat-box span { color: #38bdf8; font-weight: bold; }
    .btn { border: none; padding: 9px 16px; margin: 4px; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: bold; color: white; transition: opacity 0.15s; }
    .btn:hover { opacity: 0.85; }
    .btn-blue   { background: #0284c7; }
    .btn-red    { background: #ef4444; }
    .btn-green  { background: #10b981; }
    .btn-yellow { background: #ca8a04; }
    .btn-gray   { background: #475569; }
    .slider { width: 100%; margin: 6px 0; accent-color: #38bdf8; }
    label { font-size: 13px; color: #94a3b8; }
    .row { display: flex; justify-content: space-between; align-items: center; }
    .angle-val { font-family: monospace; color: #38bdf8; font-size: 18px; font-weight: bold; }
    hr { border: none; border-top: 1px solid #334155; margin: 16px 0; }
  </style>
</head>
<body>
  <div class="card">
    <h2>🌲 ESP32 Forest Protection Node</h2>

    <div class="stat-box">
      Ultrasonik: <span id="dist">--</span> cm &nbsp;|&nbsp; Sensor Api: <span id="flame">--</span>
    </div>

    <h3>🔄 Servo Tower Control</h3>
    <div class="row"><label>Servo 1 — Wilayah 1</label><span class="angle-val"><span id="s1-val">90</span>°</span></div>
    <input type="range" min="0" max="180" value="90" class="slider" oninput="setServo(1, this.value)">

    <div class="row"><label>Servo 2 — Wilayah 2</label><span class="angle-val"><span id="s2-val">90</span>°</span></div>
    <input type="range" min="0" max="180" value="90" class="slider" oninput="setServo(2, this.value)">

    <hr>
    <h3>💧 Relay Pompa Air</h3>
    <button class="btn btn-red"  onclick="setRelay(1,1)">Pompa 1 ON</button>
    <button class="btn btn-gray" onclick="setRelay(1,0)">Pompa 1 OFF</button>
    &nbsp;
    <button class="btn btn-red"  onclick="setRelay(2,1)">Pompa 2 ON</button>
    <button class="btn btn-gray" onclick="setRelay(2,0)">Pompa 2 OFF</button>

    <hr>
    <h3>🔊 Buzzer &amp; LED RGB</h3>
    <button class="btn btn-yellow" onclick="fetch('/beep')">🔔 Test Buzzer</button><br><br>
    <button class="btn btn-red"    onclick="setLED('RED')">🔴 LED Merah</button>
    <button class="btn btn-green"  onclick="setLED('GREEN')">🟢 LED Hijau</button>
    <button class="btn btn-yellow" onclick="setLED('YELLOW')">🟡 LED Kuning</button>
    <button class="btn btn-blue"   onclick="setLED('BLUE')">🔵 LED Biru</button>
    <button class="btn btn-gray"   onclick="setLED('OFF')">⚫ LED OFF</button>
  </div>

  <script>
    function setServo(t, a) {
      document.getElementById('s'+t+'-val').innerText = a;
      fetch('/servo?tower='+t+'&angle='+a);
    }
    function setRelay(r, s) { fetch('/relay?id='+r+'&state='+s); }
    function setLED(c)       { fetch('/led?color='+c); }

    setInterval(function() {
      fetch('/status').then(r => r.json()).then(d => {
        document.getElementById('dist').innerText  = d.distance_cm.toFixed(1);
        document.getElementById('flame').innerText = d.flame_pin === 0 ? '🔥 API TERDETEKSI' : '✅ AMAN';
      }).catch(()=>{});
    }, 800);
  </script>
</body>
</html>
)rawliteral";

void setupWebServer() {
  // Serve HTML dashboard
  localWebServer.on("/", HTTP_GET, []() {
    localWebServer.send_P(200, "text/html", INDEX_HTML);
  });

  // JSON telemetry status
  localWebServer.on("/status", HTTP_GET, []() {
    String json = "{\"distance_cm\":" + String(currentDistance, 1) +
                  ",\"flame_pin\":"   + String(digitalRead(PIN_FLAME_SENSOR)) + "}";
    localWebServer.send(200, "application/json", json);
  });

  // Control Servo
  localWebServer.on("/servo", HTTP_GET, []() {
    if (localWebServer.hasArg("tower") && localWebServer.hasArg("angle")) {
      int t = localWebServer.arg("tower").toInt();
      int a = constrain(localWebServer.arg("angle").toInt(), 0, 180);
      if (t == 1) servoTower1.write(a);
      else if (t == 2) servoTower2.write(a);
      localWebServer.send(200, "text/plain", "OK");
    } else {
      localWebServer.send(400, "text/plain", "Bad Request");
    }
  });

  // Control Relay
  localWebServer.on("/relay", HTTP_GET, []() {
    if (localWebServer.hasArg("id") && localWebServer.hasArg("state")) {
      setRelay(localWebServer.arg("id").toInt(), localWebServer.arg("state").toInt() == 1);
      localWebServer.send(200, "text/plain", "OK");
    } else {
      localWebServer.send(400, "text/plain", "Bad Request");
    }
  });

  // Control RGB LED
  localWebServer.on("/led", HTTP_GET, []() {
    if (localWebServer.hasArg("color")) {
      String c = localWebServer.arg("color");
      if      (c == "RED")    setRGBColor(true,  false, false);
      else if (c == "GREEN")  setRGBColor(false, true,  false);
      else if (c == "YELLOW") setRGBColor(true,  true,  false);
      else if (c == "BLUE")   setRGBColor(false, false, true);
      else                    setRGBColor(false, false, false); // OFF
      localWebServer.send(200, "text/plain", "OK");
    }
  });

  // Test Buzzer beep
  localWebServer.on("/beep", HTTP_GET, []() {
    playBuzzerTone(1500, 200);
    localWebServer.send(200, "text/plain", "OK");
  });

  localWebServer.begin();
  Serial.println("[WEB SERVER] Embedded Web Server started — open http://" + WiFi.localIP().toString());
}

// ===========================================================
// TCP CONNECTION & COMMAND HANDLER
// ===========================================================
void ensureTcpConnection() {
  if (!tcpClient.connected()) {
    static unsigned long lastAttempt = 0;
    if (millis() - lastAttempt > 3000) {
      lastAttempt = millis();
      Serial.printf("[TCP] Connecting to Python %s:%d...\n", python_server_ip, python_server_port);
      if (tcpClient.connect(python_server_ip, python_server_port)) {
        Serial.println("[TCP] Connected to Python AI Central Hub!");
        setRGBColor(false, true, false); // Green = Online
      } else {
        Serial.println("[TCP ERROR] Failed. Retrying in 3s...");
        setRGBColor(false, false, true); // Blue = Waiting
      }
    }
  }
}

void handleIncomingCommands() {
  while (tcpClient.available()) {
    String line = tcpClient.readStringUntil('\n');
    line.trim();
    if (line.length() == 0) continue;

    StaticJsonDocument<512> doc;
    DeserializationError err = deserializeJson(doc, line);
    if (err) {
      Serial.println("[JSON ERROR] " + String(err.c_str()));
      continue;
    }

    const char* action = doc["action"] | "";

    // 1. Fire Extinguish — from AI vision
    if (strcmp(action, "FIRE_EXTINGUISH") == 0) {
      bool z1 = doc["zone1_active"] | false;
      bool z2 = doc["zone2_active"] | false;
      if (z1) { servoTower1.write(constrain((int)(doc["zone1_angle"] | 90), 0, 180)); setRelay(1, (int)(doc["relay1"] | 0) == 1); }
      else      setRelay(1, false);
      if (z2) { servoTower2.write(constrain((int)(doc["zone2_angle"] | 90), 0, 180)); setRelay(2, (int)(doc["relay2"] | 0) == 1); }
      else      setRelay(2, false);
      buzzerAlarmActive = true;
      setRGBColor(true, false, false); // RED

    // 2. Obstacle alert — ultrasonic 1-8 cm
    } else if (strcmp(action, "OBSTACLE_ALERT") == 0) {
      setRGBColor(true, true, false); // YELLOW
      playBuzzerTone(1200, 150);

    // 3. Standby
    } else if (strcmp(action, "STANDBY") == 0) {
      setRelay(1, false);
      setRelay(2, false);
      buzzerAlarmActive = false;
      noTone(PIN_BUZZER);
      setRGBColor(false, true, false); // GREEN

    // 4. Manual servo from Python dashboard
    } else if (strcmp(action, "SET_SERVO") == 0) {
      int tower = doc["tower"] | 1;
      int angle = constrain((int)(doc["angle"] | 90), 0, 180);
      if (tower == 1) servoTower1.write(angle);
      else if (tower == 2) servoTower2.write(angle);

    // 5. Manual relay from Python dashboard
    } else if (strcmp(action, "SET_RELAY") == 0) {
      setRelay(doc["relay"] | 1, (int)(doc["state"] | 0) == 1);

    // 6. Buzzer test beep
    } else if (strcmp(action, "BEEP") == 0) {
      playBuzzerTone(1500, 200);
    }
  }
}

// ===========================================================
// SETUP & LOOP
// ===========================================================
void setup() {
  // ── CRITICAL: Disable brownout detector FIRST ──
  // ESP32 brownout resets when servo draws surge current (300-600mA peak).
  // Real fix: power servos from external 5V rail. Software fix below:
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);

  Serial.begin(115200);
  delay(200);
  Serial.println("\n===========================================");
  Serial.println("AIoT Forest Protection - Main ESP32 Node");
  Serial.println("===========================================");
  Serial.println("[BOOT] Brownout detector DISABLED (servo protection)");

  pinMode(PIN_RELAY_1, OUTPUT);   setRelay(1, false);
  pinMode(PIN_RELAY_2, OUTPUT);   setRelay(2, false);
  pinMode(PIN_US_TRIG, OUTPUT);
  pinMode(PIN_US_ECHO, INPUT);
  pinMode(PIN_FLAME_SENSOR, INPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_RGB_RED,   OUTPUT);
  pinMode(PIN_RGB_GREEN, OUTPUT);
  pinMode(PIN_RGB_BLUE,  OUTPUT);

  setRGBColor(false, false, true); // Blue = Booting

  // ── Boot melody: confirms buzzer alive ──
  playBootMelody();

  // ── Servo init: ONE timer per servo, settle before moving ──
  ESP32PWM::allocateTimer(0); // Timer 0 → Servo Tower 1
  ESP32PWM::allocateTimer(1); // Timer 1 → Servo Tower 2
  servoTower1.setPeriodHertz(50);
  servoTower2.setPeriodHertz(50);
  servoTower1.attach(PIN_SERVO_TOWER1, 500, 2400);
  servoTower2.attach(PIN_SERVO_TOWER2, 500, 2400);
  delay(300); // Let servo driver capacitors charge before sending angle

  // Park both at 90°
  servoTower1.write(90);
  delay(600);  // Wait for Servo 1 to reach position (avoid current spike overlap)
  servoTower2.write(90);
  delay(600);

  // Servo 1 diagnostic sweep (if horn still doesn't move → gear stripped → replace)
  Serial.println("[SERVO] Diagnostic sweep Servo 1 (GPIO 16) — watch white horn");
  Serial.println("[SERVO]   If motor sounds but horn is still → gear stripped, replace servo");
  servoBootSweep(servoTower1);
  delay(400);

  // Servo 2 diagnostic sweep
  Serial.println("[SERVO] Diagnostic sweep Servo 2 (GPIO 17)");
  servoBootSweep(servoTower2);
  delay(400);

  Serial.println("[BOOT] Servos initialized. Connecting to WiFi...");
  setRGBColor(true, true, false); // Yellow = Connecting
  connectToWiFi();
  setRGBColor(false, true, false); // Green = Ready
  setupWebServer();
}

void loop() {
  localWebServer.handleClient();   // Handle browser requests → http://<IP_ESP32>
  ensureTcpConnection();
  handleIncomingCommands();

  unsigned long now = millis();

  // Periodic ultrasonic reading
  if (now - lastDistanceMeasureTime >= distanceMeasureInterval) {
    lastDistanceMeasureTime = now;
    currentDistance = measureUltrasonicDistance();
  }

  // Send telemetry JSON to Python server
  if (now - lastTelemetryTime >= telemetryInterval) {
    lastTelemetryTime = now;
    int flameRaw = digitalRead(PIN_FLAME_SENSOR);
    if (tcpClient.connected()) {
      StaticJsonDocument<128> tel;
      tel["distance_cm"] = round(currentDistance * 10) / 10.0;
      tel["flame_pin"]   = flameRaw;
      String out; serializeJson(tel, out); out += "\n";
      tcpClient.print(out);
    }
  }

  // Fire alarm siren
  if (buzzerAlarmActive) {
    if (now - lastBuzzerToggleTime > 180) {
      lastBuzzerToggleTime = now;
      buzzerToneState = !buzzerToneState;
      tone(PIN_BUZZER, buzzerToneState ? 2200 : 1400);
    }
  }
}
