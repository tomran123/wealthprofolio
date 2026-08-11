variable "region" {
  description = "Alibaba Cloud region shared by all resources."
  type        = string
  default     = "cn-hangzhou"
}

variable "project_name" {
  description = "Short lowercase deployment name."
  type        = string
  default     = "wealthprofolio"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,24}$", var.project_name))
    error_message = "project_name must start with a lowercase letter and contain only lowercase letters, digits, and dashes."
  }
}

variable "namespace_slug" {
  description = "SAE namespace suffix. The full ID is <region>:<namespace_slug>."
  type        = string
  default     = "wealthprofolio-prod"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,30}$", var.namespace_slug))
    error_message = "namespace_slug must contain only lowercase letters, digits, and dashes."
  }
}

variable "vpc_id" {
  description = "Existing VPC ID. Create and review it in the Alibaba Cloud account first."
  type        = string
  default     = ""
}

variable "vswitch_id" {
  description = "Existing vSwitch ID in vpc_id."
  type        = string
  default     = ""
}

variable "security_group_id" {
  description = "Existing least-privilege security group ID in vpc_id."
  type        = string
  default     = ""
}

variable "migration_database_role" {
  description = "Dedicated RDS LOGIN role that owns the schema and runs Alembic Jobs."
  type        = string
  default     = "wp_migration_owner"

  validation {
    condition     = can(regex("^[a-z_][a-z0-9_]{2,62}$", var.migration_database_role))
    error_message = "migration_database_role must be a valid unquoted PostgreSQL role name."
  }
}

variable "runtime_database_role" {
  description = "Dedicated least-privilege RDS LOGIN role used by API and workers."
  type        = string
  default     = "wp_runtime"

  validation {
    condition     = can(regex("^[a-z_][a-z0-9_]{2,62}$", var.runtime_database_role))
    error_message = "runtime_database_role must be a valid unquoted PostgreSQL role name."
  }
}

variable "enable_runtime" {
  description = "Create the API and Celery worker. Keep false until the migration Job succeeds."
  type        = bool
  default     = false
}

variable "enable_frontend" {
  description = "Create the Next.js application. Build it only after BACKEND_INTERNAL_URL is known."
  type        = bool
  default     = false
}

variable "backend_image_url" {
  description = "Immutable ACR VPC image URL for FastAPI and Celery."
  type        = string
  default     = ""
}

variable "frontend_image_url" {
  description = "Immutable ACR VPC image URL for Next.js."
  type        = string
  default     = ""
}

variable "backend_internal_url" {
  description = "URL baked into the frontend image and also exposed as a runtime diagnostic value."
  type        = string
  default     = ""
}

variable "sae_secret_name" {
  description = "Name of an existing SAE Secret containing all sensitive runtime variables."
  type        = string
  default     = ""
}

variable "sae_secret_id" {
  description = "Numeric ID of sae_secret_name. No secret values are stored in Terraform state."
  type        = number
  default     = 0
}

variable "cors_origins" {
  description = "Exact HTTPS browser origins allowed by the API."
  type        = list(string)
  default     = []
}

variable "default_base_currency" {
  type    = string
  default = "USD"
}

variable "kms_key_id" {
  description = "Existing KMS key used for application envelope encryption and OSS SSE-KMS."
  type        = string
  default     = ""
}

variable "kms_endpoint" {
  description = "Optional KMS endpoint. Leave empty to use the regional endpoint."
  type        = string
  default     = ""
}

variable "oss_endpoint" {
  description = "Private OSS endpoint, for example oss-cn-hangzhou-internal.aliyuncs.com."
  type        = string
  default     = ""
}

variable "oss_public_endpoint" {
  description = "Public HTTPS OSS endpoint used only to sign browser upload/preview URLs."
  type        = string
  default     = ""
}

variable "oss_bucket" {
  description = "Existing private, versioned OSS bucket with default SSE-KMS."
  type        = string
  default     = ""
}

variable "document_ocr_provider" {
  description = "Use tesseract until the FC OCR adapter image and caller are enabled."
  type        = string
  default     = "tesseract"

  validation {
    condition     = contains(["tesseract", "alibaba_ocr"], var.document_ocr_provider)
    error_message = "document_ocr_provider must be tesseract or alibaba_ocr."
  }
}

variable "api_replicas" {
  type    = number
  default = 2
}

variable "worker_replicas" {
  type    = number
  default = 1
}

variable "celery_concurrency" {
  type    = number
  default = 2
}

variable "sae_sls_configs" {
  description = "SAE SLS JSON. Prefer an existing project/logstore in production."
  type        = string
  default     = "[{\"logDir\":\"\",\"logType\":\"stdout\"}]"
}

variable "api_intranet_slb_id" {
  description = "Optional existing intranet CLB ID for the API."
  type        = string
  default     = ""
}

variable "external_clamav_host" {
  description = "Existing VPC-reachable clamd hostname/IP when not deploying ClamAV on SAE."
  type        = string
  default     = ""
}

variable "enable_clamav_sae" {
  description = "Deploy a mirrored, pinned ClamAV image to SAE."
  type        = bool
  default     = false
}

variable "clamav_image_url" {
  description = "Pinned ACR VPC image URL mirroring the approved ClamAV image."
  type        = string
  default     = ""
}

variable "clamav_intranet_slb_id" {
  description = "Existing intranet CLB used only for clamd TCP/3310."
  type        = string
  default     = ""
}

variable "enable_fc_ocr" {
  description = "Create the FC v3 async OCR function after its image contract is integrated."
  type        = bool
  default     = false
}

variable "fc_ocr_image_url" {
  description = "Pinned ACR image implementing the Function Compute custom-container contract."
  type        = string
  default     = ""
}

variable "fc_ocr_role_arn" {
  description = "Existing least-privilege FC execution RAM role ARN."
  type        = string
  default     = ""
}

variable "fc_ocr_function_name" {
  type    = string
  default = "wealthprofolio-ocr"
}

variable "fc_ocr_memory_mb" {
  type    = number
  default = 2048
}

variable "fc_ocr_cpu" {
  type    = number
  default = 1
}

variable "fc_sls_project" {
  type    = string
  default = ""
}

variable "fc_sls_logstore" {
  type    = string
  default = ""
}
