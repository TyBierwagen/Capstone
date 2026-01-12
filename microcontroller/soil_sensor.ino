/*
 * Soil Sensing Robot - Microcontroller Code (Arduino/ESP32)
 * 
 * This code is designed for ESP32/ESP8266 microcontrollers
 * with WiFi capability and analog sensors for soil monitoring.
 * 
 * Hardware Requirements:
 * - ESP32 or ESP8266 board
 * - Soil moisture sensor (analog)
 * - Temperature sensor (DHT22 or similar)
 * - pH sensor (analog)
 * - Light sensor (LDR or similar)
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// WiFi credentials - UPDATE THESE
const char* ssid = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";

// Azure Function API endpoint - UPDATE THIS
const char* apiEndpoint = "https://your-apim-gateway-url/api";

// Sensor pins
const int MOISTURE_PIN = 34;    // Analog pin for moisture sensor
const int TEMPERATURE_PIN = 35; // Analog pin for temperature sensor (or digital for DHT)
const int PH_PIN = 36;          // Analog pin for pH sensor
const int LIGHT_PIN = 39;       // Analog pin for light sensor

// Sampling configuration
unsigned long samplingInterval = 60000; // 60 seconds default
unsigned long lastSampleTime = 0;
bool isRunning = false;

// Device information
String deviceId = "";
String deviceIp = "";

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  Serial.println("\n=================================");
  Serial.println("Soil Sensing Robot Starting...");
  Serial.println("=================================\n");
  
  // Initialize sensor pins
  pinMode(MOISTURE_PIN, INPUT);
  pinMode(TEMPERATURE_PIN, INPUT);
  pinMode(PH_PIN, INPUT);
  pinMode(LIGHT_PIN, INPUT);
  
  // Connect to WiFi
  connectWiFi();
  
  // Register device with backend
  registerDevice();
  
  Serial.println("\nSetup complete! Ready to start sampling.");
  Serial.println("Waiting for start command from web interface...\n");
}

void loop() {
  // Check WiFi connection
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi disconnected. Reconnecting...");
    connectWiFi();
  }
  
  // Sample sensors if running and interval elapsed
  if (isRunning && (millis() - lastSampleTime >= samplingInterval)) {
    readAndSendSensorData();
    lastSampleTime = millis();
  }
  
  // Check for control commands (in production, use HTTP server or MQTT)
  // For now, you can send commands via serial or implement HTTP server
  
  delay(100); // Small delay to prevent tight loop
}

void connectWiFi() {
  Serial.print("Connecting to WiFi: ");
  Serial.println(ssid);
  
  WiFi.begin(ssid, password);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n✓ WiFi connected!");
    Serial.print("IP Address: ");
    deviceIp = WiFi.localIP().toString();
    Serial.println(deviceIp);
    Serial.print("Signal Strength: ");
    Serial.print(WiFi.RSSI());
    Serial.println(" dBm");
  } else {
    Serial.println("\n✗ WiFi connection failed!");
  }
}

void registerDevice() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Cannot register device - WiFi not connected");
    return;
  }
  
  Serial.println("\nRegistering device with backend...");
  
  HTTPClient http;
  String url = String(apiEndpoint) + "/devices";
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  
  // Create JSON payload
  StaticJsonDocument<200> doc;
  doc["ip"] = deviceIp;
  doc["port"] = 80;
  doc["type"] = "soil_sensor";
  
  String jsonPayload;
  serializeJson(doc, jsonPayload);
  
  int httpResponseCode = http.POST(jsonPayload);
  
  if (httpResponseCode > 0) {
    String response = http.getString();
    Serial.print("✓ Device registered! Response code: ");
    Serial.println(httpResponseCode);
    
    // Parse response to get device ID
    StaticJsonDocument<200> responseDoc;
    deserializeJson(responseDoc, response);
    deviceId = responseDoc["id"].as<String>();
    Serial.print("Device ID: ");
    Serial.println(deviceId);
  } else {
    Serial.print("✗ Registration failed. Error code: ");
    Serial.println(httpResponseCode);
  }
  
  http.end();
}

void readAndSendSensorData() {
  Serial.println("\n--- Reading Sensors ---");
  
  // Read sensor values
  float moisture = readMoisture();
  float temperature = readTemperature();
  float ph = readPH();
  int light = readLight();
  
  // Display readings
  Serial.print("Moisture: ");
  Serial.print(moisture);
  Serial.println("%");
  
  Serial.print("Temperature: ");
  Serial.print(temperature);
  Serial.println("°C");
  
  Serial.print("pH: ");
  Serial.println(ph);
  
  Serial.print("Light: ");
  Serial.print(light);
  Serial.println(" lux");
  
  // Send data to backend
  sendSensorData(moisture, temperature, ph, light);
  
  Serial.println("--- Reading Complete ---\n");
}

float readMoisture() {
  // Read analog value from moisture sensor
  int rawValue = analogRead(MOISTURE_PIN);
  
  // Convert to percentage (calibrate these values for your sensor)
  // Typical range: 0 (water) to 4095 (dry) for ESP32
  float moisture = map(rawValue, 0, 4095, 100, 0);
  moisture = constrain(moisture, 0, 100);
  
  return moisture;
}

float readTemperature() {
  // Simple analog temperature sensor reading
  // For DHT22, use DHT library instead
  int rawValue = analogRead(TEMPERATURE_PIN);
  
  // Convert to temperature (calibrate for your sensor)
  // This is a placeholder - adjust based on your sensor
  float temperature = (rawValue / 4095.0) * 50.0; // 0-50°C range
  
  return temperature;
}

float readPH() {
  // Read analog value from pH sensor
  int rawValue = analogRead(PH_PIN);
  
  // Convert to pH scale (calibrate for your sensor)
  // Typical pH range: 0-14
  float ph = (rawValue / 4095.0) * 14.0;
  
  return ph;
}

int readLight() {
  // Read analog value from light sensor
  int rawValue = analogRead(LIGHT_PIN);
  
  // Convert to lux (calibrate for your sensor)
  // This is a placeholder - adjust based on your sensor
  int lux = map(rawValue, 0, 4095, 0, 1000);
  
  return lux;
}

void sendSensorData(float moisture, float temperature, float ph, int light) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Cannot send data - WiFi not connected");
    return;
  }
  
  HTTPClient http;
  String url = String(apiEndpoint) + "/sensor-data";
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  
  // Create JSON payload
  StaticJsonDocument<300> doc;
  doc["deviceIp"] = deviceIp;
  doc["timestamp"] = getISOTimestamp();
  doc["moisture"] = moisture;
  doc["temperature"] = temperature;
  doc["ph"] = ph;
  doc["light"] = light;
  
  String jsonPayload;
  serializeJson(doc, jsonPayload);
  
  int httpResponseCode = http.POST(jsonPayload);
  
  if (httpResponseCode > 0) {
    Serial.print("✓ Data sent successfully! Response code: ");
    Serial.println(httpResponseCode);
  } else {
    Serial.print("✗ Failed to send data. Error code: ");
    Serial.println(httpResponseCode);
  }
  
  http.end();
}

String getISOTimestamp() {
  // In production, sync with NTP server
  // For now, return milliseconds since boot
  return String(millis());
}

// Optional: Implement HTTP server to receive commands from web app
void handleControlCommands(String command) {
  if (command == "start") {
    isRunning = true;
    Serial.println("✓ Sampling started");
  } else if (command == "stop") {
    isRunning = false;
    Serial.println("✓ Sampling stopped");
  }
}
