# Microcontroller Code

This directory contains sample code for the microcontroller (ESP32/ESP8266) that communicates with the Azure backend.

## Hardware Requirements

### Microcontroller
- ESP32 or ESP8266 board with WiFi
- USB cable for programming
- Power supply (5V, 1A minimum)

### Sensors
1. **Soil Moisture Sensor**
   - Capacitive or resistive type
   - Output: Analog (0-3.3V)
   - Connection: Analog pin (e.g., GPIO34)

2. **Temperature Sensor**
   - DHT22, DS18B20, or analog temperature sensor
   - Output: Digital or Analog
   - Connection: Digital or Analog pin

3. **pH Sensor**
   - Analog pH sensor module
   - Output: Analog (0-3.3V)
   - Connection: Analog pin (e.g., GPIO36)

4. **Light Sensor**
   - LDR (Light Dependent Resistor) or BH1750
   - Output: Analog (0-3.3V)
   - Connection: Analog pin (e.g., GPIO39)

## Arduino IDE Setup

1. **Install Arduino IDE**
   - Download from https://www.arduino.cc/en/software

2. **Install ESP32/ESP8266 Board Support**
   - Open Arduino IDE
   - Go to File → Preferences
   - Add board URL:
     - ESP32: `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`
     - ESP8266: `http://arduino.esp8266.com/stable/package_esp8266com_index.json`
   - Go to Tools → Board → Boards Manager
   - Search and install "ESP32" or "ESP8266"

3. **Install Required Libraries**
   - Go to Sketch → Include Library → Manage Libraries
   - Install:
     - `ArduinoJson` (version 6.x)
     - `WiFi` (built-in for ESP32/ESP8266)
     - `HTTPClient` (built-in)
     - Optional: `DHT sensor library` if using DHT22

## Configuration

1. **Update WiFi Credentials**
   ```cpp
   const char* ssid = "YOUR_WIFI_SSID";
   const char* password = "YOUR_WIFI_PASSWORD";
   ```

2. **Update API Endpoint**
   ```cpp
   const char* apiEndpoint = "https://your-apim-gateway-url/api";
   ```
   
   Get this URL from Terraform output:
   ```bash
   cd terraform
   terraform output api_management_gateway_url
   ```

3. **Adjust Sensor Pins**
   Match the pin numbers to your actual wiring:
   ```cpp
   const int MOISTURE_PIN = 34;
   const int TEMPERATURE_PIN = 35;
   const int PH_PIN = 36;
   const int LIGHT_PIN = 39;
   ```

## Wiring Diagram

### ESP32 Connections
```
ESP32          Sensors
-----          -------
GPIO34    →    Moisture Sensor (Analog Out)
GPIO35    →    Temperature Sensor (Analog Out)
GPIO36    →    pH Sensor (Analog Out)
GPIO39    →    Light Sensor (Analog Out)
3.3V      →    Sensors VCC
GND       →    Sensors GND
```

### Notes
- Use 3.3V for sensor power (not 5V) on ESP32
- Most ESP32 analog pins support 0-3.3V input
- Some sensors may need voltage dividers

## Sensor Calibration

### Moisture Sensor
1. Test in dry air: note the reading
2. Test in water: note the reading
3. Adjust the map() function:
   ```cpp
   float moisture = map(rawValue, DRY_VALUE, WET_VALUE, 0, 100);
   ```

### pH Sensor
1. Use pH 4, 7, and 10 calibration solutions
2. Measure voltage at each pH
3. Create calibration curve
4. Adjust conversion formula

### Temperature Sensor
- If using DHT22, replace analog reading with DHT library calls
- For analog sensors, calibrate against known temperature

### Light Sensor
- Calibrate in different lighting conditions
- Adjust lux conversion based on sensor datasheet

## Uploading Code

1. Connect ESP32/ESP8266 to computer via USB
2. Select correct board: Tools → Board → ESP32 Dev Module
3. Select correct port: Tools → Port → /dev/ttyUSB0 (or COM port on Windows)
4. Click Upload button
5. Monitor serial output: Tools → Serial Monitor (115200 baud)

## Serial Monitor Output

Expected output:
```
=================================
Soil Sensing Robot Starting...
=================================

Connecting to WiFi: YourNetwork
................
✓ WiFi connected!
IP Address: 192.168.1.100
Signal Strength: -65 dBm

Registering device with backend...
✓ Device registered! Response code: 200
Device ID: dev_1234567890_abc123xyz

Setup complete! Ready to start sampling.
Waiting for start command from web interface...
```

## Troubleshooting

### WiFi Connection Failed
- Check SSID and password
- Verify WiFi is 2.4GHz (ESP8266/ESP32 don't support 5GHz)
- Check signal strength
- Restart microcontroller

### Cannot Register Device
- Verify API endpoint URL is correct
- Check internet connectivity
- Verify HTTPS certificate (may need to add root CA)
- Check firewall settings

### Sensor Readings Incorrect
- Check wiring and connections
- Verify power supply (3.3V)
- Calibrate sensors
- Check for loose connections

### Upload Failed
- Check USB cable (must support data, not just power)
- Verify correct board and port selected
- Try different USB port
- Press BOOT button during upload (some boards)

## Advanced Features

### Adding NTP Time Sync
```cpp
#include <time.h>

void syncTime() {
  configTime(0, 0, "pool.ntp.org");
  struct tm timeinfo;
  if (getLocalTime(&timeinfo)) {
    Serial.println("Time synchronized");
  }
}
```

### Adding HTTP Server for Commands
```cpp
#include <WebServer.h>

WebServer server(80);

void handleStart() {
  isRunning = true;
  server.send(200, "text/plain", "Started");
}

void setup() {
  // ... existing setup code ...
  server.on("/start", handleStart);
  server.begin();
}

void loop() {
  server.handleClient();
  // ... existing loop code ...
}
```

### Deep Sleep for Battery Operation
```cpp
void goToSleep() {
  Serial.println("Going to sleep for 60 seconds");
  esp_sleep_enable_timer_wakeup(60 * 1000000); // 60 seconds
  esp_deep_sleep_start();
}
```

## Security Considerations

- Use HTTPS for API calls
- Store WiFi credentials securely
- Implement device authentication
- Use API keys for backend communication
- Encrypt sensitive data

## Power Consumption

Typical power usage:
- Active WiFi: 80-170mA
- Deep sleep: 10-150µA
- Consider solar panel for outdoor deployment

## Testing

1. **Test sensors individually**: Read values in serial monitor
2. **Test WiFi connection**: Verify IP address obtained
3. **Test API communication**: Check backend receives data
4. **Test end-to-end**: Use web interface to start/stop sampling

## Backend Connectivity

- MCU samples send their latest readings to `POST /api/sensor-data` when `isRunning` is true. The payload now includes `deviceId`, `deviceIp`, and `commandStatus`, which allows the web UI to show live values.
- Every 5 seconds the board polls `GET /api/control?deviceIp=<your-ip>&consume=true` so commands issued from the website (`start`, `stop`, future modes) propagate immediately. If no command is queued the endpoint replies with `command: null`.
- Ensure `apiEndpoint` points at the gateway that fronts the Azure Functions (for local debugging it is `http://localhost:7071/api`).

## Additional Resources

- [ESP32 Documentation](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/)
- [Arduino ESP32 Core](https://github.com/espressif/arduino-esp32)
- [ArduinoJson Library](https://arduinojson.org/)
