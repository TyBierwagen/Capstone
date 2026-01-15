from pathlib import Path
path = Path('microcontroller/soil_sensor.ino')
path.write_text("""#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <DHT.h>

// WiFi credentials (set before deployment)
const char* ssid = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";

// API gateway that fronts the backend
const char* apiGatewayBase = "https://your-api-gateway-url/api";
const char* sensorEndpoint = "/sensor-data";

// Sensor pins
const int MOISTURE_PIN = 34;
const int PH_PIN = 36;
const int LIGHT_PIN = 39;
#define DHT_PIN 15
#define DHTTYPE DHT11

// Sampling cadence
const unsigned long SAMPLE_INTERVAL_MS = 60000;
unsigned long lastSampleTime = 0;

String deviceId;
String deviceIp;

DHT dht(DHT_PIN, DHTTYPE);

void setup() {
  Serial.begin(115200);
  delay(500);
  dht.begin();

  connectWiFi();
  deviceId = WiFi.macAddress();
  deviceIp = WiFi.localIP().toString();

  Serial.println("=== Soil Sensor Connected ===");
  Serial.print("Device ID: ");
  Serial.println(deviceId);
  Serial.print("IP Address: ");
  Serial.println(deviceIp);
  Serial.print("Backend: ");
  Serial.println(apiGatewayBase);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
    return;
  }

  if (millis() - lastSampleTime >= SAMPLE_INTERVAL_MS) {
    readAndSendSensorData();
    lastSampleTime = millis();
  }

  delay(250);
}

void connectWiFi() {
  Serial.print("Connecting to WiFi ");
  Serial.println(ssid);

  WiFi.begin(ssid, password);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print('.');
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi connected");
    deviceIp = WiFi.localIP().toString();
  } else {
    Serial.println("\nFailed to join WiFi network");
  }
}

void readAndSendSensorData() {
  Serial.println("\nReading sensors...");

  float moisture = readMoisture();
  float temperature = readTemperature();
  float humidity = readHumidity();
  float ph = readPH();
  int light = readLight();

  Serial.printf("Moisture: %.1f%%\n", moisture);
  Serial.printf("Temperature: %.1f°C\n", temperature);
  Serial.printf("Humidity: %.1f%%\n", humidity);
  Serial.printf("pH: %.2f\n", ph);
  Serial.printf("Light: %d lux\n", light);

  sendSensorData(moisture, temperature, humidity, ph, light);
}

float readMoisture() {
  int raw = analogRead(MOISTURE_PIN);
  float value = map(raw, 0, 4095, 100, 0);
  return constrain(value, 0, 100);
}

float readTemperature() {
  float temp = dht.readTemperature();
  if (isnan(temp)) {
    temp = 0;
  }
  return temp;
}

float readHumidity() {
  float hum = dht.readHumidity();
  if (isnan(hum)) {
    hum = 0;
  }
  return hum;
}

float readPH() {
  int raw = analogRead(PH_PIN);
  return (raw / 4095.0) * 14.0;
}

int readLight() {
  int raw = analogRead(LIGHT_PIN);
  return map(raw, 0, 4095, 0, 1000);
}

void sendSensorData(float moisture, float temperature, float humidity, float ph, int light) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi disconnected. Skipping upload.");
    return;
  }

  HTTPClient http;
  String url = String(apiGatewayBase) + sensorEndpoint;
  http.begin(url);
  http.addHeader("Content-Type", "application/json");

  StaticJsonDocument<384> payload;
  payload["deviceIp"] = deviceIp;
  payload["deviceId"] = deviceId;
  payload["timestamp"] = nowTimestamp();
  payload["moisture"] = moisture;
  payload["temperature"] = temperature;
  payload["humidity"] = humidity;
  payload["ph"] = ph;
  payload["light"] = light;

  String body;
  serializeJson(payload, body);

  int responseCode = http.POST(body);

  if (responseCode >= 200 && responseCode < 300) {
    Serial.printf("Uploaded sensor data (code %d)\n", responseCode);
  } else {
    Serial.printf("Failed to upload (code %d)\n", responseCode);
  }

  http.end();
}

String nowTimestamp() {
  unsigned long seconds = millis() / 1000;
  unsigned long minutes = seconds / 60;
  unsigned long hours = minutes / 60;
  minutes %= 60;
  seconds %= 60;
  char buffer[20];
  snprintf(buffer, sizeof(buffer), "%02lu:%02lu:%02lu", hours, minutes, seconds);
  return String(buffer);
}
""", encoding='utf-8')
