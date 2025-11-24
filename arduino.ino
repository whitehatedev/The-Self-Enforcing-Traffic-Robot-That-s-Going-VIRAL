#include <WiFi.h>
#include <WebServer.h>

// WiFi credentials - UPDATE THESE
const char* ssid = "Airtel_sahi_0849";
const char* password = "air99772";

// Motor pins with EN pins (L298N with Enable pins)
const int enA = 2;      // Enable pin Motor A
const int motor1Pin1 = 4;  // IN1
const int motor1Pin2 = 5;  // IN2
const int enB = 12;     // Enable pin Motor B
const int motor2Pin1 = 13; // IN3
const int motor2Pin2 = 14; // IN4

// Ultrasonic sensor pins
const int trigPin = 26;
const int echoPin = 27;

WebServer server(80);

// Car status
bool isBlocked = false;
bool atHomePosition = false;
bool isMoving = false;
bool shouldStopAtHome = false;
String currentDirection = "STOP";

// PWM settings
const int pwmSpeed = 200; // PWM speed (0-255)
const int homeDistance = 15; // 15cm for home position
const unsigned long homeCheckInterval = 1000; // Check home position every 1 second
unsigned long lastHomeCheck = 0;

// Ultrasonic functions
long readUltrasonic() {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);

  long duration = pulseIn(echoPin, HIGH, 30000); // 30ms timeout
  if (duration == 0) {
    return -1; // Error reading
  }

  long distance = duration * 0.034 / 2;

  // Validate distance reading
  if (distance > 400 || distance < 0) {
    return -1; // Invalid reading
  }

  return distance;
}

bool checkHomePosition() {
  long distance = readUltrasonic();

  // Check if at home position (within 15cm)
  bool isHome = (distance <= homeDistance && distance > 0);

  if (isHome && !atHomePosition) {
    Serial.println("🏠 At Home Position");
    atHomePosition = true;

    // If vehicle is blocked and reaches home, stop it
    if (isBlocked && isMoving) {
      Serial.println("🚫 Vehicle blocked and reached home - Stopping");
      stopCar();
    }
  } else if (!isHome && atHomePosition) {
    atHomePosition = false;
    Serial.println("📍 Left Home Position");
  }

  return isHome;
}

