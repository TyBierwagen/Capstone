#!/bin/bash

# Deploy Azure Functions code only (zip + config-zip upload).
# Usage:
#   ./deploy-functions.sh [function_app_name] [resource_group]

set -e

cd "$(dirname "$0")"

FUNCTION_APP="${1:-}"
RESOURCE_GROUP="${2:-}"
ZIP_PATH="/tmp/capstone-functions-$$.zip"

echo "Starting Functions-only deployment..."

if ! command -v az >/dev/null 2>&1; then
  echo "ERROR: Azure CLI not found."
  exit 1
fi

if ! az account show >/dev/null 2>&1; then
  echo "Not logged in to Azure. Logging in..."
  az login
fi

if [ -z "$FUNCTION_APP" ] && [ -f "terraform/terraform.tfstate" ]; then
  FUNCTION_APP="$(cd terraform && terraform output -raw function_app_name 2>/dev/null || true)"
fi

if [ -z "$RESOURCE_GROUP" ] && [ -f "terraform/terraform.tfstate" ]; then
  RESOURCE_GROUP="$(cd terraform && terraform output -raw resource_group_name 2>/dev/null || true)"
fi

if [ -z "$FUNCTION_APP" ] || [ -z "$RESOURCE_GROUP" ]; then
  echo "ERROR: Missing function app or resource group."
  echo "Usage: ./deploy-functions.sh <function_app_name> <resource_group>"
  exit 1
fi

echo "Function App : $FUNCTION_APP"
echo "Resource Group: $RESOURCE_GROUP"

echo "Enabling remote build settings for Python dependencies..."
az functionapp config appsettings set \
  --name "$FUNCTION_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --settings SCM_DO_BUILD_DURING_DEPLOYMENT=true ENABLE_ORYX_BUILD=true >/dev/null

echo "Creating deployment zip from functions/..."
rm -f "$ZIP_PATH"
(
  cd functions
  zip -r "$ZIP_PATH" . >/dev/null
)

echo "Uploading zip package to Azure Functions..."
az functionapp deployment source config-zip \
  --name "$FUNCTION_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --src "$ZIP_PATH"

echo "Restarting Function App..."
az functionapp restart --name "$FUNCTION_APP" --resource-group "$RESOURCE_GROUP" >/dev/null || true

echo "Waiting for app to warm up..."
sleep 12

rm -f "$ZIP_PATH"

echo
echo "Functions-only deployment complete."
