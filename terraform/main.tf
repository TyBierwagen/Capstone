terraform {
  required_version = ">= 1.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
}

provider "azurerm" {
  features {
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
 }
  skip_provider_registration = true
}

data "azurerm_client_config" "current" {}


# Resource Group
resource "azurerm_resource_group" "main" {
  name     = "${var.project_name}-rg-${var.environment}"
  location = var.location
  tags     = var.tags
}

# Storage Account for web app static files and function app
resource "azurerm_storage_account" "main" {
  name                     = "${var.project_name}st${var.environment}"
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  
  static_website {
    index_document = "index.html"
  }
  
  tags = var.tags
}

# Storage Container for function app
resource "azurerm_storage_container" "functions" {
  name                  = "function-releases"
  storage_account_name  = azurerm_storage_account.main.name
  container_access_type = "private"
}

# Storage Table for Sensor Data
resource "azurerm_storage_table" "sensor_data" {
  name                 = "SensorData"
  storage_account_name = azurerm_storage_account.main.name
}

# Storage Table for Devices
resource "azurerm_storage_table" "devices" {
  name                 = "Devices"
  storage_account_name = azurerm_storage_account.main.name
}

# App Service Plan for Azure Functions
resource "azurerm_service_plan" "main" {
  name                = "${var.project_name}-asp-${var.environment}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  os_type             = "Linux"
  sku_name            = "Y1"  # Consumption plan for serverless
  tags                = var.tags
}

# API Management Service (API Gateway)
resource "azurerm_api_management" "main" {
  name                = "${var.project_name}-apim-${var.environment}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  publisher_name      = var.publisher_name
  publisher_email     = var.publisher_email
  sku_name            = "Consumption_0"
  
  tags = var.tags
}

# API Management API
resource "azurerm_api_management_api" "main" {
  name                = "microcontroller-api"
  resource_group_name = azurerm_resource_group.main.name
  api_management_name = azurerm_api_management.main.name
  revision            = "1"
  display_name        = "Microcontroller API"
  path                = "api"
  protocols           = ["https"]
  
  subscription_required = false
}

# API Management Backend for Azure Functions
resource "azurerm_api_management_backend" "functions" {
  name                = "functions-backend"
  resource_group_name = azurerm_resource_group.main.name
  api_management_name = azurerm_api_management.main.name
  protocol            = "http"
  url                 = "https://${azurerm_linux_function_app.main.default_hostname}"
}

# Application Insights for monitoring
resource "azurerm_application_insights" "main" {
  name                = "${var.project_name}-appinsights-${var.environment}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  application_type    = "web"
  #workspace_id        = "/subscriptions/c266ae67-f775-42f4-a754-ec0b46ac7811/resourceGroups/DefaultResourceGroup-WUS/providers/Microsoft.OperationalInsights/workspaces/DefaultWorkspace-c266ae67-f775-42f4-a754-ec0b46ac7811-WUS"
  tags = var.tags
}

# Key Vault for secrets management
resource "azurerm_key_vault" "main" {
  name                       = "${var.project_name}-kv-${var.environment}"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
}

resource "azurerm_key_vault_access_policy" "terraform_user" {
  key_vault_id = azurerm_key_vault.main.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = data.azurerm_client_config.current.object_id

  secret_permissions = [
    "Get",
    "List",
    "Set",
    "Delete",
    "Recover",
    "Backup",
    "Restore",
    "Purge"
  ]
}

resource "azurerm_key_vault_access_policy" "function_app" {
  key_vault_id = azurerm_key_vault.main.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = azurerm_linux_function_app.main.identity[0].principal_id

  secret_permissions = [
    "Get",
    "List"
  ]
}


resource "azurerm_linux_function_app" "main" {
  name                       = "${var.project_name}-func-${var.environment}"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  service_plan_id            = azurerm_service_plan.main.id
  storage_account_name       = azurerm_storage_account.main.name
  storage_account_access_key = azurerm_storage_account.main.primary_access_key

  identity {
    type = "SystemAssigned"
  }

  site_config {
    application_stack {
      python_version = "3.11"
    }
  }

  app_settings = {
    FUNCTIONS_WORKER_RUNTIME = "python"
    WEBSITE_RUN_FROM_PACKAGE = "1"
    # Don't reference Key Vault secret here initially - causes cycle
  }
  
  lifecycle {
    ignore_changes = [
      app_settings["SQL_CONNECTION_STRING"]
    ]
  }
  
  tags = var.tags
}

resource "azurerm_static_web_app" "main" {
  name                = "${var.project_name}-swa-${var.environment}"
  resource_group_name = azurerm_resource_group.main.name
  location            = "eastus2"
  sku_tier            = "Free"
  sku_size            = "Free"
}