void setup() {
  Serial.begin(115200);

  // Setup motor pins
  pinMode(enA, OUTPUT);
  pinMode(motor1Pin1, OUTPUT);
  pinMode(motor1Pin2, OUTPUT);
  pinMode(enB, OUTPUT);
  pinMode(motor2Pin1, OUTPUT);
  pinMode(motor2Pin2, OUTPUT);

  // Setup ultrasonic
  pinMode(trigPin, OUTPUT);
  pinMode(echoPin, INPUT);

  // Set initial motor state - STOP
  stopCar();

  // Connect to WiFi
  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(1000);
    Serial.print(".");
  }
  Serial.println("\nConnected to WiFi");
  Serial.print("IP Address: ");
  Serial.println(WiFi.localIP());

  // Setup server routes
  server.on("/", HTTP_GET, []() {
    String html = "<html><body>";
    html += "<h1>🤖 ESP32 Car Controller</h1>";
    html += "<p>Vehicle: MH19EQ0009</p>";
    html += "<p>Status: " + String(isBlocked ? "FINE NOTICE ACTIVE" : "ACTIVE") + "</p>";
    html += "<p>Home Position: " + String(atHomePosition ? "AT HOME" : "NOT AT HOME") + "</p>";

    long distance = readUltrasonic();
    html += "<p>Distance: " + String(distance) + " cm</p>";
    html += "<p>Movement Policy: " + String(isBlocked ? "Stop at home position" : "Free movement") + "</p>";
    html += "<p>Endpoints: /forward, /backward, /left, /right, /stop, /status, /block, /unblock, /test_ultrasonic</p>";
    html += "<p><a href='/test_ultrasonic'>Test Ultrasonic Sensor</a></p>";
    html += "</body></html>";

    server.send(200, "text/html", html);
  });

  server.on("/forward", HTTP_GET, []() {
    // Allow movement unless blocked AND at home position
    if (isBlocked && atHomePosition) {
      server.send(403, "application/json", "{\"status\":\"blocked\",\"direction\":\"stop\",\"blocked\":true,\"home\":true,\"message\":\"Vehicle blocked at home - pay fine first\"}");
    } else {
      moveForward();
      server.send(200, "application/json", "{\"status\":\"moving\",\"direction\":\"forward\",\"blocked\":" + String(isBlocked ? "true" : "false") + ",\"home\":" + String(atHomePosition ? "true" : "false") + "}");
    }
  });

  server.on("/backward", HTTP_GET, []() {
    // Allow movement unless blocked AND at home position
    if (isBlocked && atHomePosition) {
      server.send(403, "application/json", "{\"status\":\"blocked\",\"direction\":\"stop\",\"blocked\":true,\"home\":true,\"message\":\"Vehicle blocked at home - pay fine first\"}");
    } else {
      moveBackward();
      server.send(200, "application/json", "{\"status\":\"moving\",\"direction\":\"backward\",\"blocked\":" + String(isBlocked ? "true" : "false") + ",\"home\":" + String(atHomePosition ? "true" : "false") + "}");
    }
  });

  server.on("/left", HTTP_GET, []() {
    // Allow movement unless blocked AND at home position
    if (isBlocked && atHomePosition) {
      server.send(403, "application/json", "{\"status\":\"blocked\",\"direction\":\"stop\",\"blocked\":true,\"home\":true,\"message\":\"Vehicle blocked at home - pay fine first\"}");
    } else {
      turnLeft();
      server.send(200, "application/json", "{\"status\":\"moving\",\"direction\":\"left\",\"blocked\":" + String(isBlocked ? "true" : "false") + ",\"home\":" + String(atHomePosition ? "true" : "false") + "}");
    }
  });

  server.on("/right", HTTP_GET, []() {
    // Allow movement unless blocked AND at home position
    if (isBlocked && atHomePosition) {
      server.send(403, "application/json", "{\"status\":\"blocked\",\"direction\":\"stop\",\"blocked\":true,\"home\":true,\"message\":\"Vehicle blocked at home - pay fine first\"}");
    } else {
      turnRight();
      server.send(200, "application/json", "{\"status\":\"moving\",\"direction\":\"right\",\"blocked\":" + String(isBlocked ? "true" : "false") + ",\"home\":" + String(atHomePosition ? "true" : "false") + "}");
    }
  });

  server.on("/stop", HTTP_GET, []() {
    stopCar();
    server.send(200, "application/json", "{\"status\":\"stopped\",\"direction\":\"stop\",\"blocked\":" + String(isBlocked ? "true" : "false") + ",\"home\":" + String(atHomePosition ? "true" : "false") + "}");
  });

  server.on("/status", HTTP_GET, []() {
    String status = isBlocked ? "fine_notice" : "active";
    String moving = isMoving ? "moving" : "stopped";
    String home = atHomePosition ? "home" : "not_home";
    long distance = readUltrasonic();

    // Proper JSON formatting
    String json = "{";
    json += "\"status\":\"" + status + "\",";
    json += "\"moving\":\"" + moving + "\",";
    json += "\"direction\":\"" + currentDirection + "\",";
    json += "\"home\":\"" + home + "\",";
    json += "\"distance\":" + String(distance) + ",";
    json += "\"vehicle\":\"MH19EQ0009\"";
    json += "}";

    server.send(200, "application/json", json);
  });

  server.on("/block", HTTP_GET, []() {
    isBlocked = true;
    Serial.println("🚫 Fine notice received - Vehicle will stop when reaching home position");

    server.send(200, "application/json", "{\"status\":\"fine_notice\",\"home\":" + String(atHomePosition ? "true" : "false") + ",\"message\":\"Fine notice active - vehicle will stop when reaching home\"}");
  });

  server.on("/unblock", HTTP_GET, []() {
    isBlocked = false;
    server.send(200, "application/json", "{\"status\":\"active\",\"message\":\"Vehicle unblocked - fine paid\"}");
  });

  server.on("/emergency_stop", HTTP_GET, []() {
    emergencyStop();
    server.send(200, "application/json", "{\"status\":\"emergency_stop\",\"message\":\"Emergency stop activated\"}");
  });

  server.on("/test_ultrasonic", HTTP_GET, []() {
    String html = "<html><body>";
    html += "<h1>🔊 Ultrasonic Sensor Test</h1>";

    long distance = readUltrasonic();
    html += "<p>Current Distance: <span style='font-size: 24px; font-weight: bold;'>" + String(distance) + "</span> cm</p>";
    html += "<button onclick='refreshDistance()'>Refresh Distance</button>";
    html += "<script>function refreshDistance() { location.reload(); }</script>";
    html += "<h3>Test Results:</h3>";

    if (distance <= homeDistance && distance > 0) {
      html += "<p style='color: green; font-size: 18px;'>✅ At Home Position (" + String(distance) + "cm)</p>";
    } else if (distance > homeDistance) {
      html += "<p style='color: orange; font-size: 18px;'>📍 Not at Home (" + String(distance) + "cm - need to be within " + String(homeDistance) + "cm)</p>";
    } else {
      html += "<p style='color: red; font-size: 18px;'>❌ Sensor Error (distance: " + String(distance) + "cm)</p>";
    }

    html += "<h3>System Status:</h3>";
    html += "<ul>";
    html += "<li>Home Distance Threshold: " + String(homeDistance) + "cm</li>";
    html += "<li>Current Home Status: " + String(atHomePosition ? "AT HOME" : "NOT AT HOME") + "</li>";
    html += "<li>Fine Notice: " + String(isBlocked ? "ACTIVE" : "INACTIVE") + "</li>";
    html += "<li>Vehicle Moving: " + String(isMoving ? "YES" : "NO") + "</li>";
    html += "</ul>";

    html += "<h3>Movement Policy:</h3>";
    html += "<ul>";
    html += "<li>Fine Notice INACTIVE: Free movement</li>";
    html += "<li>Fine Notice ACTIVE: Stop when reaching home position</li>";
    html += "<li>Place vehicle within " + String(homeDistance) + "cm for home position</li>";
    html += "</ul>";
    html += "<p><a href='/'>Back to Main</a></p>";
    html += "</body></html>";

    server.send(200, "text/html", html);
  });

  server.on("/debug", HTTP_GET, []() {
    String json = "{";
    json += "\"ultrasonic_distance\":" + String(readUltrasonic()) + ",";
    json += "\"at_home_position\":" + String(atHomePosition ? "true" : "false") + ",";
    json += "\"is_blocked\":" + String(isBlocked ? "true" : "false") + ",";
    json += "\"is_moving\":" + String(isMoving ? "true" : "false") + ",";
    json += "\"current_direction\":\"" + currentDirection + "\"";
    json += "}";

    server.send(200, "application/json", json);
  });

  server.on("/simple_status", HTTP_GET, []() {
    // Simple status endpoint for quick testing
    long distance = readUltrasonic();
    String response = "Status: " + String(isBlocked ? "FINE NOTICE" : "ACTIVE");
    response += " | Home: " + String(atHomePosition ? "YES" : "NO");
    response += " | Distance: " + String(distance) + "cm";
    response += " | Moving: " + String(isMoving ? "YES" : "NO");

    server.send(200, "text/plain", response);
  });

  server.begin();
  Serial.println("HTTP server started");
  Serial.println("🤖 Vehicle Control System Ready");
  Serial.println("🚗 Commands: forward, backward, left, right, stop");
  Serial.println("💰 Fine System: /block, /unblock");
  Serial.println("📊 Status: /status");
  Serial.println("🔍 Debug: /debug");
  Serial.println("🔊 Ultrasonic Test: /test_ultrasonic");
  Serial.println("🏠 Home Position: " + String(homeDistance) + "cm from sensor");
  Serial.println("🎯 Movement Policy: Stop only when reaching home after fine notice");

  // Test ultrasonic sensor on startup
  long startupDistance = readUltrasonic();
  Serial.println("🔊 Startup Ultrasonic Test: " + String(startupDistance) + "cm");
}

