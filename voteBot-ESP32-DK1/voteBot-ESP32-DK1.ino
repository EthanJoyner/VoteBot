#include <Arduino.h>
#include <WiFi.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>

// -------------------- WIFI / WS CONFIG --------------------
const char* WIFI_SSID = "VOTE_BOT_BLUE";
const char* WIFI_PASSWORD = "VOTEBOT-8";
const char* WS_HOST = "192.168.1.2";
const uint16_t WS_PORT = 5000;
const char* WS_PATH = "/ws/robot";

WebSocketsClient webSocket;

const unsigned long WIFI_CONNECT_TIMEOUT_MS = 20000;
const unsigned long WIFI_RETRY_INTERVAL_MS = 10000;
unsigned long lastWiFiRetryAt = 0;

// Motor Pins
int ML1 = 4;   // Left motor IN1
int ML2 = 2;   // Left motor IN2
int MR1 = 12;  // Right motor IN3
int MR2 = 13;  // Right motor IN4

int ENA = 16;  // PWM for left motor
int ENB = 14;  // PWM for right motor

int SPEED = 128; // 50% duty cycle (0–255)

const char* wifiStatusText(wl_status_t status) {
  switch (status) {
    case WL_IDLE_STATUS:
      return "idle";
    case WL_NO_SSID_AVAIL:
      return "ssid unavailable";
    case WL_SCAN_COMPLETED:
      return "scan completed";
    case WL_CONNECTED:
      return "connected";
    case WL_CONNECT_FAILED:
      return "connect failed";
    case WL_CONNECTION_LOST:
      return "connection lost";
    case WL_DISCONNECTED:
      return "disconnected";
    default:
      return "unknown";
  }
}

void applySpeed() {
  analogWrite(ENA, SPEED);
  analogWrite(ENB, SPEED);
}

// -------------------- MOTOR SETUP --------------------
void motorSetup() {
  pinMode(ML1, OUTPUT);
  pinMode(ML2, OUTPUT);
  pinMode(MR1, OUTPUT);
  pinMode(MR2, OUTPUT);

  pinMode(ENA, OUTPUT);
  pinMode(ENB, OUTPUT);

  applySpeed();
}

// -------------------- MOTOR FUNCTIONS --------------------
void forward(int ms_time) {
  SPEED = 128; // Set speed to 50%
  applySpeed();
  digitalWrite(ML1, LOW);
  digitalWrite(ML2, HIGH);
  digitalWrite(MR1, LOW);
  digitalWrite(MR2, HIGH);
  Serial.println("forward");
  delay(ms_time);
  stop(100);
}

void backward(int ms_time) {
  SPEED = 128; // Set speed to 50%
  applySpeed();
  digitalWrite(ML1, HIGH);
  digitalWrite(ML2, LOW);
  digitalWrite(MR1, HIGH);
  digitalWrite(MR2, LOW);
  Serial.println("backward");
  delay(ms_time);
  stop(100);
}

void right(int ms_time) {
  SPEED = 75; // Set speed to 30% for sharper turn
  applySpeed();
  digitalWrite(ML1, LOW);
  digitalWrite(ML2, HIGH);
  digitalWrite(MR1, HIGH);
  digitalWrite(MR2, LOW);
  Serial.println("right");
  delay(ms_time);
  stop(100);
}

void left(int ms_time) {
  SPEED = 75; // Set speed to 30% for sharper turn
  applySpeed();
  digitalWrite(ML1, HIGH);
  digitalWrite(ML2, LOW);
  digitalWrite(MR1, LOW);
  digitalWrite(MR2, HIGH);
  Serial.println("left");
  delay(ms_time);
  stop(100);
}

void stop(int ms_delay) {
  SPEED = 128; // Set speed to 50%
  applySpeed();
  digitalWrite(ML1, LOW);
  digitalWrite(ML2, LOW);
  digitalWrite(MR1, LOW);
  digitalWrite(MR2, LOW);
  Serial.println("stop");
  delay(ms_delay);
}

void executeDirection(const String& direction) {
  if (direction == "forward") forward(1500);
  else if (direction == "backward") backward(1500);
  else if (direction == "left") left(500);
  else if (direction == "right") right(500);
  else if (direction == "stop") stop(100);
  else {
    Serial.print("Unknown robot direction: ");
    Serial.println(direction);
  }
}

void handleRobotMessage(const char* message) {
  JsonDocument doc;
  DeserializationError error = deserializeJson(doc, message);
  if (error) {
    Serial.print("JSON parse error: ");
    Serial.println(error.c_str());
    return;
  }

  const char* type = doc["type"] | "";
  if (String(type) != "robot_command") {
    return;
  }

  const char* directionValue = doc["direction"] | "";
  String direction = String(directionValue);
  int durationMs = doc["duration_ms"] | 1500;

  Serial.print("Executing direction: ");
  Serial.print(direction);
  Serial.print(" for ");
  Serial.print(durationMs);
  Serial.println("ms");

  executeDirection(direction);
}

void onWebSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      Serial.println("WebSocket connected to robot command channel");
      webSocket.sendTXT("{\"type\":\"status\"}");
      break;

    case WStype_DISCONNECTED:
      Serial.println("WebSocket disconnected");
      break;

    case WStype_TEXT: {
      String message;
      message.reserve(length + 1);
      for (size_t i = 0; i < length; i++) {
        message += (char)payload[i];
      }
      handleRobotMessage(message.c_str());
      break;
    }

    default:
      break;
  }
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.persistent(false);
  WiFi.disconnect(true, true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print("Connecting to WiFi");
  unsigned long startAt = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - startAt < WIFI_CONNECT_TIMEOUT_MS) {
    delay(500);
    Serial.print(".");
  }

  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("WiFi connected. IP: ");
    Serial.println(WiFi.localIP());
    return;
  }

  Serial.print("WiFi connection failed, status: ");
  Serial.println(wifiStatusText(WiFi.status()));

  int networkCount = WiFi.scanNetworks();
  Serial.print("Visible WiFi networks: ");
  Serial.println(networkCount);
  for (int i = 0; i < networkCount; i++) {
    Serial.print("  ");
    Serial.print(i + 1);
    Serial.print(": ");
    Serial.print(WiFi.SSID(i));
    Serial.print(" (");
    Serial.print(WiFi.RSSI(i));
    Serial.println(" dBm)");
  }

  Serial.println("Check SSID/password, 2.4 GHz network availability, and signal strength.");
}

void setupWebSocket() {
  webSocket.begin(WS_HOST, WS_PORT, WS_PATH);
  webSocket.onEvent(onWebSocketEvent);
  webSocket.setReconnectInterval(2000);
}
// -------------------- SETUP --------------------
void setup() {
  Serial.begin(115200);
  motorSetup();
  connectWiFi();
  if (WiFi.status() == WL_CONNECTED) {
    setupWebSocket();
    Serial.println("Ready. Listening for WS robot commands.");
  } else {
    Serial.println("WiFi not connected yet; will retry from loop().");
  }
}

// -------------------- LOOP --------------------
void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    unsigned long now = millis();
    if (now - lastWiFiRetryAt >= WIFI_RETRY_INTERVAL_MS) {
      lastWiFiRetryAt = now;
      Serial.println("Retrying WiFi connection...");
      connectWiFi();
      if (WiFi.status() == WL_CONNECTED) {
        setupWebSocket();
      }
    }
    delay(50);
    return;
  }

  webSocket.loop();
}
