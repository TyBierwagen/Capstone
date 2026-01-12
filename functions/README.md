# Azure Functions

This directory contains the serverless backend functions for the Soil Sensing Robot application.

## Functions

### Device Management
- **POST /api/devices** - Register a new microcontroller device
  - Body: `{ "ip": "192.168.1.100", "port": 80, "type": "soil_sensor" }`

### Sensor Data
- **GET /api/sensor-data?deviceIp={ip}** - Get latest sensor readings from a device
- **POST /api/sensor-data** - Save sensor data to database
  - Body: `{ "deviceIp": "192.168.1.100", "timestamp": "ISO-8601", "moisture": 45.2, "temperature": 24.5, "ph": 6.8, "light": 450 }`

### Device Control
- **POST /api/control** - Send control commands to a device
  - Body: `{ "deviceIp": "192.168.1.100", "command": "start|stop" }`

## Local Development

1. **Install Azure Functions Core Tools**:
   ```bash
   npm install -g azure-functions-core-tools@4
   ```

2. **Install dependencies**:
   ```bash
   npm install
   ```

3. **Run locally**:
   ```bash
   npm start
   ```
   
   Functions will be available at http://localhost:7071

## Deployment

Functions are automatically deployed when you apply the Terraform configuration.

To manually deploy:

```bash
func azure functionapp publish <function-app-name>
```

## Environment Variables

The following environment variables are configured in Terraform:

- `SQL_CONNECTION_STRING` - Connection string for Azure SQL Database (from Key Vault)
- `APPLICATIONINSIGHTS_CONNECTION_STRING` - Application Insights connection string

## Database Integration

To integrate with Azure SQL Database, uncomment the database code in the functions and install the `tedious` package:

```bash
npm install tedious
```

Example database query:
```javascript
const { Connection, Request } = require('tedious');

// Use connection string from environment
const config = {
    server: 'your-server.database.windows.net',
    authentication: {
        type: 'default',
        options: {
            userName: 'username',
            password: 'password'
        }
    },
    options: {
        database: 'your-database',
        encrypt: true
    }
};
```

## API Testing

You can test the APIs using curl:

```bash
# Register device
curl -X POST http://localhost:7071/api/devices \
  -H "Content-Type: application/json" \
  -d '{"ip":"192.168.1.100","port":80,"type":"soil_sensor"}'

# Get sensor data
curl http://localhost:7071/api/sensor-data?deviceIp=192.168.1.100

# Save sensor data
curl -X POST http://localhost:7071/api/sensor-data \
  -H "Content-Type: application/json" \
  -d '{"deviceIp":"192.168.1.100","timestamp":"2024-01-01T12:00:00Z","moisture":45.2,"temperature":24.5,"ph":6.8,"light":450}'

# Control device
curl -X POST http://localhost:7071/api/control \
  -H "Content-Type: application/json" \
  -d '{"deviceIp":"192.168.1.100","command":"start"}'
```