void loop() {
  server.handleClient();

  // Check home position periodically
  if (millis() - lastHomeCheck >= homeCheckInterval) {
    checkHomePosition();
    lastHomeCheck = millis();
  }

  delay(100);
}

void moveForward() {
  // Allow movement unless blocked AND at home position
  if (isBlocked && atHomePosition) {
    Serial.println("❌ Blocked at home: Cannot move forward - pay fine first");
    return;
  }

  analogWrite(enA, pwmSpeed);
  analogWrite(enB, pwmSpeed);
  digitalWrite(motor1Pin1, HIGH);
  digitalWrite(motor1Pin2, LOW);
  digitalWrite(motor2Pin1, HIGH);
  digitalWrite(motor2Pin2, LOW);

  isMoving = true;
  currentDirection = "FORWARD";
  Serial.println("🔼 Moving Forward");
}

void moveBackward() {
  // Allow movement unless blocked AND at home position
  if (isBlocked && atHomePosition) {
    Serial.println("❌ Blocked at home: Cannot move backward - pay fine first");
    return;
  }

  analogWrite(enA, pwmSpeed);
  analogWrite(enB, pwmSpeed);
  digitalWrite(motor1Pin1, LOW);
  digitalWrite(motor1Pin2, HIGH);
  digitalWrite(motor2Pin1, LOW);
  digitalWrite(motor2Pin2, HIGH);

  isMoving = true;
  currentDirection = "BACKWARD";
  Serial.println("🔽 Moving Backward");
}

