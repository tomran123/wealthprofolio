# WealthProfolio 阿里云生产部署手册（Sprint 1）

本目录是可执行的部署骨架，不包含真实账号 ID、AccessKey、密码或云资源。
当前仓库没有阿里云凭据，因此没有创建或修改任何云资源。

## 选择结论

长期运行的 Next.js、FastAPI 和 Celery worker 放在 SAE，原因是它们分别需要
常驻 HTTP、WebSocket/长连接能力和持续消费 RabbitMQ。共享 worker 同时消费
`documents.process`、`agent.run` 与 `prices.refresh`；生产固定设置
`AGENT_JOB_BACKEND=celery`、`AGENT_INLINE_FALLBACK=false`、
`PRICE_JOB_BACKEND=celery`、`PRICE_INLINE_FALLBACK=false`，避免 API 进程内执行
Agent 或价格刷新。Agent 创建入口为
`POST /api/v1/agent/jobs`，状态与事件分别使用 `GET /api/v1/jobs/{id}` 和
`WS /api/v1/ws/jobs/{id}`。页级 OCR 是突发、可重试的短任务，适合 Function
Compute v3 异步任务。PostgreSQL 仍是唯一 OLTP 与事件事实源，Redis 只保存
缓存/限流/结果，RabbitMQ 只传递任务，OSS 只保存私有文档。

```text
WAF / HTTPS ALB
  |-- /* ---------> Next.js (SAE)
  +-- /api/* -----> FastAPI (SAE, including WebSocket upgrade)
                        |   |  \
                        |   |   +---- OSS private bucket + SSE-KMS
                        |   +-------- Tair/Redis
                        +------------ ApsaraMQ for RabbitMQ
                                         |
                                    Celery worker (SAE)
                                         |
                                    FC v3 page OCR
```

官方依据：

