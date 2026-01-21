output "resource_group_name" {
  description = "Name of the resource group"
  value       = azurerm_resource_group.main.name
}

output "storage_account_name" {
  description = "Name of the storage account"
  value       = azurerm_storage_account.main.name
}

output "static_website_url" {
  description = "URL of the static website"
  value       = azurerm_storage_account.main.primary_web_endpoint
}

output "cdn_endpoint_url" {
  description = "CDN endpoint URL for the static website"
  value       = azurerm_storage_account.main.primary_web_endpoint
}

output "function_app_name" {
  description = "Name of the Azure Function App"
  value       = azurerm_linux_function_app.main.name
}

output "function_app_url" {
  description = "URL of the Azure Function App"
  value       = "https://${azurerm_linux_function_app.main.default_hostname}"
}

output "api_management_gateway_url" {
  description = "Gateway URL of the API Management service"
  value       = azurerm_api_management.main.gateway_url
}

output "api_management_name" {
  description = "Name of the API Management service"
  value       = azurerm_api_management.main.name
}

output "application_insights_instrumentation_key" {
  description = "Instrumentation key for Application Insights"
  value       = azurerm_application_insights.main.instrumentation_key
  sensitive   = true
}

output "key_vault_uri" {
  description = "URI of the Key Vault"
  value       = azurerm_key_vault.main.vault_uri
}

output "static_web_app_url" {
  value = azurerm_static_web_app.main.default_host_name
}

# Convenience outputs for testing the email endpoint via API Management
output "api_test_email_get_url" {
  description = "GET endpoint to trigger test email via APIM (query params: to, from, deviceId, subject)"
  value       = "${azurerm_api_management.main.gateway_url}/api/test-email"
}

output "api_test_email_post_url" {
  description = "POST endpoint to trigger test email via APIM (JSON body: {to, from, deviceId, subject})"
  value       = "${azurerm_api_management.main.gateway_url}/api/test-email"
}