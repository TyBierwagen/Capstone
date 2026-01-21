# AWS Route53 records to verify domain for Azure Communication Services
# This file creates the DNS records required for ACS email domain verification (DKIM, domain TXT, SPF).
# NOTE: Configure AWS credentials for Terraform (env vars or shared config) before applying.

provider "aws" {
  region = var.aws_region
}

# Lookup the hosted zone by name
data "aws_route53_zone" "zone" {
  name         = var.route53_zone_name
  private_zone = false
}

resource "aws_route53_record" "dkim1" {
  zone_id = data.aws_route53_zone.zone.zone_id
  name    = "selector1-azurecomm-prod-net._domainkey.${var.route53_zone_name}"
  type    = "CNAME"
  ttl     = 3600
  records = ["selector1-azurecomm-prod-net._domainkey.azurecomm.net"]
}

resource "aws_route53_record" "dkim2" {
  zone_id = data.aws_route53_zone.zone.zone_id
  name    = "selector2-azurecomm-prod-net._domainkey.${var.route53_zone_name}"
  type    = "CNAME"
  ttl     = 3600
  records = ["selector2-azurecomm-prod-net._domainkey.azurecomm.net"]
}

# Single TXT record that includes both SPF and the ACS domain verification token.
# Route53 represents multiple TXT values as multiple entries on the same record.
resource "aws_route53_record" "acs_txt" {
  zone_id = data.aws_route53_zone.zone.zone_id
  name    = var.route53_zone_name
  type    = "TXT"
  ttl     = 3600
  records = [var.acs_spf_value, var.acs_verification_token]
}

output "route53_zone_id" {
  value = data.aws_route53_zone.zone.zone_id
} 
