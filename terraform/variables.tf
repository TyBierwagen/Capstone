variable "project_name" {
  description = "Name of the project, used for resource naming"
  type        = string
  default     = "soilrobot"
  
  validation {
    condition     = length(var.project_name) <= 10 && can(regex("^[a-z0-9]+$", var.project_name))
    error_message = "Project name must be lowercase alphanumeric and max 10 characters for resource naming constraints."
  }
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"
  
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be dev, staging, or prod."
  }
}

variable "location" {
  description = "Azure region for resources"
  type        = string
  default     = "westus2"
}

variable "sql_admin_username" {
  description = "Administrator username for SQL Server"
  type        = string
  default     = "sqladmin"
  sensitive   = true
}

variable "sql_admin_password" {
  description = "Administrator password for SQL Server"
  type        = string
  sensitive   = true
  
  validation {
    condition     = length(var.sql_admin_password) >= 8
    error_message = "SQL admin password must be at least 8 characters long."
  }
}

variable "publisher_name" {
  description = "Publisher name for API Management"
  type        = string
  default     = "Soil Robot Team"
}

variable "publisher_email" {
  description = "Publisher email for API Management"
  type        = string
  default     = "admin@soilrobot.local"
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default = {
    Project     = "Soil Sensing Robot"
    ManagedBy   = "Terraform"
    Environment = "Development"
  }
}

variable "allowed_origins" {
  description = "Static list of allowed CORS origins"
  type        = list(string)
  default     = ["https://portal.azure.com", "http://localhost:5500", "http://127.0.0.1:5500", "https://soil.tybierwagen.com"]
}

variable "acs_sender_email" {
  description = "Email address used as the verified sender for Azure Communication Services email (must be verified after deployment)"
  type        = string
  default     = "alerts@soilrobot.example.com"
  validation {
    # Use double-escaped backslashes so Terraform string parsing keeps the \s and \.
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.acs_sender_email))
    error_message = "acs_sender_email must be a valid email address"
  }
}

variable "aws_region" {
  description = "AWS region used for Route53 lookups (Routing is global for Route53, default used for API calls)"
  type        = string
  default     = "us-east-1"
}

variable "route53_zone_name" {
  description = "The hosted zone name in Route53 for your domain (example: tybierwagen.com)"
  type        = string
  default     = "tybierwagen.com"
}

variable "acs_verification_token" {
  description = "TXT value for ACS domain verification (include quotes). Example: \"ms-domain-verification=...\""
  type        = string
  default     = "\"ms-domain-verification=f4b70a3f-f035-4aa0-a258-0fbe7e5f3785\""
}

variable "acs_spf_value" {
  description = "SPF TXT value for ACS (include quotes)"
  type        = string
  default     = "\"v=spf1 include:spf.protection.outlook.com -all\""
}

variable "acs_connection_string" {
  description = "Azure Communication Services connection string (sensitive). If provided, Terraform will place it in Key Vault secret and wire it to Function App settings."
  type        = string
  sensitive   = true
  default     = ""
}  
