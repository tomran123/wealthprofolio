locals {
  namespace_id = "${var.region}:${var.namespace_slug}"

  sae_secret_reference = [
    {
      name = "sae-sys-secret-all-${var.sae_secret_name}"
      valueFrom = {
        secretRef = {
          secretId = var.sae_secret_id
          key      = ""
        }
      }
    }
  ]

  clamav_host = var.enable_runtime && var.enable_clamav_sae ? alicloud_sae_load_balancer_intranet.clamav[0].intranet_ip : var.external_clamav_host

  backend_environment = [
    for name, value in {
      ENVIRONMENT                      = "production"
      CORS_ORIGINS                     = jsonencode(var.cors_origins)
      DEFAULT_BASE_CURRENCY            = var.default_base_currency
      AGENT_TIMEZONE                   = "Asia/Shanghai"
      AGENT_JOB_BACKEND                = "celery"
      AGENT_INLINE_FALLBACK            = "false"
      PRICE_JOB_BACKEND                = "celery"
      PRICE_INLINE_FALLBACK            = "false"
      ENCRYPTION_PROVIDER              = "alicloud"
      ALICLOUD_REGION_ID               = var.region
      ALICLOUD_KMS_KEY_ID              = var.kms_key_id
      ALICLOUD_KMS_ENDPOINT            = var.kms_endpoint
      DOCUMENT_JOB_BACKEND             = "celery"
      DOCUMENT_INLINE_FALLBACK         = "false"
      DOCUMENT_STORAGE_BACKEND         = "oss"
      DOCUMENT_STORAGE_ENDPOINT        = var.oss_endpoint
      DOCUMENT_STORAGE_PUBLIC_ENDPOINT = var.oss_public_endpoint
      DOCUMENT_STORAGE_BUCKET          = var.oss_bucket
      DOCUMENT_STORAGE_REGION          = var.region
      DOCUMENT_STORAGE_SECURE          = "true"
      DOCUMENT_STORAGE_KMS_KEY_ID      = var.kms_key_id
      DOCUMENT_OCR_PROVIDER            = var.document_ocr_provider
      DOCUMENT_CLAMAV_HOST             = local.clamav_host
      DOCUMENT_CLAMAV_PORT             = "3310"
      DOCUMENT_CLAMAV_REQUIRED         = "true"
      DOCUMENT_TESSERACT_LANGUAGES     = "eng+chi_sim"
      } : {
      name  = name
      value = tostring(value)
    }
  ]
}

check "database_role_separation" {
  assert {
    condition     = var.migration_database_role != var.runtime_database_role
    error_message = "Alembic migration owner and API/worker runtime roles must be different."
  }
}

resource "alicloud_sae_namespace" "production" {
  namespace_id              = local.namespace_id
  namespace_name            = var.namespace_slug
  namespace_description     = "WealthProfolio production"
  enable_micro_registration = false
}

resource "alicloud_sae_application" "clamav" {
  count = var.enable_runtime && var.enable_clamav_sae ? 1 : 0

  app_name             = "${var.project_name}-clamav"
  app_description      = "Private ClamAV daemon for document uploads"
  namespace_id         = alicloud_sae_namespace.production.id
  package_type         = "Image"
  image_url            = var.clamav_image_url
  replicas             = 1
  cpu                  = 1000
  memory               = 4096
  vpc_id               = var.vpc_id
  vswitch_id           = var.vswitch_id
  security_group_id    = var.security_group_id
  timezone             = "Asia/Shanghai"
  programming_language = "other"
  micro_registration   = "0"
  deploy               = true
  status               = "RUNNING"
  sls_configs          = var.sae_sls_configs

  liveness_v2 {
    initial_delay_seconds = 120
    period_seconds        = 15
    timeout_seconds       = 3
    failure_threshold     = 5
    tcp_socket {
      port = 3310
    }
  }

  readiness_v2 {
    initial_delay_seconds = 90
    period_seconds        = 10
    timeout_seconds       = 3
    failure_threshold     = 12
    tcp_socket {
      port = 3310
    }
  }

  lifecycle {
    precondition {
      condition     = var.clamav_image_url != "" && var.clamav_intranet_slb_id != ""
      error_message = "enable_clamav_sae requires clamav_image_url and clamav_intranet_slb_id."
    }
  }
}

