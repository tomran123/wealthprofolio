# 本地 Docker Compose 运行手册

这套 Compose 用于开发、演示和隔离验收，不是阿里云生产拓扑。它包含：

- PostgreSQL 16 + pgvector
- 独立一次性 Alembic migration
- FastAPI 与 Next.js
- Redis
- RabbitMQ
- Celery worker（共享消费 `documents.process`、`agent.run` 与 `prices.refresh`）
- ClamAV
- MinIO 及私有 Bucket 初始化
- 可选的 AES-256 加密本地备份

## 数据安全前提

`postgres_data` 卷名、PostgreSQL 16 主版本以及 Alpine libc/locale 家族都保持
不变。`ops/postgres/Dockerfile` 在原 `postgres:16-alpine` 基础上编译固定版本
pgvector，避免把现有 Alpine 数据目录直接挂到官方 Debian pgvector 镜像。即使
如此，镜像兼容也不等于可以跳过备份。

对于已有真实数据的机器：

1. 不要先执行 `docker compose down -v`；任何时候都不要加 `-v`。
2. 先用当前仍在运行的 PostgreSQL 生成并校验一份 `pg_dump -Fc` 备份。
3. 记录当前 `alembic current` 和数据库行数。
4. 再切换镜像并执行一次性 migration。
5. migration 失败时保持 API 停止，排查后重试；不要自动执行 downgrade。

## 首次配置

```bash
cp .env.example .env
openssl rand -hex 32
```

将每个 `replace-*` 值替换为不同的随机值。Redis 与 RabbitMQ 密码会进入 URL，
应使用十六进制或 Base64URL 字符，避免未转义的 `@`、`:`、`/`。

只做静态校验，不启动服务：

```bash
docker compose --env-file .env config --quiet
```

若本机默认的 PostgreSQL 端口已被占用，可使用随仓库提供的覆盖文件。它会将
基础文件的 `5432` 映射替换为 `5433`，不会同时暴露两个端口：

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml \
  --env-file .env config --quiet
docker compose -f docker-compose.yml -f docker-compose.local.yml \
  --env-file .env up -d
```

## 启动顺序

```bash
docker compose pull redis rabbitmq minio minio-init clamav
docker compose build postgres backend frontend backup
docker compose up -d
```

`migrate` 是一次性容器。只有它以 0 退出后，API 和 Celery worker 才会启动。
API 镜像自身不再运行 Alembic，因此横向扩容不会争抢 migration lock。
Agent、价格刷新与文档任务都强制走 Celery（`AGENT_JOB_BACKEND=celery`、
`AGENT_INLINE_FALLBACK=false`、`PRICE_JOB_BACKEND=celery`、
`PRICE_INLINE_FALLBACK=false`）；共享 worker 不限定 queue，因此会同时消费
`documents.process`、`agent.run` 与 `prices.refresh`。Agent 创建入口为
`POST /api/v1/agent/jobs`，状态与事件分别使用 `GET /api/v1/jobs/{id}` 和
`WS /api/v1/ws/jobs/{id}`。

检查：

```bash
docker compose ps
docker compose logs migrate
docker compose exec backend alembic current
docker compose exec postgres psql -U wealthportfolio -d wealthportfolio -c '\dx vector'
```

本机端口默认只绑定 `127.0.0.1`：

| 服务 | 地址 |
| --- | --- |
| Web | `http://localhost:3000` 或 `http://127.0.0.1:3000` |
| API | `http://127.0.0.1:8000/api/health` |
| PostgreSQL | `127.0.0.1:${POSTGRES_PORT:-5432}` |
| Redis | `127.0.0.1:6379` |
| RabbitMQ Management | `http://127.0.0.1:15672` |
| MinIO API / Console | `127.0.0.1:9000` / `http://127.0.0.1:9001` |

ClamAV 仅在 Compose 私网开放 3310，不发布到主机。

## 加密本地备份

生产必须使用 RDS 自动备份/PITR 和加密 OSS；本地备份是显式 opt-in：

```bash
export BACKUP_ENCRYPTION_PASSPHRASE="$(openssl rand -hex 32)"
docker compose --profile backup up -d backup
```

备份先在容器临时目录生成 PostgreSQL custom dump，然后使用
AES-256-CBC + PBKDF2 加密；主机 `backups/` 只收到
`backup_*.dump.enc`。请将 passphrase 放进密码管理器，丢失后无法恢复。
backup 镜像以 UID/GID `10001:10001` 非 root 运行；Linux 主机若拒绝写入，
请只给该 UID 对 `backups/` 的写权限（ACL 或调整该目录属主），不要把容器改为
root，也不要递归修改仓库其他目录权限。

任何恢复动作都会覆盖数据，应先在隔离数据库做恢复演练并核对 checksum。
