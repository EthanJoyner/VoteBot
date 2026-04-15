#if defined(ESP32)
#include "BluetoothSerial.h"
#else
#error "This sketch requires an ESP32 board package. In Arduino IDE, select an ESP32 board (e.g., ESP32 Dev Module)."
#endif

// Motor Pins
int ML1 = 18; // Motor Left Front - low
int ML2 = 19; // Motor Left Front - high
int MR1 = 17; // Motor Right Back - low
int MR2 = 5;  // Motor Right Back - high

BluetoothSerial SerialBT;

void motorSetup() {
  pinMode(ML1, OUTPUT);
  pinMode(ML2, OUTPUT);
  pinMode(MR1, OUTPUT);
  pinMode(MR2, OUTPUT);
}

void forward(int ms_time) {
  // Left Motor forward
  digitalWrite(ML1, LOW);
  digitalWrite(ML2, HIGH);
  // Right Motor forward
  digitalWrite(MR1, LOW);
  digitalWrite(MR2, HIGH);
  Serial.print("forward\n");
  SerialBT.print("forward\n");
  delay(ms_time);
}

void backward(int ms_time) {
  // Left Motor backward
  digitalWrite(ML1, HIGH);
  digitalWrite(ML2, LOW);
  // Right Motor backward
  digitalWrite(MR1, HIGH);
  digitalWrite(MR2, LOW);
  Serial.print("backward\n");
  SerialBT.print("backward\n");
  delay(ms_time);
}

void stop(int ms_delay) {
  digitalWrite(ML1, LOW);
  digitalWrite(ML2, LOW);
  digitalWrite(MR1, LOW);
  digitalWrite(MR2, LOW);
  Serial.print("stop\n");
  SerialBT.print("stop\n");
  delay(ms_delay);
}

void right(int ms_time) {
  // Left Motor forward
  digitalWrite(ML1, LOW);
  digitalWrite(ML2, HIGH);
  // Right motor backward
  digitalWrite(MR1, HIGH);
  digitalWrite(MR2, LOW);
  Serial.print("right\n");
  SerialBT.print("right\n");
  delay(ms_time);
}

void left(int ms_time) {
  // Left Motor backward
  digitalWrite(ML1, HIGH);
  digitalWrite(ML2, LOW);
  // Right motor forward
  digitalWrite(MR1, LOW);
  digitalWrite(MR2, HIGH);
  Serial.print("left\n");
  SerialBT.print("left\n");
  delay(ms_time);
}

void setup() {
  Serial.begin(115200);
  motorSetup();
  
  // Initialize Bluetooth with device name "VOTEBOT1"
  SerialBT.begin("VOTEBOT1", true); // true = master mode
  Serial.println("Bluetooth initialized as VOTEBOT1 (Master mode)");
  Serial.println("Waiting for Bluetooth connection...");
}

void loop() {
  // Handle Bluetooth commands
  if (SerialBT.available()) {
    String command = SerialBT.readStringUntil('\n');
    command.trim();
    command.toLowerCase();
    
    Serial.print("Received command: ");
    Serial.println(command);
    
    if (command == "forward") {
      forward(500);
    } else if (command == "backward") {
      backward(500);
    } else if (command == "left") {
      left(500);
    } else if (command == "right") {
      right(500);
    } else if (command == "stop") {
      stop(100);
    }
  }
}
