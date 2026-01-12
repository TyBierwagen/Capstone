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
}

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

# App Service Plan for Azure Functions
resource "azurerm_service_plan" "main" {
  name                = "${var.project_name}-asp-${var.environment}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  os_type             = "Linux"
  sku_name            = "Y1"  # Consumption plan for serverless
  tags                = var.tags
}

# Azure Function App (Serverless Backend)
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
      node_version = "18"
    }
    cors {
      allowed_origins = ["*"]
    }
  }
  
  app_settings = {
    "FUNCTIONS_WORKER_RUNTIME"       = "node"
    "WEBSITE_NODE_DEFAULT_VERSION"   = "~18"
    "SQL_CONNECTION_STRING"          = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.sql_connection.id})"
    "APPLICATIONINSIGHTS_CONNECTION_STRING" = azurerm_application_insights.main.connection_string
  }
  
  tags = var.tags
}

# Azure SQL Server
resource "azurerm_mssql_server" "main" {
  name                         = "${var.project_name}-sql-${var.environment}"
  resource_group_name          = azurerm_resource_group.main.name
  location                     = azurerm_resource_group.main.location
  version                      = "12.0"
  administrator_login          = var.sql_admin_username
  administrator_login_password = var.sql_admin_password
  minimum_tls_version          = "1.2"
  
  tags = var.tags
}

# Azure SQL Database
resource "azurerm_mssql_database" "main" {
  name           = "${var.project_name}-db-${var.environment}"
  server_id      = azurerm_mssql_server.main.id
  collation      = "SQL_Latin1_General_CP1_CI_AS"
  license_type   = "LicenseIncluded"
  sku_name       = "Basic"
  max_size_gb    = 2
  zone_redundant = false
  
  tags = var.tags
}

# Firewall rule to allow Azure services to access SQL Server
resource "azurerm_mssql_firewall_rule" "allow_azure_services" {
  name             = "AllowAzureServices"
  server_id        = azurerm_mssql_server.main.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

# CDN Profile
resource "azurerm_cdn_profile" "main" {
  name                = "${var.project_name}-cdn-${var.environment}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Standard_Microsoft"
  tags                = var.tags
}

# CDN Endpoint for static website
resource "azurerm_cdn_endpoint" "main" {
  name                = "${var.project_name}-cdn-endpoint-${var.environment}"
  profile_name        = azurerm_cdn_profile.main.name
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  
  origin {
    name      = "staticwebsite"
    host_name = azurerm_storage_account.main.primary_web_host
  }
  
  origin_host_header = azurerm_storage_account.main.primary_web_host
  
  is_http_allowed  = true
  is_https_allowed = true
  
  tags = var.tags
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
  
  tags = var.tags
}

# Key Vault for secrets management
resource "azurerm_key_vault" "main" {
  name                       = "${var.project_name}-kv-${var.environment}"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  soft_delete_retention_days = 7
  purge_protection_enabled   = false
  
  access_policy {
    tenant_id = data.azurerm_client_config.current.tenant_id
    object_id = data.azurerm_client_config.current.object_id
    
    secret_permissions = [
      "Get", "List", "Set", "Delete", "Purge"
    ]
  }
  
  access_policy {
    tenant_id = data.azurerm_client_config.current.tenant_id
    object_id = azurerm_linux_function_app.main.identity[0].principal_id
    
    secret_permissions = [
      "Get", "List"
    ]
  }
  
  tags = var.tags
}

# Store SQL connection string in Key Vault
resource "azurerm_key_vault_secret" "sql_connection" {
  name         = "sql-connection-string"
  value        = "Server=tcp:${azurerm_mssql_server.main.fully_qualified_domain_name},1433;Initial Catalog=${azurerm_mssql_database.main.name};Persist Security Info=False;User ID=${var.sql_admin_username};Password=${var.sql_admin_password};MultipleActiveResultSets=False;Encrypt=True;TrustServerCertificate=False;Connection Timeout=30;"
  key_vault_id = azurerm_key_vault.main.id
  
  depends_on = [azurerm_key_vault.main]
}

# Data source for current Azure client config
data "azurerm_client_config" "current" {}