resource "alicloud_sae_load_balancer_intranet" "clamav" {
  count = var.enable_runtime && var.enable_clamav_sae ? 1 : 0

  app_id          = alicloud_sae_application.clamav[0].id
  intranet_slb_id = var.clamav_intranet_slb_id

  intranet {
    protocol    = "TCP"
    port        = 3310
    target_port = 3310
  }
}

resource "alicloud_sae_application" "api" {
  count = var.enable_runtime ? 1 : 0

  app_name                         = "${var.project_name}-api"
  app_description                  = "WealthProfolio FastAPI"
  namespace_id                     = alicloud_sae_namespace.production.id
  package_type                     = "Image"
  image_url                        = var.backend_image_url
  replicas                         = var.api_replicas
  cpu                              = 1000
  memory                           = 2048
  vpc_id                           = var.vpc_id
  vswitch_id                       = var.vswitch_id
  security_group_id                = var.security_group_id
  timezone                         = "Asia/Shanghai"
  programming_language             = "other"
  micro_registration               = "0"
  deploy                           = true
  status                           = "RUNNING"
  envs                             = jsonencode(concat(local.backend_environment, local.sae_secret_reference))
  sls_configs                      = var.sae_sls_configs
  termination_grace_period_seconds = 30

  liveness_v2 {
    initial_delay_seconds = 30
    period_seconds        = 15
    timeout_seconds       = 3
    failure_threshold     = 5
    http_get {
      path   = "/api/health"
      port   = 8000
      scheme = "HTTP"
    }
  }

  readiness_v2 {
    initial_delay_seconds = 10
    period_seconds        = 10
    timeout_seconds       = 3
    success_threshold     = 1
    failure_threshold     = 6
    http_get {
      path   = "/api/health"
      port   = 8000
      scheme = "HTTP"
    }
  }

  lifecycle {
    precondition {
      condition = alltrue([
        var.vpc_id != "",
        var.vswitch_id != "",
        var.security_group_id != "",
        var.backend_image_url != "",
        var.sae_secret_name != "",
        var.sae_secret_id > 0,
        var.kms_key_id != "",
        var.oss_endpoint != "",
        var.oss_public_endpoint != "",
        var.oss_bucket != "",
        local.clamav_host != "",
        length(var.cors_origins) > 0,
      ])
      error_message = "Runtime networking, image, SAE Secret, KMS, OSS, ClamAV, and CORS values must be set before enable_runtime=true."
    }
  }
}

resource "alicloud_sae_load_balancer_intranet" "api" {
  count = var.enable_runtime && var.api_intranet_slb_id != "" ? 1 : 0

  app_id          = alicloud_sae_application.api[0].id
  intranet_slb_id = var.api_intranet_slb_id

  intranet {
    protocol    = "HTTP"
    port        = 80
    target_port = 8000
  }
}

resource "alicloud_sae_application" "worker" {
  count = var.enable_runtime ? 1 : 0

  app_name             = "${var.project_name}-worker"
  app_description      = "WealthProfolio Celery document, agent, and price worker"
  namespace_id         = alicloud_sae_namespace.production.id
  package_type         = "Image"
  image_url            = var.backend_image_url
  replicas             = var.worker_replicas
  cpu                  = 2000
  memory               = 4096
  vpc_id               = var.vpc_id
  vswitch_id           = var.vswitch_id
  security_group_id    = var.security_group_id
  timezone             = "Asia/Shanghai"
  programming_language = "other"
  micro_registration   = "0"
  deploy               = true
  status               = "RUNNING"
  command              = "celery"
  command_args_v2 = [
    "-A",
    "app.worker:celery_app",
    "worker",
    "--loglevel=INFO",
    "--concurrency=${var.celery_concurrency}",
    "--hostname=celery@%h",
  ]
  envs                             = jsonencode(concat(local.backend_environment, local.sae_secret_reference))
  sls_configs                      = var.sae_sls_configs
  termination_grace_period_seconds = 60

  liveness_v2 {
    initial_delay_seconds = 60
    period_seconds        = 30
    timeout_seconds       = 3
    failure_threshold     = 5
    exec {
      command = [
        "sh",
        "-c",
        "celery -A app.worker:celery_app inspect ping --timeout 5 | grep -q pong",
      ]
    }
  }

  lifecycle {
    precondition {
      condition     = var.backend_image_url != "" && var.sae_secret_name != "" && var.sae_secret_id > 0
      error_message = "The worker requires backend_image_url and an existing SAE Secret."
    }
  }
}

