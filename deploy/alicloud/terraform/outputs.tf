output "sae_namespace_id" {
  value       = alicloud_sae_namespace.production.id
  description = "Use this ID when creating SAE Secrets and the migration Job."
}

output "database_role_contract" {
  value = {
    migration = var.migration_database_role
    runtime   = var.runtime_database_role
  }
  description = "Role names expected in the migration and runtime SAE DATABASE_URL secrets."
}

output "api_application_id" {
  value       = try(alicloud_sae_application.api[0].id, null)
  description = "SAE API application ID."
}

output "api_intranet_ip" {
  value       = try(alicloud_sae_load_balancer_intranet.api[0].intranet_ip, null)
  description = "Private API endpoint IP when an intranet CLB is attached."
}

output "worker_application_id" {
  value       = try(alicloud_sae_application.worker[0].id, null)
  description = "SAE Celery worker application ID."
}

output "frontend_application_id" {
  value       = try(alicloud_sae_application.frontend[0].id, null)
  description = "SAE frontend application ID."
}

output "fc_ocr_function_arn" {
  value       = try(alicloud_fcv3_function.ocr[0].function_arn, null)
  description = "FC v3 OCR function ARN when enabled."
}
