#!/bin/bash

# Deploy script for Soil Sensing Robot infrastructure and application
# This script deploys the complete solution to Azure

set -e

echo "🚀 Starting deployment of Soil Sensing Robot..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check prerequisites
echo "📋 Checking prerequisites..."

if ! command -v az &> /dev/null; then
    echo -e "${RED}❌ Azure CLI not found. Please install it first.${NC}"
    exit 1
fi

if ! command -v terraform &> /dev/null; then
    echo -e "${RED}❌ Terraform not found. Please install it first.${NC}"
    exit 1
fi

if ! command -v node &> /dev/null; then
    echo -e "${RED}❌ Node.js not found. Please install it first.${NC}"
    exit 1
fi

echo -e "${GREEN}✅ All prerequisites found${NC}"

# Check Azure login
echo "🔐 Checking Azure login status..."
if ! az account show &> /dev/null; then
    echo -e "${YELLOW}⚠️  Not logged in to Azure. Logging in...${NC}"
    az login
fi

echo -e "${GREEN}✅ Logged in to Azure${NC}"

# Navigate to terraform directory
cd terraform

# Check if terraform.tfvars exists
if [ ! -f "terraform.tfvars" ]; then
    echo -e "${YELLOW}⚠️  terraform.tfvars not found. Creating from example...${NC}"
    cp terraform.tfvars.example terraform.tfvars
    echo -e "${RED}❌ Please edit terraform.tfvars with your values and run this script again.${NC}"
    exit 1
fi

# Initialize Terraform
echo "🔧 Initializing Terraform..."
terraform init

# Validate configuration
echo "✅ Validating Terraform configuration..."
terraform validate

# Plan deployment
echo "📝 Planning infrastructure deployment..."
terraform plan -out=tfplan

# Confirm deployment
read -p "Do you want to deploy this infrastructure? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "Deployment cancelled."
    exit 0
fi

# Apply Terraform
echo "🚀 Deploying infrastructure (this may take 10-15 minutes)..."
terraform apply tfplan

# Get outputs
echo "📊 Getting deployment outputs..."
FUNCTION_APP=$(terraform output -raw function_app_name)
STATIC_WEB_APP=$(terraform output -raw static_web_app_name)
CDN_URL=$(terraform output -raw cdn_endpoint_url)
STATIC_URL=$(terraform output -raw static_website_url)

cd ..

# Deploy Web Application
echo "🌐 Deploying web application to Static Web App..."
az staticwebapp upload \
    --name "$STATIC_WEB_APP" \
    --resource-group "$(terraform output -raw resource_group_name)" \
    --source ../web-app

echo -e "${GREEN}✅ Web application deployed to Static Web App${NC}"

# Deploy Azure Functions
echo "⚡ Deploying Azure Functions..."
cd functions
pip install -r requirements.txt --quiet
func azure functionapp publish "$FUNCTION_APP" --python

cd ..

echo ""
echo -e "${GREEN}🎉 Deployment complete!${NC}"
echo ""
echo "📍 Your application is available at:"
echo "   Static Website: $STATIC_URL"
echo "   CDN URL: $CDN_URL"
echo ""
echo "📚 Next steps:"
echo "   1. Open the CDN URL in your browser"
echo "   2. Configure your microcontroller to connect to WiFi"
echo "   3. Enter the microcontroller IP address in the web interface"
echo "   4. Monitor sensor data in real-time"
echo ""
echo "📊 To view monitoring data:"
echo "   az portal open"
echo "   Navigate to Application Insights"
echo ""
