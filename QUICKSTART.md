# Quick Start Guide

## Overview
This guide will help you quickly deploy the Soil Sensing Robot infrastructure to Azure.

## Prerequisites Checklist
- [ ] Azure account with active subscription
- [ ] Azure CLI installed and configured
- [ ] Terraform installed (>= 1.0)
- [ ] Node.js installed (>= 18)
- [ ] ESP32/ESP8266 microcontroller with sensors
- [ ] Git installed

## Step-by-Step Deployment

### 1. Clone Repository
```bash
git clone https://github.com/TyBierwagen/Capstone.git
cd Capstone
```

### 2. Authenticate with Azure
```bash
az login
az account set --subscription "your-subscription-id"
```

### 3. Configure Terraform
```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` and set:
- `sql_admin_password`: Strong password (min 8 characters)
- `publisher_email`: Your email address
- Other variables as needed

### 4. Deploy Infrastructure
```bash
terraform init
terraform plan
terraform apply
```

**Time estimate**: 10-15 minutes

### 5. Note Important Outputs
After deployment, save these values:
```bash
terraform output static_website_url
terraform output cdn_endpoint_url
terraform output api_management_gateway_url
```

### 6. Deploy Web Application
```bash
cd ..
STORAGE_ACCOUNT=$(cd terraform && terraform output -raw storage_account_name)
az storage blob upload-batch \
    --account-name $STORAGE_ACCOUNT \
    --source web-app \
    --destination '$web' \
    --overwrite
```

### 7. Deploy Azure Functions
```bash
cd functions
npm install
FUNCTION_APP=$(cd ../terraform && terraform output -raw function_app_name)
func azure functionapp publish $FUNCTION_APP
```

### 8. Configure Microcontroller

#### A. Hardware Setup
1. Connect sensors to ESP32:
   - Moisture sensor → GPIO34
   - Temperature sensor → GPIO35
   - pH sensor → GPIO36
   - Light sensor → GPIO39
   - VCC → 3.3V
   - GND → GND

#### B. Software Setup
1. Open `microcontroller/soil_sensor.ino` in Arduino IDE
2. Update WiFi credentials:
   ```cpp
   const char* ssid = "YOUR_WIFI_SSID";
   const char* password = "YOUR_WIFI_PASSWORD";
   ```
3. Update API endpoint:
   ```cpp
   const char* apiEndpoint = "YOUR_API_GATEWAY_URL/api";
   ```
4. Select board: ESP32 Dev Module
5. Select port
6. Upload code

### 9. Test the System

#### A. Access Web Interface
1. Open the CDN URL in browser
2. You should see the control panel

#### B. Connect to Microcontroller
1. Find microcontroller IP in Serial Monitor
2. Enter IP address in web interface
3. Click "Connect"
4. Click "Start Sampling"

#### C. Verify Data Flow
1. Check sensor readings update in web interface
2. View activity log for status
3. Check Azure Portal → Application Insights for telemetry

## Automated Deployment (Alternative)

Use the deployment script for one-command deployment:

### Linux/Mac
```bash
chmod +x deploy.sh
./deploy.sh
```

### Windows
```cmd
deploy.bat
```

## Architecture Summary

```
Microcontroller (WiFi) ←→ Web App (CDN) → API Gateway → Functions → Database
                                                            ↓
                                                      Key Vault
                                                            ↓
                                                  App Insights
```

## Troubleshooting

### Terraform Deployment Fails
- **Resource name taken**: Change `project_name` variable
- **Insufficient permissions**: Verify Azure role assignments
- **Quota exceeded**: Request quota increase or choose different region

### Web App Not Loading
- Wait 5-10 minutes for CDN propagation
- Try static website URL instead of CDN URL
- Check browser console for errors

### Microcontroller Can't Connect
- Verify WiFi credentials
- Check WiFi is 2.4GHz network
- Ensure API endpoint URL is correct
- Check Serial Monitor for error messages

### No Data in Web Interface
- Verify microcontroller is connected (green indicator)
- Check microcontroller Serial Monitor for data being sent
- Check Azure Functions logs in portal
- Verify CORS settings in Functions

## Verification Checklist

After deployment, verify:
- [ ] Can access web interface via CDN URL
- [ ] Web interface loads without errors
- [ ] Microcontroller connects to WiFi successfully
- [ ] Microcontroller shows IP address in Serial Monitor
- [ ] Can connect to microcontroller from web interface
- [ ] Sensor data displays in web interface
- [ ] Activity log shows successful operations
- [ ] Data saves to database (check Azure SQL)
- [ ] Application Insights shows telemetry

## Cost Management

Expected costs for development:
- **Daily**: $0.50 - $1.00
- **Monthly**: $13 - $20

To minimize costs:
- Stop/deallocate resources when not in use
- Use `terraform destroy` to remove all resources
- Monitor costs in Azure Portal

## Next Steps

1. **Customize Web Interface**: Edit `web-app/index.html` and `web-app/app.js`
2. **Add Database Logic**: Implement SQL queries in Functions
3. **Add Authentication**: Configure Azure AD or OAuth
4. **Set Up Alerts**: Create alerts in Application Insights
5. **Scale for Production**: Upgrade tiers as needed

## Getting Help

- **Documentation**: See `README.md` and `ARCHITECTURE.md`
- **Terraform Issues**: Check `terraform/README.md`
- **Function Issues**: Check `functions/README.md`
- **Hardware Issues**: Check `microcontroller/README.md`
- **Azure Support**: Visit Azure Portal support

## Useful Commands

```bash
# View all Terraform outputs
cd terraform && terraform output

# Check Function App logs
func azure functionapp logstream $FUNCTION_APP

# List storage account files
az storage blob list --account-name $STORAGE_ACCOUNT --container '$web'

# Check Function App status
az functionapp show --name $FUNCTION_APP --resource-group $RESOURCE_GROUP

# Open Azure Portal
az portal open
```

## Clean Up

To remove all resources:
```bash
cd terraform
terraform destroy
```

Confirm with `yes` when prompted.

---

**Need Help?** Open an issue on GitHub or check the documentation.
