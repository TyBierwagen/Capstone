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

resource "azurerm_api_management_api_policy" "main" {
  api_name            = azurerm_api_management_api.main.name
  api_management_name = azurerm_api_management.main.name
  resource_group_name = azurerm_resource_group.main.name

  xml_content = <<XML
<policies>
    <inbound>
        <cors>
            <allowed-origins>
                <origin>http://localhost:5500</origin>
                <origin>http://127.0.0.1:5500</origin>
                <origin>https://soil.tybierwagen.com</origin>
            </allowed-origins>
            <allowed-methods>
                <method>GET</method>
                <method>POST</method>
                <method>OPTIONS</method>
                <method>PUT</method>
                <method>DELETE</method>
            </allowed-methods>
            <allowed-headers>
                <header>*</header>
            </allowed-headers>
            <expose-headers>
                <header>*</header>
            </expose-headers>
        </cors>
        <base />
        <set-backend-service base-url="https://${azurerm_linux_function_app.main.default_hostname}/api" />
    </inbound>
    <backend>
        <base />
    </backend>
    <outbound>
        <base />
    </outbound>
    <on-error>
        <base />
    </on-error>
</policies>
XML
}

# API Management Operations
resource "azurerm_api_management_api_operation" "get_sensor_data" {
  operation_id        = "get-sensor-data"
  api_name            = azurerm_api_management_api.main.name
  api_management_name = azurerm_api_management.main.name
  resource_group_name = azurerm_api_management_api.main.resource_group_name
  display_name        = "Get Sensor Data"
  method              = "GET"
  url_template        = "/sensor-data"
  description         = "Retrieve sensor readings"
}

resource "azurerm_api_management_api_operation" "post_sensor_data" {
  operation_id        = "post-sensor-data"
  api_name            = azurerm_api_management_api.main.name
  api_management_name = azurerm_api_management.main.name
  resource_group_name = azurerm_api_management_api.main.resource_group_name
  display_name        = "Post Sensor Data"
  method              = "POST"
  url_template        = "/sensor-data"
  description         = "Submit new sensor readings"
}

resource "azurerm_api_management_api_operation" "get_control" {
  operation_id        = "get-control"
  api_name            = azurerm_api_management_api.main.name
  api_management_name = azurerm_api_management.main.name
  resource_group_name = azurerm_api_management_api.main.resource_group_name
  display_name        = "Get Control Commands"
  method              = "GET"
  url_template        = "/control"
}

resource "azurerm_api_management_api_operation" "post_control" {
  operation_id        = "post-control"
  api_name            = azurerm_api_management_api.main.name
  api_management_name = azurerm_api_management.main.name
  resource_group_name = azurerm_api_management_api.main.resource_group_name
  display_name        = "Send Control Command"
  method              = "POST"
  url_template        = "/control"
}

resource "azurerm_api_management_api_operation" "health" {
  operation_id        = "health-check"
  api_name            = azurerm_api_management_api.main.name
  api_management_name = azurerm_api_management.main.name
  resource_group_name = azurerm_api_management_api.main.resource_group_name
  display_name        = "Health Check"
  method              = "GET"
  url_template        = "/health"
}

# API Management Backend for Azure Functions
resource "azurerm_api_management_backend" "functions" {
  name                = "functions-backend"
  resource_group_name = azurerm_resource_group.main.name
  api_management_name = azurerm_api_management.main.name
  protocol            = "http"
  url                 = "https://${azurerm_linux_function_app.main.default_hostname}/api"
}

# Log Analytics Workspace for Application Insights
resource "azurerm_log_analytics_workspace" "main" {
  name                = "${var.project_name}-law-${var.environment}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = var.tags
}

# Application Insights for monitoring
resource "azurerm_application_insights" "main" {
  name                = "${var.project_name}-appinsights-${var.environment}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  workspace_id        = azurerm_log_analytics_workspace.main.id
  application_type    = "web"
  
  lifecycle {
    ignore_changes = [
      # Ignore daily_data_cap_in_gb as it can be modified by Azure policies
      daily_data_cap_in_gb,
    ]
  }

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

# Azure Communication Services - Email
# NOTE: Some versions of the AzureRM provider may not support creating
# `azurerm_communication_service` directly. To avoid provider compatibility
# issues during Terraform runs, the Communication Service is not created
# automatically by Terraform in this configuration.
#
# Please create an Azure Communication Service (Email) in the portal or via
# `az communication` CLI, then store its connection string manually in
# the Key Vault secret below (name: "ACS-ConnectionString").

# Placeholder Key Vault secret for ACS connection string. After you create
# the Communication Service, set this secret using the Azure CLI:
# az keyvault secret set --vault-name <vault> --name "ACS-ConnectionString" --value "<connection-string>"
resource "azurerm_key_vault_secret" "acs_connection" {
  name         = "ACS-ConnectionString"
  value        = var.acs_connection_string
  key_vault_id = azurerm_key_vault.main.id

  lifecycle {
    ignore_changes = [ value ]
  }
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
    cors {
      allowed_origins     = ["*"]
      support_credentials = false
    }
  }

  app_settings = {
    FUNCTIONS_WORKER_RUNTIME       = "python"
    FUNCTIONS_EXTENSION_VERSION    = "~4"
    WEBSITE_RUN_FROM_PACKAGE       = "1"
    AzureWebJobsStorage            = azurerm_storage_account.main.primary_connection_string
    STORAGE_CONNECTION_STRING      = azurerm_storage_account.main.primary_connection_string
    WEBSITE_CONTENTAZUREFILECONNECTIONSTRING = azurerm_storage_account.main.primary_connection_string
    WEBSITE_CONTENTSHARE                     = "${var.project_name}-func-share"
    APPINSIGHTS_INSTRUMENTATIONKEY = azurerm_application_insights.main.instrumentation_key
    APPLICATIONINSIGHTS_CONNECTION_STRING = azurerm_application_insights.main.connection_string
    ENABLE_ORYX_BUILD              = "true"
    SCM_DO_BUILD_DURING_DEPLOYMENT = "true"
    # Azure Communication Services connection string is stored in Key Vault for security
    # It is populated from the Key Vault secret if provided.
    ACS_CONNECTION_STRING = azurerm_key_vault_secret.acs_connection.value
    # Verified sender email for ACS (set this to a verified address after deploy if using email)
    ACS_SENDER_EMAIL = var.acs_sender_email
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