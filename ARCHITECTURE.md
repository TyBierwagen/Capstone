# Architecture Documentation

## System Overview

The Soil Sensing Robot application is a cloud-native solution deployed on Microsoft Azure. It enables real-time monitoring and control of IoT soil sensors through a web interface.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Internet / WiFi                              │
└─────────────────────────────────────────────────────────────────────┘
         │                                               │
         │ WiFi                                          │ HTTPS
         │                                               │
         ▼                                               ▼
┌──────────────────┐                            ┌──────────────────┐
│ Microcontroller  │                            │   End Users      │
│ (Soil Sensors)   │                            │   (Web Browser)  │
│                  │                            └─────────┬────────┘
│ - Moisture       │                                      │
│ - Temperature    │                                      │ HTTPS
│ - pH Level       │                                      │
│ - Light          │                                      ▼
└──────────────────┘                            ┌──────────────────┐
                                                │  Azure CDN       │
                                                │  (Global Edge)   │
                                                └─────────┬────────┘
                                                          │
                                                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Azure Cloud Platform                           │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │              Static Web App (Storage Account)               │   │
│  │  - index.html (UI)                                          │   │
│  │  - app.js (Client Logic)                                    │   │
│  └──────────────────────────┬─────────────────────────────────┘   │
│                             │ API Calls                             │
│                             ▼                                        │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │         Azure API Management (API Gateway)                  │   │
│  │  - Rate Limiting                                            │   │
│  │  - Authentication                                           │   │
│  │  - Request Routing                                          │   │
│  └──────────────────────────┬─────────────────────────────────┘   │
│                             │                                        │
│                             ▼                                        │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │           Azure Functions (Serverless Backend)              │   │
│  │                                                             │   │
│  │  ┌─────────────────┐  ┌──────────────────┐                │   │
│  │  │ Device          │  │ Sensor Data      │                │   │
│  │  │ Management      │  │ Processing       │                │   │
│  │  └─────────────────┘  └──────────────────┘                │   │
│  │  ┌─────────────────┐  ┌──────────────────┐                │   │
│  │  │ Control         │  │ Data Storage     │                │   │
│  │  │ Commands        │  │ Handler          │                │   │
│  │  └─────────────────┘  └──────────────────┘                │   │
│  └──────────────────────────┬───────────┬────────────────────┘   │
│                             │           │                          │
│                             │           │                          │
│              ┌──────────────┘           └──────────────┐          │
│              │                                          │          │
│              ▼                                          ▼          │
│  ┌─────────────────────┐                  ┌─────────────────────┐│
│  │  Azure SQL Database │                  │  Azure Key Vault    ││
│  │                     │                  │                     ││
│  │  - Device Registry  │                  │  - SQL Credentials  ││
│  │  - Sensor Data      │                  │  - API Keys         ││
│  │  - Historical Data  │                  │  - Secrets          ││
│  └─────────────────────┘                  └─────────────────────┘│
│              │                                                     │
│              │                                                     │
│              ▼                                                     │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │        Application Insights (Monitoring)                 │     │
│  │  - Telemetry                                             │     │
│  │  - Performance Metrics                                   │     │
│  │  - Error Tracking                                        │     │
│  └─────────────────────────────────────────────────────────┘     │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Frontend Layer

#### Azure CDN
- **Purpose**: Global content delivery network
- **Benefits**: 
  - Reduced latency
  - Improved load times
  - DDoS protection
- **Configuration**: Points to Azure Storage static website

#### Azure Storage (Static Website)
- **Purpose**: Host single-page web application
- **Contents**:
  - HTML5 interface
  - JavaScript application logic
  - Client-side state management
- **Features**:
  - Cost-effective hosting
  - High availability
  - HTTPS by default

### 2. API Gateway Layer

#### Azure API Management
- **Purpose**: Centralized API gateway
- **Features**:
  - Request routing
  - Rate limiting
  - API versioning
  - Authentication/Authorization
  - Request/response transformation
  - Analytics and monitoring
- **Tiers**: Consumption tier for cost optimization

### 3. Application Layer

#### Azure Functions (Serverless Backend)
- **Purpose**: Business logic and data processing
- **Functions**:
  1. **Device Management** (`POST /api/devices`)
     - Register new microcontrollers
     - Update device status
     
  2. **Sensor Data** (`GET/POST /api/sensor-data`)
     - Retrieve latest sensor readings
     - Store sensor data to database
     
  3. **Control Commands** (`POST /api/control`)
     - Send commands to devices
     - Start/stop sampling
     
- **Runtime**: Node.js 18
- **Scaling**: Automatic based on demand
- **Cost Model**: Pay-per-execution

### 4. Data Layer

#### Azure SQL Database
- **Purpose**: Persistent data storage
- **Schema**:
  ```sql
  -- Devices table
  CREATE TABLE Devices (
      DeviceId NVARCHAR(50) PRIMARY KEY,
      IpAddress NVARCHAR(45),
      Port INT,
      DeviceType NVARCHAR(50),
      RegisteredAt DATETIME,
      LastSeen DATETIME,
      Status NVARCHAR(20)
  );
  
  -- SensorData table
  CREATE TABLE SensorData (
      DataId BIGINT IDENTITY(1,1) PRIMARY KEY,
      DeviceId NVARCHAR(50),
      Timestamp DATETIME,
      Moisture DECIMAL(5,2),
      Temperature DECIMAL(5,2),
      PhLevel DECIMAL(3,1),
      LightLevel INT,
      FOREIGN KEY (DeviceId) REFERENCES Devices(DeviceId)
  );
  ```
