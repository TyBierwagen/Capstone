# Terraform Infrastructure

This directory contains Infrastructure as Code (IaC) definitions for deploying the Soil Sensing Robot application to Microsoft Azure.

## Architecture

The infrastructure includes:

- **Resource Group**: Container for all Azure resources
- **Azure Storage Account**: Hosts the static website for the web application
- **Azure Functions**: Serverless backend for processing microcontroller data
- **Azure SQL Database**: Stores sensor data and configuration
- **Azure CDN**: Content Delivery Network for fast global access to the web app
- **Azure API Management**: API Gateway for routing and managing API calls
- **Azure Key Vault**: Secure storage for secrets and connection strings
- **Application Insights**: Monitoring and telemetry

## Prerequisites

1. [Terraform](https://www.terraform.io/downloads.html) >= 1.0
2. [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli)
3. Active Azure subscription
4. Optional (for DNS automation): [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) configured with credentials that can manage Route 53 hosted zones. If you prefer, you can add the DNS records manually in Route 53 instead of using Terraform.

## Setup

1. **Login to Azure**:
   ```bash
   az login
   ```

2. **Set your subscription** (if you have multiple):
   ```bash
   az account set --subscription "your-subscription-id"
   ```

3. **Create terraform.tfvars**:
   ```bash
   cp terraform.tfvars.example terraform.tfvars
   ```
   
4. **Edit terraform.tfvars** with your values:
   - Update `sql_admin_password` with a strong password
   - Update `publisher_email` with your email
   - Set `acs_sender_email` to the email address you want ACS to use for outgoing messages (default: `alerts@soilrobot.example.com`).
   - Adjust other values as needed

Note: Azure Communication Services requires that the `ACS_SENDER_EMAIL` be a verified sender identity. After deployment, go to your Communication Service in the Azure Portal → **Email** → **Sender identities** and verify the email (or domain). For domain verification, add the DNS TXT records ACS provides and wait for propagation.
If Terraform doesn't create the Communication Service (provider compatibility), create it manually via the Azure CLI or Portal and then set the connection string into Key Vault:

az communication service create --name <name> --resource-group <rg> --location <location>
# Get the connection string and store it in Key Vault
az communication credential create --name <name> --resource-group <rg> --kind primary
az keyvault secret set --vault-name <vault> --name "ACS-ConnectionString" --value "<connection-string>"
## Deployment

1. **Initialize Terraform**:
   ```bash
   terraform init
   ```

2. **Review the plan**:
   ```bash
   terraform plan
   ```

3. **Apply the configuration**:
   ```bash
   terraform apply
   ```
   
   Type `yes` when prompted to confirm.

4. **View outputs**:
   ```bash
   terraform output
   ```

## Outputs

After deployment, Terraform will output important information:

- `static_website_url`: URL where your web app is hosted
- `cdn_endpoint_url`: CDN URL for faster access
- `function_app_url`: Azure Functions endpoint
- `api_management_gateway_url`: API Gateway URL for accessing APIs

## Resource Naming Convention

Resources are named using the pattern: `{project_name}-{resource_type}-{environment}`

Example: `soilrobot-rg-dev` (resource group in dev environment)

## Security Notes

- SQL Server credentials are stored in Azure Key Vault
- Managed Identity is used for Function App to access Key Vault
- All secrets are marked as sensitive in Terraform outputs
- **Never commit terraform.tfvars or *.tfstate files to version control**

## Cleanup

To destroy all resources:

```bash
terraform destroy
```

Type `yes` when prompted to confirm.

## Cost Optimization

The configuration uses cost-effective tiers:

- Function App: Consumption (Y1) plan - pay per execution
- SQL Database: Basic tier
- API Management: Consumption tier
- Storage: Standard LRS
- CDN: Standard Microsoft

## Customization

To modify the infrastructure:

1. Edit the relevant `.tf` files
2. Run `terraform plan` to preview changes
3. Run `terraform apply` to apply changes

## Troubleshooting

If deployment fails:

1. Check your Azure permissions
2. Verify resource name availability (they must be globally unique)
3. Ensure your Azure subscription has sufficient quota
4. Check the Terraform error messages for specific issues

## Next Steps

After infrastructure is deployed:

1. Deploy the web application to the storage account
2. Deploy Azure Functions code
3. Configure API Management policies
4. Set up monitoring alerts in Application Insights