resource "alicloud_sae_application" "frontend" {
  count = var.enable_frontend ? 1 : 0

  app_name             = "${var.project_name}-web"
  app_description      = "WealthProfolio Next.js"
  namespace_id         = alicloud_sae_namespace.production.id
  package_type         = "Image"
  image_url            = var.frontend_image_url
  replicas             = 2
  cpu                  = 1000
  memory               = 2048
  vpc_id               = var.vpc_id
  vswitch_id           = var.vswitch_id
  security_group_id    = var.security_group_id
  timezone             = "Asia/Shanghai"
  programming_language = "other"
  micro_registration   = "0"
  deploy               = true
  status               = "RUNNING"
  envs = jsonencode([
    {
      name  = "BACKEND_INTERNAL_URL"
      value = var.backend_internal_url
    },
    {
      name  = "NEXT_TELEMETRY_DISABLED"
      value = "1"
    },
  ])
  sls_configs                      = var.sae_sls_configs
  termination_grace_period_seconds = 30

  liveness_v2 {
    initial_delay_seconds = 30
    period_seconds        = 15
    timeout_seconds       = 3
    failure_threshold     = 5
    http_get {
      path   = "/"
      port   = 3000
      scheme = "HTTP"
    }
  }

  readiness_v2 {
    initial_delay_seconds = 10
    period_seconds        = 10
    timeout_seconds       = 3
    failure_threshold     = 6
    http_get {
      path   = "/"
      port   = 3000
      scheme = "HTTP"
    }
  }

  lifecycle {
    precondition {
      condition = alltrue([
        var.enable_runtime,
        var.frontend_image_url != "",
        var.backend_internal_url != "",
        var.vpc_id != "",
        var.vswitch_id != "",
        var.security_group_id != "",
      ])
      error_message = "Frontend requires a running API, an immutable image, BACKEND_INTERNAL_URL, and VPC networking."
    }
  }
}

resource "alicloud_fcv3_function" "ocr" {
  count = var.enable_fc_ocr ? 1 : 0

  function_name        = var.fc_ocr_function_name
  description          = "Asynchronous page-level OCR for WealthProfolio"
  runtime              = "custom-container"
  handler              = "index.handler"
  memory_size          = var.fc_ocr_memory_mb
  cpu                  = var.fc_ocr_cpu
  disk_size            = 512
  timeout              = 900
  instance_concurrency = 1
  internet_access      = false
  role                 = var.fc_ocr_role_arn

  custom_container_config {
    image = var.fc_ocr_image_url
    port  = 9000
    health_check_config {
      http_get_url          = "/health"
      initial_delay_seconds = 5
      period_seconds        = 10
      success_threshold     = 1
      failure_threshold     = 3
      timeout_seconds       = 2
    }
  }

  vpc_config {
    vpc_id            = var.vpc_id
    vswitch_ids       = [var.vswitch_id]
    security_group_id = var.security_group_id
  }

  environment_variables = {
    OSS_BUCKET   = var.oss_bucket
    OSS_ENDPOINT = var.oss_endpoint
    KMS_KEY_ID   = var.kms_key_id
  }

  dynamic "log_config" {
    for_each = var.fc_sls_project != "" && var.fc_sls_logstore != "" ? [1] : []
    content {
      project                 = var.fc_sls_project
      logstore                = var.fc_sls_logstore
      log_begin_rule          = "None"
      enable_instance_metrics = true
      enable_request_metrics  = true
    }
  }

  lifecycle {
    precondition {
      condition = alltrue([
        var.fc_ocr_image_url != "",
        var.fc_ocr_role_arn != "",
        var.vpc_id != "",
        var.vswitch_id != "",
        var.security_group_id != "",
        var.oss_bucket != "",
        var.oss_endpoint != "",
        var.kms_key_id != "",
      ])
      error_message = "FC OCR requires its integrated image, execution role, VPC, OSS, and KMS values."
    }
  }
}

resource "alicloud_fcv3_async_invoke_config" "ocr" {
  count = var.enable_fc_ocr ? 1 : 0

  function_name                  = alicloud_fcv3_function.ocr[0].function_name
  qualifier                      = "LATEST"
  async_task                     = "true"
  max_async_retry_attempts       = 2
  max_async_event_age_in_seconds = 3600
}