- **Tier**: Basic (upgradeable)
- **Backup**: Automated daily backups

### 5. Security Layer

#### Azure Key Vault
- **Purpose**: Secure secrets management
- **Stored Secrets**:
  - SQL connection strings
  - API keys
  - Service credentials
- **Access**: Managed Identity integration with Functions

### 6. Monitoring Layer

#### Application Insights
- **Purpose**: Application performance monitoring
- **Metrics Tracked**:
  - Request rates
  - Response times
  - Error rates
  - Custom telemetry
  - User analytics
- **Features**:
  - Real-time monitoring
  - Alerting
  - Log analytics

## Data Flow

### 1. Device Registration Flow
```
User → Web App → API Gateway → Functions → SQL Database
                                        ↓
                                   Key Vault (credentials)
```

### 2. Sensor Data Collection Flow
```
Microcontroller → WiFi → Functions → SQL Database
                            ↓
                     Application Insights
```

### 3. Data Retrieval Flow
```
User → Web App → API Gateway → Functions → SQL Database
                                        ↓
                                   Cache (future)
```

### 4. Control Command Flow
```
User → Web App → API Gateway → Functions → Microcontroller (via WiFi)
                                        ↓
                                   SQL Database (audit log)
```

## Network Architecture

### Connectivity
- **Public Internet**: Used for web app access
- **WiFi**: Local network for microcontroller communication
- **Azure VNet**: Optional for enhanced security (not implemented in basic version)

### Security
- **TLS/SSL**: All communications encrypted
- **CORS**: Configured for web app domain
- **Authentication**: Optional OAuth/Azure AD integration
- **Authorization**: Function-level authorization codes

## Scalability

### Horizontal Scaling
- **Functions**: Auto-scale based on load
- **SQL Database**: Can upgrade to higher tiers
- **CDN**: Globally distributed by default
- **Storage**: Virtually unlimited capacity

### Performance Optimization
- **CDN Caching**: Static content cached at edge
- **Connection Pooling**: SQL connections reused
- **Async Processing**: Non-blocking I/O
- **Compression**: Content compressed for transfer

## High Availability

### Service SLAs
- Azure Functions: 99.95%
- Azure SQL Database: 99.99%
- Azure Storage: 99.9%
- Azure CDN: 99.9%
- API Management: 99.95%

### Disaster Recovery
- **Database**: Point-in-time restore (7-35 days)
- **Storage**: Geo-redundant option available
- **Functions**: Multi-region deployment possible

## Cost Optimization

### Current Configuration
- **Consumption-based pricing** for Functions and APIM
- **Basic tier** for SQL Database
- **Standard LRS** for Storage
- **Standard tier** for CDN

### Monthly Estimate (Dev/Test)
- Storage: $1-2
- Functions: $0-5 (low usage)
- SQL Database: $5
- APIM: $0-5 (low usage)
- CDN: $0-2
- **Total: ~$13-20/month**

## Future Enhancements

### Planned Features
1. **Real-time Updates**: SignalR for live data streaming
2. **Machine Learning**: Predictive analytics for soil conditions
3. **Mobile App**: Native iOS/Android applications
4. **IoT Hub**: Replace direct WiFi with Azure IoT Hub
5. **Analytics Dashboard**: Power BI integration
6. **Alerting**: SMS/Email notifications for critical conditions

### Security Enhancements
1. OAuth 2.0 authentication
2. Azure AD integration
3. Private endpoints for services
4. VNet integration
5. DDoS protection standard

## Deployment

### Infrastructure as Code
All infrastructure defined in Terraform:
- Version controlled
- Reproducible
- Environment isolation
- Automated deployment

### CI/CD Pipeline (Future)
```
GitHub → GitHub Actions → Terraform → Azure
                      ↓
                   Azure Functions
                      ↓
                   Storage (Web App)
```

## Monitoring and Alerts

### Key Metrics
1. Function execution count
2. Function execution duration
3. API response times
4. SQL database DTU usage
5. Storage transaction counts
6. CDN bandwidth usage

### Alerts
- Failed function executions
- High response times
- Database throttling
- Storage quota warnings

## Compliance and Governance

### Tags
All resources tagged with:
- Project name
- Environment
- Managed by (Terraform)
- Cost center

### Resource Naming
Convention: `{project}-{resource}-{environment}`
Example: `soilrobot-func-dev`

## Support and Maintenance

### Backup Strategy
- SQL Database: Automated daily backups
- Infrastructure: Terraform state in version control
- Application Code: Git repository

### Update Strategy
- Rolling updates for functions
- Blue-green deployment for web app
- Database schema versioning with migrations

## References

- [Azure Functions Documentation](https://docs.microsoft.com/azure/azure-functions/)
- [Azure API Management Documentation](https://docs.microsoft.com/azure/api-management/)
- [Azure SQL Database Documentation](https://docs.microsoft.com/azure/sql-database/)
- [Terraform Azure Provider](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs)