void turnLeft() {
  // Allow movement unless blocked AND at home position
  if (isBlocked && atHomePosition) {
    Serial.println("❌ Blocked at home: Cannot turn left - pay fine first");
    return;
  }

  analogWrite(enA, pwmSpeed);
  analogWrite(enB, pwmSpeed);
  digitalWrite(motor1Pin1, LOW);
  digitalWrite(motor1Pin2, HIGH);
  digitalWrite(motor2Pin1, HIGH);
  digitalWrite(motor2Pin2, LOW);

  isMoving = true;
  currentDirection = "LEFT";
  Serial.println("↩️ Turning Left");
}

void turnRight() {
  // Allow movement unless blocked AND at home position
  if (isBlocked && atHomePosition) {
    Serial.println("❌ Blocked at home: Cannot turn right - pay fine first");
    return;
  }

  analogWrite(enA, pwmSpeed);
  analogWrite(enB, pwmSpeed);
  digitalWrite(motor1Pin1, HIGH);
  digitalWrite(motor1Pin2, LOW);
  digitalWrite(motor2Pin1, LOW);
  digitalWrite(motor2Pin2, HIGH);

  isMoving = true;
  currentDirection = "RIGHT";
  Serial.println("↪️ Turning Right");
}

void stopCar() {
  digitalWrite(motor1Pin1, LOW);
  digitalWrite(motor1Pin2, LOW);
  digitalWrite(motor2Pin1, LOW);
  digitalWrite(motor2Pin2, LOW);
  analogWrite(enA, 0);
  analogWrite(enB, 0);

  isMoving = false;
  currentDirection = "STOP";
  Serial.println("🛑 Stopped");
}

void emergencyStop() {
  digitalWrite(motor1Pin1, LOW);
  digitalWrite(motor1Pin2, LOW);
  digitalWrite(motor2Pin1, LOW);
  digitalWrite(motor2Pin2, LOW);
  analogWrite(enA, 0);
  analogWrite(enB, 0);

  isMoving = false;
  currentDirection = "EMERGENCY_STOP";
  Serial.println("🚨 EMERGENCY STOP");
}