- [SAE 支持容器镜像、环境变量、健康检查和 Terraform](https://www.alibabacloud.com/help/en/sae/application-deployment-overview)
- [SAE Job 会在任务结束后释放实例，适合一次性 migration](https://www.alibabacloud.com/help/en/sae/job-template-management-2-0)
- [Function Compute 自定义容器](https://www.alibabacloud.com/help/en/functioncompute/fc/user-guide/custom-container/)
- [Function Compute 异步任务](https://www.alibabacloud.com/help/en/functioncompute/fc/asynchronous-task)
- [RDS PostgreSQL pgvector](https://www.alibabacloud.com/help/en/rds/apsaradb-rds-for-postgresql/pgvector-use-guide)
- [OSS 服务端加密](https://www.alibabacloud.com/help/en/oss/user-guide/data-encryption/)
- [SAE Secret 注入环境变量](https://www.alibabacloud.com/help/doc-detail/2773561.html)

## 必须由账号所有者完成的操作

以下操作会开通计费服务、创建角色或接触生产密钥，必须在阿里云控制台由你确认。
所有服务应选择同一 Region 和同一 VPC；示例使用 `cn-hangzhou`，不要盲目照抄。

### 1. 账号、RAM 与服务开通

1. 不使用主账号 AccessKey。创建单独的部署 RAM 用户/角色，并启用 MFA。
2. 开通 SAE、SAE Job、EventBridge、ACR、RDS PostgreSQL、Tair/Redis、
   ApsaraMQ for RabbitMQ、OSS、KMS、Function Compute、SLS、WAF 和负载均衡。
3. 首次打开 SAE Job 时，按控制台提示创建
   `AliyunServiceRoleForEventBridgeSendToSAE`。
4. 给部署身份授予限于目标 Region/资源组的创建和部署权限；不要给应用运行身份
   管理 RDS、RAM 或 KMS 的权限。
5. 为 API/worker、FC OCR、migration 分别创建最小权限运行身份。FC OCR 只需要
   指定 OSS prefix 的读写、指定 KMS key 的使用及 SLS 写入。

### 2. VPC 与入口

1. 创建或选择 VPC、至少两个 vSwitch、一个仅允许必要东西向流量的安全组。
2. RDS、Redis、RabbitMQ、CLB 和 SAE 全部使用私网地址；不要创建公网数据库地址。
3. RDS/Tair 白名单填写 SAE vSwitch CIDR，而不是单个会变化的容器 IP。
4. 为 API 准备私网 CLB 或 SAE Gateway；API 不直接暴露独立公网入口。
5. 为同一域名准备 HTTPS ALB，绑定证书并接入 WAF。将 `/api/*`（包括
   `/api/v1/ws/*` 的 WebSocket upgrade）路由到 API，其余路径路由到 Web；
   安全组只允许该入口访问 SAE 应用。Next.js rewrite 只作 HTTP 后备路径，不能
   替代入口层显式的 WebSocket 路由。
6. 中国大陆公网域名按实际主体完成 ICP 备案。

### 3. RDS PostgreSQL

1. 选择区域支持的 PostgreSQL 16 高可用规格，开启 SSL、删除保护、自动备份和
   PITR。部署前在控制台核实该版本支持 `vector` 扩展，并由 RDS 高权限账号先执行
   `CREATE EXTENSION IF NOT EXISTS vector`；普通 migration owner 不应获得扩展
   管理权限。
2. 创建 `wealthportfolio` 数据库，再在 RDS 控制台创建两个不同的 LOGIN：
   `wp_migration_owner` 与 `wp_runtime`。密码只在控制台/密码管理器生成，不传给
   Terraform 或 SQL 脚本。
3. `wp_migration_owner` 是 schema owner，只用于 Alembic SAE Job；
   `wp_runtime` 只用于 API/worker。Terraform 的
   `migration_database_role`/`runtime_database_role` 会阻止两个名称相同，但
   SAE Secret 是不透明的，仍须人工核对两条 URL 的用户名。
4. 用 RDS 高权限 bootstrap 账号执行 `ops/db/bootstrap-roles.sql`，迁移后立即用
   owner 执行 `ops/db/harden-runtime.sql`，并用 runtime 连接执行只读的
   `ops/db/verify-runtime-privileges.sql`。API/worker 在验证通过前保持关闭。
5. 将连接串做 URL 编码并要求 SSL，例如放入 Secret 的 `DATABASE_URL`，绝不写入
   `terraform.tfvars`。
6. 首次 migration 后确认 `vector` 扩展、Alembic head 和所有索引均存在。

最终权限契约如下：

- `transactions`、`journal_entries`、`journal_postings`、`audit_events`、
  `outbox_events`、`price_snapshots`、`valuation_snapshots`：runtime 仅
  `SELECT/INSERT`，无直接 `UPDATE/DELETE/TRUNCATE`；`fx_rate_snapshots` 同样
  按不可变快照处理。
- `holdings`：runtime 可 `SELECT/INSERT`，只能更新 `quantity`、`source`、
  `projection_version`、`last_event_id`、`updated_at` 投影列。
- `transaction_metadata_projections`：只能更新有效元数据投影列。
- `alembic_version`：runtime 只读；只有 migration owner 可改 schema。
- reversal marker、未入账 draft 删除、outbox 投递状态分别通过
  `wp_mark_transaction_reversed`、`wp_delete_draft_transaction`、
  `wp_record_outbox_delivery` 三个 `SECURITY DEFINER` 边界执行。

Alembic 0015 是三个数据库函数及不可变触发器的唯一定义源；Python 的
reversal/draft 路径调用函数，`harden-runtime.sql` 只负责收紧表权限并授权
`EXECUTE`，不会用重复函数体覆盖 migration 契约。旧版仍做直接 `UPDATE/DELETE`
的容器在严格权限下会有意报 permission denied，不能通过恢复整表权限来绕过。

### 4. Redis 与 RabbitMQ

1. Tair/Redis 选择 VPC 私网、TLS 和密码认证；DB 0 用缓存/限流，DB 1 用 Celery
   result backend。
2. ApsaraMQ for RabbitMQ 选择 Serverless 或与负载匹配的规格，并使用兼容 Celery
   的开源用户名/密码认证模式，创建独立 vhost。
3. 只允许 SAE vSwitch CIDR；优先使用 TLS endpoint。
4. 将完整的 `REDIS_URL`、`CELERY_RESULT_BACKEND`、
   `CELERY_BROKER_URL` 放入 SAE Secret。用户名和密码必须 URL 编码。

### 5. OSS、KMS 与病毒扫描

1. 创建唯一名称的私有 OSS Bucket，开启版本控制、禁止公共 ACL，并将默认服务端
   加密设为 SSE-KMS。
2. 创建客户管理 KMS key，开启轮换和删除保护。给应用身份仅授予该 key 的
   `GenerateDataKey`/`Decrypt` 及必要 OSS prefix 权限。
3. 为浏览器直传配置最小 CORS：只允许正式 Web origin、`PUT/HEAD` 和应用实际
   使用的 headers；不要设置 `*`。
4. `DOCUMENT_STORAGE_ENDPOINT` 使用 VPC 内网 endpoint；另行设置
   `DOCUMENT_STORAGE_PUBLIC_ENDPOINT=https://oss-<region>.aliyuncs.com`，只用于
   签发浏览器可访问的上传/预览 URL。不能把 `-internal` 地址返回给浏览器，也不能
   在生产使用 HTTP。
5. 代码当前的 OSS adapter 显式读取 access key，因此 Sprint 1 需要一个权限极小、
   可轮换的 RAM 凭据。把它放进 SAE Secret；不要放在镜像、Terraform state 或 SLS。
6. 生产上传必须经过 clamd。可以把经过安全审核并固定版本的 ClamAV 镜像镜像到
   ACR，然后启用 Terraform 中的 `enable_clamav_sae`，也可以提供已管理的
   `external_clamav_host`。不允许把 `DOCUMENT_CLAMAV_REQUIRED` 关闭后上线。

### 6. Secrets

KMS Secrets Manager 是密钥的主记录。Sprint 1 的容器启动方式仍需要 SAE Secret
把值注入环境变量，因此需要在 SAE namespace 中创建两个 Secret：

- `wealthprofolio-prod-runtime`：runtime 最小权限数据库连接和应用密钥。
- `wealthprofolio-prod-migration`：只给一次性 migration Job，包含临时高权限
  `DATABASE_URL`；migration 后轮换或禁用。

Migration Job 不注入 runtime Secret，也不设置 `ENVIRONMENT=production`。
Alembic 只读取 migration Secret 中的 `DATABASE_URL`，不会实例化要求
Redis、RabbitMQ、OSS、ClamAV、JWT 和 KMS 全部就绪的 API 运行时配置。

runtime Secret 至少包含：

```text
DATABASE_URL
REDIS_URL
CELERY_BROKER_URL
CELERY_RESULT_BACKEND
JWT_SECRET
INITIAL_ADMIN_USERNAME
INITIAL_ADMIN_PASSWORD
ALIBABA_CLOUD_ACCESS_KEY_ID
ALIBABA_CLOUD_ACCESS_KEY_SECRET
DOCUMENT_STORAGE_ACCESS_KEY
DOCUMENT_STORAGE_SECRET_KEY
LLM_ENCRYPTION_KEY
```

密钥值不能出现在 Terraform variables。Terraform 仅保存 SAE Secret 的数字 ID，
通过 `valueFrom.secretRef` 引用。KMS 中轮换后，同步更新 SAE Secret 并滚动重启
应用；SAE Secret 修改不会自动更新已运行容器。

## 可执行部署顺序

### A. 工具与 ACR

本机安装 Terraform 1.7+、Alibaba Cloud CLI、`jq`、Docker buildx。按 ACR
控制台给出的短期凭据执行 `docker login`，不要把密码作为脚本参数。
先进入仓库根目录；下文命令都从该目录执行。

先构建后端镜像：

```bash
export ACR_PUSH_REGISTRY=registry.cn-hangzhou.aliyuncs.com
export ACR_RUNTIME_REGISTRY=registry-vpc.cn-hangzhou.aliyuncs.com
export ACR_NAMESPACE=your-reviewed-namespace
export IMAGE_TAG=your-immutable-git-sha
./deploy/alicloud/scripts/build-and-push.sh backend
```

脚本输出可直接填入 `backend_image_url`。不要使用 `latest`。
默认 Python 包源仍是 Dockerfile 中的官方
`https://pypi.org/simple`。若构建网络必须使用经过组织审核的私有/可信镜像，
可显式传入：

```bash
export PYTHON_PACKAGE_INDEX_URL=https://your-reviewed-index.example.com/simple
./deploy/alicloud/scripts/build-and-push.sh backend
unset PYTHON_PACKAGE_INDEX_URL
```

该值必须是 HTTPS，且不能在 URL 中嵌入用户名、密码或 token。此 build arg
不是 Secret 通道；需要鉴权的镜像应由受控构建网络提供无凭据 URL，或先扩展为
BuildKit Secret 后再使用。

### B. Terraform 只创建 namespace

```bash
cp deploy/alicloud/terraform/terraform.tfvars.example \
  deploy/alicloud/terraform/terraform.tfvars
terraform -chdir=deploy/alicloud/terraform init
terraform -chdir=deploy/alicloud/terraform fmt -check
terraform -chdir=deploy/alicloud/terraform validate
terraform -chdir=deploy/alicloud/terraform plan -out namespace.tfplan
terraform -chdir=deploy/alicloud/terraform apply namespace.tfplan
terraform -chdir=deploy/alicloud/terraform output -raw sae_namespace_id
```

首次保持：

```hcl
enable_runtime  = false
enable_frontend = false
enable_fc_ocr   = false
```

逐项替换 `REPLACE` 值并审阅 plan。`terraform.tfvars`、`*.tfplan` 和 state
已被 gitignore，但生产 state 仍应放在加密、锁定且有访问审计的远端 backend；
plan 文件也应按敏感部署产物管理，不要发送到聊天或提交到版本库。

### C. 创建 Secret 并执行 migration

在刚创建的 SAE namespace 中创建 runtime/migration Secret，记录其名称和数字 ID。
先确认 RDS 自动备份成功，并额外保留一次可验证快照。

先在 RDS 控制台创建 `wp_migration_owner` 和 `wp_runtime`，然后用一次性
bootstrap URL 建立 owner/runtime 边界。`read -s` 避免 URL 进入 shell history：

```bash
read -rsp 'RDS bootstrap URL: ' RDS_BOOTSTRAP_DATABASE_URL && echo
export RDS_BOOTSTRAP_DATABASE_URL
psql "$RDS_BOOTSTRAP_DATABASE_URL" \
  -v migration_role=wp_migration_owner \
  -v runtime_role=wp_runtime \
  -f ops/db/bootstrap-roles.sql
unset RDS_BOOTSTRAP_DATABASE_URL
```

migration Secret 的 `DATABASE_URL` 用户必须是 `wp_migration_owner`，runtime
Secret 的用户必须是 `wp_runtime`。两者不得互换。

```bash
export ALICLOUD_REGION=cn-hangzhou
export SAE_NAMESPACE_ID=cn-hangzhou:wealthprofolio-prod
export VPC_ID=vpc-actual
export VSWITCH_ID=vsw-actual
export SECURITY_GROUP_ID=sg-actual
export BACKEND_IMAGE_URL=registry-vpc.cn-hangzhou.aliyuncs.com/actual/backend:sha
export SAE_MIGRATION_SECRET_NAME=wealthprofolio-prod-migration
export SAE_MIGRATION_SECRET_ID=123
export RELEASE_ID=your-immutable-git-sha
export CONFIRM_CREATE_JOB=YES
./deploy/alicloud/scripts/create-migration-job.sh
```

脚本只创建 Job template，不改数据库。到 SAE 控制台复核镜像、VPC、Secret reference
和命令 `alembic upgrade head`，再执行：

```bash
export SAE_MIGRATION_JOB_ID=the-returned-app-id
export CONFIRM_RUN_MIGRATION=YES
./deploy/alicloud/scripts/run-migration-job.sh
```

等待 Job record 为 `Succeeded`，检查日志和 `alembic current`。失败时保持 runtime
关闭，修复后使用同一个 `EventId` 重试；不要让 API 容器代跑 migration。

成功后、启动 runtime 前，用 migration owner 收紧权限，再用 runtime URL 做只读
验收（同样建议通过 `read -s` 或密码管理器临时注入）：

```bash
psql "$MIGRATION_DATABASE_URL" \
  -v runtime_role=wp_runtime \
  -f ops/db/harden-runtime.sql
psql "$RUNTIME_DATABASE_URL" \
  -f ops/db/verify-runtime-privileges.sql
```

每次 Alembic migration 都可能创建新表，因此发布流水线必须重复
`harden-runtime.sql` 与 `verify-runtime-privileges.sql`；两者之间 API/worker
replicas 保持为 0。

### D. 启动 API、worker 和 ClamAV

把 runtime Secret ID、OSS/KMS、ClamAV 和网络真实值填入 `terraform.tfvars`，设置：

```hcl
enable_runtime = true
```

然后：

```bash
terraform -chdir=deploy/alicloud/terraform plan -out runtime.tfplan
terraform -chdir=deploy/alicloud/terraform apply runtime.tfplan
terraform -chdir=deploy/alicloud/terraform output api_intranet_ip
```

确认 API health、Celery 与 RabbitMQ 连接、共享 worker 已注册
`documents.process`、`agent.run` 和 `prices.refresh`、ClamAV `PING/PONG`、
OSS 私有写入后再部署 Web。不要通过 `-Q` 把该 worker 限制到单一 queue。

### E. 构建并启动 Web

将 API 私网 CLB/Gateway URL 作为 build arg。它会写入 Next.js rewrite manifest，
因此必须在构建时确定：

```bash
export BACKEND_INTERNAL_URL=http://private-api-host
./deploy/alicloud/scripts/build-and-push.sh frontend
```

填入输出的 `frontend_image_url` 和相同 `backend_internal_url`，再设置：

```hcl
enable_frontend = true
```

```bash
terraform -chdir=deploy/alicloud/terraform plan -out frontend.tfplan
terraform -chdir=deploy/alicloud/terraform apply frontend.tfplan
```

最后在控制台把 Web 与 API 接到同一个 HTTPS ALB 和 WAF，按前述规则配置
`/api/*` 与 WebSocket upgrade，再配置 DNS、证书、限流和访问日志。API 不应有
可绕过 WAF/ALB 的独立公网入口；服务端渲染与 HTTP 后备代理继续使用
`BACKEND_INTERNAL_URL`。

## Function Compute OCR 的启用门槛

Terraform 已包含 FC v3 custom-container、VPC、执行 RAM role 和 async task 配置，
但默认 `enable_fc_ocr=false`。这不是占位资源：启用前必须提供一个真正实现 FC
custom-container HTTP contract、`/health`、OSS object 输入、页级 OCR 输出和幂等
callback 的镜像，并把文档 pipeline 的调用端接通。

当前应用内的 `AlibabaCloudOCRProvider` 只有 adapter boundary，没有配置可调用的
recognizer。未完成这一步时，生产 worker 应保持 `document_ocr_provider=tesseract`；
直接改成 `alibaba_ocr` 会让任务失败。完成端到端集成和契约测试后才设置：

```hcl
enable_fc_ocr    = true
fc_ocr_image_url = "registry-vpc.../ocr:immutable-sha"
fc_ocr_role_arn  = "acs:ram::ACCOUNT:role/least-privilege-role"
```

## 上线验收

至少完成：

1. API、Web、worker、ClamAV、RDS、Redis、RabbitMQ、OSS、KMS、SLS 均无公网管理面。
2. `GET /api/health` 正常，未授权 API 返回 401/403。
3. 两个 Family 的文档、任务、检索、Agent、LLM 配置互不可见。
4. 上传 EICAR 测试文件被拒绝；超页数/PDF bomb 测试被拒绝。
5. OSS 对象匿名访问失败，上传签名短期过期，默认对象加密为 KMS。
6. 文档任务经 RabbitMQ/Celery 完成，Redis 仅保留短期状态。
7. migration Job 结束后不再有 migration 实例；API 扩容不产生 Alembic 日志。
8. RDS 快照可在隔离实例恢复，账本和持仓 checksum 一致。
9. WAF、SLS、RDS、RabbitMQ 和 FC 告警已接收一次测试事件。

## 回滚原则

- 应用回滚：在 SAE 回滚到上一不可变镜像 tag。
- 数据库：只前向修复，不让 API 自动 downgrade。破坏性迁移必须经过独立恢复演练。
- OCR：关闭 `enable_fc_ocr` 并切回 Celery/Tesseract，不影响 PostgreSQL 事实源。
- 队列/缓存：Redis 和 RabbitMQ 可重建，不得把它们当业务事实源。
- Terraform destroy 会产生真实数据/费用影响；本手册不提供一键 destroy。
