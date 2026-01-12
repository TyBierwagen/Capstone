# Soil Sensing Robot - Capstone Project

A web application that connects to a microcontroller via WiFi for monitoring and controlling a soil sensing robot. The infrastructure is deployed on Microsoft Azure using Infrastructure as Code (Terraform).

## 🏗️ Architecture

This project implements a modern cloud-native architecture on Azure:

```
┌─────────────────┐
│ Microcontroller │ ◄──► WiFi ◄──► ┌──────────────┐
│  (Soil Sensor)  │                 │   Web App    │
└─────────────────┘                 │ (Azure CDN)  │
                                    └──────┬───────┘
                                           │
                                           ▼
                                    ┌──────────────┐
                                    │ API Gateway  │
                                    │   (APIM)     │
                                    └──────┬───────┘
                                           │
                                           ▼
                                    ┌──────────────┐
                                    │   Azure      │
                                    │  Functions   │
                                    └──────┬───────┘
                                           │
                                           ▼
                                    ┌──────────────┐
                                    │  Azure SQL   │
                                    │  Database    │
                                    └──────────────┘
```

### Components

- **Web Application**: Static HTML/JavaScript app hosted on Azure Storage with CDN
- **API Gateway**: Azure API Management for routing and securing API calls
- **Serverless Backend**: Azure Functions for processing requests
- **Database**: Azure SQL Database for storing sensor data
- **CDN**: Azure CDN for global content delivery
- **Monitoring**: Application Insights for telemetry
- **Security**: Azure Key Vault for secrets management

## 📁 Project Structure

```
.
├── terraform/              # Infrastructure as Code
│   ├── main.tf            # Main Terraform configuration
│   ├── variables.tf       # Variable definitions
│   ├── outputs.tf         # Output values
│   └── README.md          # Terraform documentation
├── web-app/               # Frontend web application
│   ├── index.html         # Main HTML file
│   └── app.js             # JavaScript application logic
├── functions/             # Azure Functions (serverless backend)
│   ├── src/functions/     # Function implementations
│   ├── package.json       # Node.js dependencies
│   └── README.md          # Functions documentation
└── README.md              # This file
```

## 🚀 Getting Started

### Prerequisites

1. [Azure Account](https://azure.microsoft.com/free/)
2. [Terraform](https://www.terraform.io/downloads.html) >= 1.0
3. [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli)
4. [Node.js](https://nodejs.org/) >= 18 (for local development)
5. [Azure Functions Core Tools](https://docs.microsoft.com/en-us/azure/azure-functions/functions-run-local) (optional, for local testing)

### Quick Start

1. **Clone the repository**:
   ```bash
   git clone https://github.com/TyBierwagen/Capstone.git
   cd Capstone
   ```

2. **Login to Azure**:
   ```bash
   az login
   ```

3. **Deploy Infrastructure**:
   ```bash
   cd terraform
   cp terraform.tfvars.example terraform.tfvars
   # Edit terraform.tfvars with your values
   terraform init
   terraform apply
   ```

4. **Deploy Web Application**:
   ```bash
   # Get storage account name from Terraform output
   STORAGE_ACCOUNT=$(terraform output -raw storage_account_name)
   
   # Upload web app files
   az storage blob upload-batch \
     --account-name $STORAGE_ACCOUNT \
     --source ../web-app \
     --destination '$web' \
     --overwrite
   ```

5. **Deploy Azure Functions**:
   ```bash
   cd ../functions
   npm install
   
   # Get function app name from Terraform output
   FUNCTION_APP=$(cd ../terraform && terraform output -raw function_app_name)
   
   # Deploy functions
   func azure functionapp publish $FUNCTION_APP
   ```

6. **Access Your Application**:
   ```bash
   # Get the CDN URL
   cd ../terraform
   terraform output cdn_endpoint_url
   ```

## 💻 Local Development

### Testing the Web App Locally

```bash
cd web-app
python3 -m http.server 8000
# Open http://localhost:8000 in your browser
```

### Testing Functions Locally

```bash
cd functions
npm install
npm start
# Functions available at http://localhost:7071
```

## 🔧 Configuration

### Terraform Variables

Key variables in `terraform/variables.tf`:

- `project_name`: Name prefix for all resources (default: "soilrobot")
- `environment`: Environment name (dev/staging/prod)
- `location`: Azure region (default: "eastus")
- `sql_admin_password`: SQL Server password (required, sensitive)

### Environment-Specific Deployments

Deploy multiple environments by changing the `environment` variable:

```bash
terraform apply -var="environment=staging"
terraform apply -var="environment=prod"
```

## 📊 Monitoring

Application Insights is automatically configured for monitoring:

1. View metrics in Azure Portal
2. Check Function App logs
3. Monitor API Gateway traffic
4. Track database performance

Access Application Insights:
```bash
cd terraform
terraform output application_insights_instrumentation_key
```

## 🔒 Security

- SQL credentials stored in Azure Key Vault
- Managed Identity for Function App to Key Vault access
- HTTPS enforced on all endpoints
- CORS configured for web app
- API Management for rate limiting and authentication

## 🛠️ Maintenance

### Updating Infrastructure

1. Modify Terraform files
2. Run `terraform plan` to preview changes
3. Run `terraform apply` to apply changes

### Updating Web App

```bash
STORAGE_ACCOUNT=$(cd terraform && terraform output -raw storage_account_name)
az storage blob upload-batch \
  --account-name $STORAGE_ACCOUNT \
  --source web-app \
  --destination '$web' \
  --overwrite
```

### Updating Functions

```bash
cd functions
FUNCTION_APP=$(cd ../terraform && terraform output -raw function_app_name)
func azure functionapp publish $FUNCTION_APP
```

## 🧪 Testing

### API Endpoints

The application exposes the following API endpoints:

- `POST /api/devices` - Register a device
- `GET /api/sensor-data?deviceIp={ip}` - Get sensor data
- `POST /api/sensor-data` - Save sensor data
- `POST /api/control` - Control device

### Example API Calls

```bash
# Register device
curl -X POST https://<api-gateway-url>/api/devices \
  -H "Content-Type: application/json" \
  -d '{"ip":"192.168.1.100","port":80,"type":"soil_sensor"}'

# Get sensor data
curl https://<api-gateway-url>/api/sensor-data?deviceIp=192.168.1.100
```

## 💰 Cost Estimation

Monthly costs (approximate, dev environment):

- Storage Account: ~$1
- Azure Functions (Consumption): Pay per execution (~$0-5)
- Azure SQL Database (Basic): ~$5
- API Management (Consumption): Pay per call (~$0-5)
- CDN: ~$0-2
- Application Insights: ~$0-2

**Total: ~$13-20/month** for development workload

## 🗑️ Cleanup

To destroy all resources:

```bash
cd terraform
terraform destroy
```

⚠️ **Warning**: This will permanently delete all resources and data!

## 📚 Documentation

- [Terraform Documentation](./terraform/README.md)
- [Functions Documentation](./functions/README.md)
- [Azure Functions Documentation](https://docs.microsoft.com/en-us/azure/azure-functions/)
- [Azure API Management Documentation](https://docs.microsoft.com/en-us/azure/api-management/)

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📝 License

This project is part of a university capstone project.

## 👥 Team

Soil Sensing Robot Team

## 📧 Support

For issues and questions, please open an issue on GitHub.
