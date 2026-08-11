# Family Office OS：未来 3 个 Sprint 迭代路线图

> 生成日期：2026-07-24  
> 依据：当前 WealthPortfolio 前端、后端、数据库迁移、API、测试及基础设施配置的仓库级审查  
> 团队与节奏：每个 Sprint 2 周，3 人团队（全栈、AI/数据、DevOps/QA 各 1 人），约 30 人日/Sprint  
> 部署主线：阿里云优先，本地 Docker Compose 保留  
> 产品优先级：AI 演示优先，但 Sprint 1 前三天的账本、Family 数据边界与审计修复是后续功能的合并硬门槛  
> 范围约束：`Family` 是唯一顶层业务边界，不引入额外组织层或 SaaS 计费模型

---

## 一、当前代码真实成熟度

| 蓝图模块        | 当前实现                                                                                                                                  | 判断                                                                                                                                    |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| 1. 资产中心     | 已有现金、股票、ETF、债券、基金、房地产、私募、公司股权、黄金、加密、负债、自定义资产，见 [资产枚举](backend/app/models/enums.py#L21-L34) | 基础可用；缺定存、收藏品、保险现金价值、养老金、VC/PE 区分、RSU、期权及类型化属性                                                       |
| 2. 账户中心     | 已有 Owner、Institution、Account、Holding 层级，[Account](backend/app/models/account.py#L11-L36) 同时关联 Owner 和 Institution            | 手工账户中心可用；无 Family 数据边界、连接器、OAuth2 凭据和账户同步                                                                     |
| 3. 事件溯源     | `TransactionService` 写交易时同步调整持仓，并能重放；但持仓仍可直接写、交易可物理删除                                                     | 只是“账本辅助的状态模型”，不是真正事件溯源                                                                                              |
| 4. 市场数据     | Yahoo、AKShare、CoinGecko、贵金属代理、Frankfurter、价格/汇率快照均已存在                                                                 | 无公司事件、股息、历史 OHLCV、NAV 回填、基准、自动调度                                                                                  |
| 5. AI Agent     | 已有大量类型化工具、Chat/Vision 分离、Pending Action、确认后原子执行、会话历史                                                            | 是当前最大亮点；但无 RAG、持久文档、流式进度、AI 记忆，仍暴露直接持仓工具                                                               |
| 6. 组合分析     | 已支持按八个维度聚合及手工 ExposureGroup                                                                                                  | 无收益、归因、基准、风险、自动穿透；[迁移 0007](backend/alembic/versions/0007_performance_indexes.py#L1-L32) 仅创建索引，并不存在绩效表 |
| 7. 仪表盘       | 净资产、负债、配置饼图、Top Holdings、历史曲线                                                                                            | 无当日盈亏、涨跌榜、现金流、事件、AI 洞察、旭日图/桑基图/热力图                                                                         |
| 8. 文档中心     | Agent 请求内临时解析图片/PDF                                                                                                              | 没有对象存储、OCR 文本、全文检索、向量索引、文档关系或 RAG                                                                              |
| 9. 自动化       | 每日 `pg_dump` 容器备份                                                                                                                   | 无价格刷新、每日快照、报告及提醒调度                                                                                                    |
| 10. 安全        | bcrypt、JWT Cookie、登录限流、Fernet 加密 LLM Key                                                                                         | 无 RBAC、CSRF、2FA/TOTP、OAuth2、API Key 管理、AES-256、统一审计和 Secrets Manager                                                      |
| 11. Family 扩展 | 有独立 `users` 表                                                                                                                         | 实际没有 Family、家庭成员关系或业务表 `family_id`，无法隔离不同家庭的数据                                                               |

---

## 二、添加新功能前必须修复的架构债务

### 1. 持仓存在多个事实来源

[持仓路由](backend/app/api/routes/holdings.py#L19-L58) 可直接设置、调整、删除 `Holding`；[市场搜索添加持仓](backend/app/services/market_instrument_service.py#L300-L398) 也直接写表；前端 [AddHoldingDialog](frontend/src/components/add-holding-dialog.tsx#L103-L130) 同样绕过交易。

必须改为：

- `transactions` 是不可变业务事件。
- `holdings` 只是可重放投影。
- “设置持仓”转换为 `opening_balance` 或 `reconciliation` 事件。
- “删除交易”转换为 reversal 补偿事件。
- 禁止任何 API、Agent 或导入直接改持仓。

### 2. 当前并非正式复式记账

[交易服务](backend/app/services/transaction_service.py#L136-L477) 使用带符号交易及现金持仓联动，但没有 Journal Entry、Posting、借贷平衡不变量。因此更准确地说是“双投影更新”，不是正式复式账本。

需要增加 `journal_entries`、`journal_postings`，并保证每笔业务事件在每种币种下借贷平衡。

### 3. CSV 导入不是原子事务

[commit_batch()](backend/app/services/import_service.py#L235-L306) 在循环中调用默认 `commit=True` 的持仓和估值服务：

- 部分行可能已提交，后续行再失败。
- 导入不生成交易。
- 同一文件重试可能重复累计。

必须改为单事务、每行幂等、生成 opening/reconciliation 事件。

### 4. 当前没有 Family 数据边界

[User](backend/app/models/user.py#L8-L16) 没有与任何业务实体关联；Owner、Agent 会话、LLM 配置、备份恢复都是全局的。任何新增文档或 RAG 功能若沿用现状，会产生严重跨家庭泄露风险。

### 5. Agent 审计无法扩展

[capture_state()](backend/app/agent/state.py#L68-L80) 每次扫描全部业务表；确认时又对每个工具前后重复扫描。当前数据少时可用，扩展后会成为：

$$
O(\text{全库行数}\times\text{工具数})
$$

[undo_agent_operation()](backend/app/services/undo_service.py#L73-L139) 直接恢复历史行状态，且不验证这些行是否已被后续操作修改，可能覆盖新数据。

### 6. 同步长任务和单进程状态

- [价格刷新](backend/app/services/price_refresh_service.py#L104-L197) 在 HTTP 请求中同步执行。
- [Next.js 代理](frontend/next.config.ts#L5-L9) 因此被放宽到 300 秒。
- [登录限流](backend/app/core/rate_limit.py#L5-L36)、行情搜索缓存和 provider backoff 都只存在单进程内存中。
- Dashboard 发出多个请求，而 [portfolio_service](backend/app/services/portfolio_service.py#L57-L146) 每次重新加载完整持仓、价格和汇率。

### 7. 安全与运维风险

- [配置默认值](backend/app/core/config.py#L9-L31) 允许弱默认凭据。
- [数据恢复接口](backend/app/api/routes/data_management.py#L87-L134) 只要求已登录，没有管理员角色或 TOTP。
- [备份容器](docker-compose.yml#L45-L68) 将明文 SQL 保存到主机目录，无加密、异地副本或恢复演练。
- 每个 API 容器启动时都会执行 Alembic，见 [backend/Dockerfile](backend/Dockerfile#L16)，横向扩容会产生迁移竞争。
- 后端依赖使用宽松版本范围，没有锁文件；前端没有测试，后端只有依赖空数据库的脚本式 smoke test。

---

## 三、固定目标架构

### 1. PostgreSQL 是唯一 OLTP 和事件事实源

一条命令在同一事务中写入：

1. `transactions`
2. 复式 `journal_postings`
3. Transactional Outbox
4. Audit Event
5. `holdings` 同步投影

同步更新投影用于保证 read-your-writes；Celery 负责重放校验和异步衍生任务，而不是创造第二事实源。

### 2. ClickHouse 只是分析副本

通过 PostgreSQL Outbox 与 Celery 幂等同步；任何业务 API 都不得直接双写 PostgreSQL 和 ClickHouse。ClickHouse 必须可随时删除并从 PostgreSQL 重建。

### 3. 标准异步拓扑

- RabbitMQ：Celery broker。
- Redis：缓存、分布式限流、任务结果、锁和 Pub/Sub。
- Celery Beat：定时任务。
- WebSocket：任务和 Agent 过程实时推送。

### 4. RAG 技术选择

- 在 LangChain/LlamaIndex 两类方案中选择 **LlamaIndex** 负责 RAG 管线。
- 保留现有自定义 Agent Pending Confirmation 编排。
- 向量数据库使用 **PostgreSQL + pgvector**。
- Pinecone/Milvus 只保留适配接口和容量迁移标准，不在三个 Sprint 内部署。

### 5. 前端渲染策略

- 私有财富页面采用 Next.js/React Server Components + SSR。
- 私有数据禁止跨家庭缓存。
- ISR 只用于非敏感证券目录和市场日历。
- Client Components 继续承载表单、图表、WebSocket 和微交互。

### 6. 以 Family 为唯一顶层数据边界

数据层级：

```text
Family
├── Members（User）
├── Owners
├── Institutions
└── Accounts（同时引用 Owner 与 Institution）
    ├── Transactions（唯一事实来源）
    └── Holdings（可重放投影）
```

不创建额外的顶层组织表。`Family` 直接承担数据归属和访问隔离；`family_memberships` 连接 User 与 Family。Institution 是 Family 下的共享实体，Account 同时引用 Owner 与 Institution，避免同一银行被每个 Owner 重复创建。

---

# Sprint 1：可信 AI 文档录入闭环

## 主题与目标

交付“PDF/截图 → OCR/Vision → RAG 索引与结构化抽取 → Agent 待确认交易 → 事件账本”的 AI 演示，同时先关闭直接持仓写入、跨家庭泄露和无审计三条红线。

**对应蓝图：** 2、3、5、8、10、11。

## 1. Days 1–3：强制安全闸

### 数据库

新增：

- `families`
- `family_memberships`
- `journal_entries`
- `journal_postings`
- `audit_events`
- `outbox_events`

对以下现有数据增加 `family_id`：

- `owners`
- `institutions`
- `accounts`
- `instruments`
- `exposure_groups`
- `transactions`
- `holdings`
- `valuation_snapshots`
- `import_batches`
- `agent_sessions`
- `llm_provider_configs`
- `app_settings`

采用 expand → backfill 默认家庭 → 建索引 → 加 NOT NULL 的迁移顺序，不修改已有 0001–0009。

扩展 `transactions`：

- `event_version`
- `idempotency_key`
- `correlation_id`
- `causation_id`
- `created_by_user_id`
- `metadata_json`
- `reversal_of_id`
- 新事件类型：opening balance、reconciliation、tax、split、reverse split、merger、stock dividend。

扩展 `holdings`：

- `projection_version`
- `last_event_id`
- 数据库权限上不再允许普通 API 角色直接写。

### 服务和 API

- 统一引入 `RequestContext(user_id, family_id, role)`。
- JWT 的 `sub` 从用户名改为用户 UUID，并携带 `jti`、active family；仍需查询 membership，不能只相信 Token。
- `PUT /api/holdings` 和 `/api/holdings/adjust` 暂保兼容，但内部生成 reconciliation 事件。
- `DELETE /api/holdings/{id}` 废止。
- `DELETE /api/transactions/{id}` 只允许删除未提交草稿；已入账交易必须调用 reversal。
- `/api/holdings/from-market-search` 改为“创建资产 + opening balance 事件”原子命令。
- `/api/data/import/{batch_id}/commit` 改为单事务、每行幂等并生成事件。
- `update_transaction_metadata()` 改为产生 metadata-amended 事件，经济字段始终不可变。
- 买入、取款、换汇默认禁止隐式负现金；需要借款时必须使用显式负债/授信账户。

## 2. 文档中心和 RAG 管线 MVP

### 数据库

新增：

- `documents`：所属家庭、Owner、Institution、Account、类型、OSS key、SHA-256、状态。
- `document_versions`
- `document_pages`
- `document_chunks`
- `document_extractions`
- `document_links`
- `background_jobs`

启用 pgvector，并让 `document_chunks` 同时具备：

- PostgreSQL `tsvector` 全文索引。
- pgvector HNSW/cosine 索引。
- `family_id`、文档类型、日期、机构等 metadata filter。
- 页码与 bounding-box citation。

### OCR、Vision 和 RAG

RAG 管线：

1. 魔数、MIME、病毒和 PDF bomb 检查。
2. 文档分页。
3. OCR。
4. Vision 结构化提取。
5. Chunking。
6. Embedding。
7. pgvector + 全文索引。
8. Hybrid retrieval、重排和带页码引用回答。

Provider 设计：

- Tesseract：本地 fallback。
- AWS Textract、Azure Form Recognizer：标准 OCR adapter。
- 阿里云生产默认可接阿里云 OCR。
- Vision API 使用 GPT-4V/当前 GPT-4o 兼容模型识别 Fidelity 等 App 截图。
- LlamaIndex 负责 ingestion/retrieval，不同时引入 LangChain，避免双重抽象。

### 新接口

```text
POST /api/v1/documents/upload-intents
POST /api/v1/documents/{id}/complete
GET  /api/v1/documents
GET  /api/v1/documents/{id}
POST /api/v1/documents/{id}/reprocess
POST /api/v1/knowledge/search
POST /api/v1/knowledge/query
GET  /api/v1/jobs/{id}
WS   /api/v1/ws/jobs/{job_id}
```

### Agent 扩展

新增工具：

- `search_documents`
- `retrieve_document_chunks`
- `draft_transactions_from_document`
- `create_price_snapshot`

保留蓝图中的语义工具名，但修正底层行为：

- `update_holding` → 创建 reconciliation event。
- `delete_transaction` → 创建 reversal，不做物理删除。
- 所有文档抽取结果必须显示置信度和来源页。
- 低置信度及全部写操作继续进入 `AgentPendingAction`，禁止 OCR 自动落账。

`AgentPendingAction` 改为只保存受影响聚合的 expected version，不再全库扫描；`AgentOperationLog` 保存事件 ID 和脱敏摘要。

## 3. 基础设施

本地 Compose 增加：

- pgvector PostgreSQL 镜像。
- Redis 缓存。
- RabbitMQ。
- Celery worker。
- ClamAV。
- MinIO 作为 OSS 模拟。

生产采用：

- 阿里云 OSS 私有 Bucket、SSE-KMS。
- 阿里云 KMS Secrets Manager。
- API 网关 + WAF。
- 阿里云函数计算执行弹性 OCR/Vision 页面任务。
- 定义腾讯云 SCF Serverless adapter 与一致性测试，但不做双云生产部署。

Redis 同时承载：

- 分布式限流。
- Job 状态。
- WebSocket Pub/Sub。
- 幂等锁。
- 短期检索缓存。

## 4. 前端

- 新增文档上传、处理队列、页级预览、抽取字段和交易草案界面。
- Agent 由最长 300 秒阻塞请求改为 Job + WebSocket。
- 使用 TailwindCSS/Shadcn UI。
- 上传、OCR、Vision、索引阶段提供 UI/UX 微交互。
- 抽取摘要 → 详细字段 → 原始页采用渐进式披露。
- 移动端优先响应式设计。

## 5. 从第一天执行的安全措施

- 所有查询必须带 family scope，并有跨家庭 IDOR 测试。
- 新增 append-only 全局审计，而非只审计 Agent。
- 管理员角色才能恢复备份或配置 LLM。
- 增加 CSRF Token/Origin 校验。
- 新敏感字段使用 KMS envelope encryption + AES-256-GCM。
- 当前 Fernet 仅作旧数据只读兼容，Sprint 3 完成迁移。
- OSS 对象永不公开，下载 URL 短期有效。
- 日志禁止记录文档正文、OAuth Token、API Key 和完整账号。

## 6. 工作量

| 角色      | 人日 | 内容                                                 |
| --------- | ---: | ---------------------------------------------------- |
| 全栈      |   10 | 家庭隔离/事件兼容 6，文档 UI 3，测试 1               |
| AI/数据   |   10 | OCR/Vision/RAG 7，Agent 集成 2，评测 1               |
| DevOps/QA |   10 | Redis/RabbitMQ/Celery/OSS/函数计算 6，安全/CI/测试 4 |

## 7. Sprint 1 DoD

- 两个 Family 的 API、Agent、文档、日志、LLM 配置互不可见。
- 全量重放前后持仓 checksum 一致。
- 每个 Journal Entry 按币种借贷和为零。
- 导入中途失败无半提交。
- 支持样例 PDF/截图在 60 秒内产生带引用的交易草案。
- 确认后写事件、postings、audit；取消后业务数据零变化。

---

# Sprint 2：市场数据、ClickHouse 分析和新仪表盘

## 主题与目标

建立自动市场数据与分析读模型，交付收益、归因、基准、风险和穿透敞口第一版。

**对应蓝图：** 1、4、6、7、9。

## 1. 资产和市场数据模型

扩展 `Instrument`：

- 定存、贵金属、收藏品、保险现金价值、养老金、VC、PE、RSU、期权。
- 新增 `instrument_type`。
- 增加 issuer、sector、industry、ISIN/CUSIP、maturity、coupon、underlying、strike、expiry、vesting、liquidity、valuation method 等类型化字段。

新增：

- `instrument_identifiers`
- `market_price_bars`
- `corporate_actions`
- `dividend_events`
- `benchmark_series`
- `market_data_runs`
- `position_snapshots`
- `position_lots`
- `exposure_nodes`
- `instrument_exposure_weights`

将现有单个 `exposure_group_id` 迁移为多权重关系，从而表达 SPY、VOO、IVV 的共同 S&P 500 敞口以及基金成分穿透。

为价格和汇率增加 provider + timestamp 幂等唯一键；生产环境不再把 seed placeholder 当作有效最新汇率。

## 2. 异步市场刷新和自动化

- `POST /api/v1/market-data/refresh-jobs` 返回 `202 + job_id`。
- 原 `/api/portfolio/refresh` 成为兼容代理。
- Celery 处理最新价、历史价格、FX、股息、公司事件和每日估值。
- RabbitMQ 配置 retry、dead-letter queue。
- Celery Beat 每日刷新价格和汇率、生成快照，并建立月底报告任务骨架。
- WebSocket 推送刷新进度和完成事件。

Redis 缓存：

- latest price/FX。
- 市场搜索结果。
- Portfolio aggregate。
- Dashboard BFF。
- Provider backoff。
- 分布式登录与行情限流。

缓存键必须包含 family、base currency 和 data version，事件提交后精准失效。

## 3. ClickHouse 分析读模型

新增 ClickHouse 表：

- `fact_transaction_events`
- `fact_cashflows`
- `fact_position_daily`
- `fact_valuation_daily`
- `fact_market_prices`
- Owner、Institution、Account、Instrument 维表

同步原则：

- PostgreSQL `outbox_events` → Celery 幂等消费 → ClickHouse。
- 每条事件携带 family、event version 和 idempotency key。
- 每日核对事件数、金额、持仓 checksum。
- ClickHouse 故障不得阻止 PostgreSQL 交易提交。

新增接口：

```text
GET /api/v1/analytics/allocation
GET /api/v1/analytics/performance
GET /api/v1/analytics/attribution
GET /api/v1/analytics/benchmarks
GET /api/v1/analytics/risk
GET /api/v1/analytics/exposures
GET /api/v1/analytics/cash-flows
GET /api/v1/analytics/dashboard
```

P0 指标：

- 日、周、月、YTD、1 年、成立以来。
- TWR、XIRR。
- S&P 500 基准。
- 价格、股息、FX 归因。
- 波动率、最大回撤、HHI 集中度。
- 穿透式敞口。

## 4. 仪表盘和前端架构

当前 [Dashboard](<frontend/src/app/(app)/dashboard/page.tsx#L23-L50>) 是纯 Client Component 并发出多个组合请求。调整为：

- Next.js/React Server Components 负责私有首屏。
- SSR 使用 `force-dynamic`，不允许共享缓存。
- ISR 只用于公共证券目录和市场日历。
- React Query 负责水合后的交互更新。
- 一个 `/analytics/dashboard` 组合端点替代多次全组合聚合。

图表：

- 保留 Recharts：净值折线、简单饼图。
- 引入 ECharts：旭日图、桑基图、热力图。
- D3.js 只用于后续自定义穿透网络图，避免同一图表重复使用多个引擎。

首页增加：

- 净资产。
- 当日盈亏。
- 资产配置。
- 涨跌榜。
- 现金流。
- 近期事件。
- AI 洞察占位。

继续采用 TailwindCSS/Shadcn UI、骨架屏、数值过渡、任务完成微交互、渐进式披露和移动端优先布局。

## 5. 性能修复

- 交易 summary 下推 SQL/ClickHouse，不再加载全部筛选行。
- 增加 `(family_id, account_id, trade_date, created_at)` 等复合索引。
- 聚合缓存命中 p95 目标小于 300ms。
- 未命中分析查询 p95 目标小于 1.5s。
- OpenTelemetry + 阿里云 ARMS/SLS 监控任务积压、provider 失败、缓存命中率和 WebSocket。

## 6. 工作量

| 角色      | 人日 | 内容                                                  |
| --------- | ---: | ----------------------------------------------------- |
| 全栈      |   10 | 模型/API 4，RSC/高级图表 5，测试 1                    |
| AI/数据   |   10 | ClickHouse/Outbox 6，收益/敞口/风险 3，对账 1         |
| DevOps/QA |   10 | Beat/Redis/WebSocket 4，ClickHouse/观测 3，性能回归 3 |

## 7. Sprint 2 DoD

- 手动与定时刷新均异步返回 Job。
- PostgreSQL 与 ClickHouse 日终金额误差不超过 0.01。
- Dashboard 支持至少八个配置维度、YTD/1Y/成立以来、S&P 500 对比和基础归因/风险。
- 断线重连后 WebSocket 能恢复任务状态。
- 私有 SSR 不发生跨用户缓存。

---

# Sprint 3：家庭知识 Agent、自动化与企业安全

## 主题与目标

将文档 RAG 与分析能力升级为可引用、可执行、可记忆的家庭办公室 Agent，并完成身份、密钥和灾备安全闭环。

**对应蓝图：** 5、6、7、8、9、10、11。

## 1. 家庭知识库与 AI 记忆

新增：

- `knowledge_collections`
- `investment_policies`
- `meeting_notes`
- `ai_memories`
- `rag_feedback`

AI Memory 必须：

- 有明确来源和 family/member scope。
- 保存置信度、有效期和创建原因。
- 经过用户显式同意。
- 可查看、编辑和删除。
- 不允许模型静默学习成永久事实。

RAG 增强：

- Hybrid retrieval。
- Metadata ACL。
- Reranker。
- Query decomposition。
- 逐句 document/page citation。
- pgvector 继续作为生产向量数据库。
- Pinecone/Milvus 仅定义容量迁移接口。

新增确定性 Agent 工具：

- `get_allocation`
- `get_performance`
- `explain_net_worth_change`
- `find_duplicate_exposures`
- `run_stress_scenario`
- `search_family_knowledge`
- `create_reminder`

“标普 500 跌 20%”必须由分析服务计算，LLM 只负责理解问题和解释结果。

Agent 会话与工具状态通过 WebSocket 流式推送；会话改为摘要和检索记忆，不再每轮重传完整历史。

## 2. 自动化与报告

新增：

- `reminders`
- `automation_rules`
- `report_runs`
- `notification_deliveries`

Celery Beat 自动执行：

- 每日价格与汇率刷新。
- 每日资产快照。
- 月底绩效 PDF。
- 股息到账提醒。
- 保险续费提醒。
- 债券到期提醒。

报告保存至 OSS，并自动进入文档中心与 RAG 索引。通知先实现站内 + WebSocket，邮件/SMS 保留 provider 接口。

## 3. JWT、OAuth2、2FA/TOTP 与 API Key

身份体系：

- 15 分钟 JWT access token。
- 旋转 refresh token，数据库只存 hash。
- Device/session 撤销。
- Refresh token reuse detection。
- CSRF 防护。
- RBAC 和 step-up authorization。

实现：

- 2FA/TOTP enrollment。
- TOTP secret 以 AES-256-GCM 加密。
- Recovery code 只存 hash。
- 备份恢复、LLM 配置、API Key、OAuth2、导出等高风险操作强制 TOTP。

OAuth2：

- PKCE、state、callback、token refresh。
- 加密 credential vault。
- 为 HSBC、招商银行、Morgan Stanley、Fidelity、Schwab、IBKR、Coinbase 定义统一连接器接口。
- 本 Sprint 只交付 sandbox connector，不承诺真实机构生产接入。

API Key 管理：

- 创建时仅显示一次。
- 数据库只存 hash 与 prefix。
- 支持 scope、family、过期时间、IP allowlist、rotation 和 last-used。
- API 网关执行限流配额。

## 4. AES-256、Secrets 与灾备

- 将 LLM Key、OAuth Token、敏感账户字段从 Fernet 迁移到 KMS envelope encryption + AES-256-GCM。
- 每条密文记录 `key_version`，支持在线密钥轮换。
- 生产 Secrets 全部进入阿里云 KMS Secrets Manager。
- PostgreSQL family-owned 表启用 RLS。
- API、Celery、Migration 使用不同的最小权限数据库角色。
- 审计日志使用 hash chain，并归档到不可变对象存储。
- 明文主机备份改为 AES-256 加密 OSS 备份、版本化、Object Lock 和跨区域复制。
- 每月自动执行隔离恢复演练。

生产拓扑：

```text
API 网关/WAF
    ├── Next.js
    └── FastAPI
          ├── RDS PostgreSQL + pgvector
          ├── Redis
          ├── RabbitMQ / Celery
          ├── ClickHouse
          ├── OSS
          └── KMS Secrets Manager

OSS Event / API 网关
    └── 阿里云函数计算：OCR / Vision 页面处理
```

腾讯云 SCF 保留 Serverless adapter 和 conformance test。

## 5. 前端

- 文档中心支持条件筛选、全文搜索、自然语言搜索和页级 citation viewer。
- AI 洞察卡可展开数据来源、计算口径和工具调用。
- 增加 TOTP、设备会话、API Key、OAuth2 连接和自动化规则页面。
- 高风险操作分步确认。
- 移动端优先，支持键盘、ARIA 和 reduced-motion。

## 6. 工作量

| 角色      | 人日 | 内容                                                         |
| --------- | ---: | ------------------------------------------------------------ |
| 全栈      |   10 | 知识/安全/自动化 API 与 UI 8，测试 2                         |
| AI/数据   |   10 | 高级 RAG、分析工具、记忆和评测                               |
| DevOps/QA |   10 | JWT/2FA/RLS/KMS/API 网关/备份/Serverless 7，安全与灾备演练 3 |

## 7. Sprint 3 DoD

- “美元资产占比、近一年收益最高、净值为何下跌、重复配置、标普跌 20%”五类问题均调用确定性数据工具并给出来源。
- RAG Recall@5 至少 85%，citation precision 至少 90%。
- 跨 Family 文档、向量和分析查询零泄露。
- Prompt injection 无法越权或绕过 Pending Confirmation。
- TOTP 和 step-up 覆盖全部高风险操作。
- 加密备份可在隔离环境完整恢复。

---

## 四、关键现有文件与修改方向

| 现有文件                                                                                         | 修改方向                                                                                  |
| ------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------- |
| [backend/app/models/transaction.py](backend/app/models/transaction.py)                           | 升级为不可变事件头，增加 family、idempotency、correlation、causation、reversal 和审计字段 |
| [backend/app/models/holding.py](backend/app/models/holding.py)                                   | 收敛为只读投影，增加 projection version 和 last event                                     |
| [backend/app/services/transaction_service.py](backend/app/services/transaction_service.py)       | 统一命令、postings、outbox、audit、reversal；处理全部持仓变化                             |
| [backend/app/services/holding_service.py](backend/app/services/holding_service.py)               | 移除公共直接写语义，只保留 projector 内部实现                                             |
| [backend/app/services/import_service.py](backend/app/services/import_service.py)                 | 改为原子、幂等、按行生成 opening/reconciliation events                                    |
| [backend/app/services/portfolio_service.py](backend/app/services/portfolio_service.py)           | 增加 Family Scope，随后由 Redis/ClickHouse 分析查询替换全量 Python 聚合                   |
| [backend/app/services/price_refresh_service.py](backend/app/services/price_refresh_service.py)   | 拆为 Celery 任务，增加历史价格、公司事件、状态和缓存失效                                  |
| [backend/app/agent/agent.py](backend/app/agent/agent.py)                                         | 从全库 state diff 改为聚合版本、RAG citation、Job/WebSocket                               |
| [backend/app/agent/tools.py](backend/app/agent/tools.py)                                         | 移除直接持仓和物理删除权限，增加文档、分析、压力测试、提醒工具                            |
| [backend/app/agent/extraction.py](backend/app/agent/extraction.py)                               | 演进为持久化异步 OCR/Vision Provider 管线                                                 |
| [backend/app/services/undo_service.py](backend/app/services/undo_service.py)                     | 金融撤销改为补偿事件；非金融恢复加入乐观版本检查                                          |
| [backend/app/api/deps.py](backend/app/api/deps.py)                                               | 提供 RequestContext、Family Membership、RBAC 依赖                                         |
| [backend/app/core/security.py](backend/app/core/security.py)                                     | JWT refresh、CSRF、2FA/TOTP、API Key 和 OAuth2 安全能力                                   |
| [backend/app/api/routes/holdings.py](backend/app/api/routes/holdings.py)                         | 兼容路由改为 opening/reconciliation 事件，移除直接删除                                    |
| [backend/app/api/routes/transactions.py](backend/app/api/routes/transactions.py)                 | 采用不可变交易语义和 reversal；扩展税、公司事件                                           |
| [backend/app/api/routes/portfolio.py](backend/app/api/routes/portfolio.py)                       | 同步刷新迁移为异步 Job；聚合迁移至 Analytics API                                          |
| [backend/app/api/routes/agent.py](backend/app/api/routes/agent.py)                               | 增加异步 Agent Job、WebSocket、RAG 引用和 Family Scope                                    |
| [backend/app/api/routes/data_management.py](backend/app/api/routes/data_management.py)           | 权限化导入、导出和恢复；高风险操作要求 TOTP                                               |
| [backend/alembic/versions](backend/alembic/versions)                                             | 新增 expand/backfill/constraint 多步迁移，不修改既有迁移                                  |
| [frontend/src/app/(app)/dashboard/page.tsx](<frontend/src/app/(app)/dashboard/page.tsx>)         | RSC/SSR data shell、Analytics BFF、高级图表                                               |
| [frontend/src/app/(app)/assets/page.tsx](<frontend/src/app/(app)/assets/page.tsx>)               | 收益、风险、归因和多层穿透分析                                                            |
| [frontend/src/app/(app)/accounts/page.tsx](<frontend/src/app/(app)/accounts/page.tsx>)           | opening/reconciliation 事件 UX，统一 Owner/Institution/Account 管理                       |
| [frontend/src/components/add-holding-dialog.tsx](frontend/src/components/add-holding-dialog.tsx) | 删除直接持仓写入口，改为 opening balance 或交易草案                                       |
| [frontend/src/app/(app)/transactions/page.tsx](<frontend/src/app/(app)/transactions/page.tsx>)   | 禁止物理删除，增加事件类型、lot、公司事件和 reversal UX                                   |
| [frontend/src/app/(app)/agent/page.tsx](<frontend/src/app/(app)/agent/page.tsx>)                 | Job/WebSocket、RAG citation、流式工具状态和确认卡                                         |
| [frontend/src/app/(app)/data/page.tsx](<frontend/src/app/(app)/data/page.tsx>)                   | 拆分文档中心、安全审计、权限化备份恢复                                                    |
| [frontend/src/lib/types.ts](frontend/src/lib/types.ts)                                           | 由 OpenAPI 生成的 TypeScript Client 替换手写 DTO                                          |
| [frontend/src/lib/api.ts](frontend/src/lib/api.ts)                                               | 增加 token refresh、CSRF、Job 和 WebSocket client                                         |
| [docker-compose.yml](docker-compose.yml)                                                         | 增加 Redis、RabbitMQ、Celery、ClickHouse、本地对象存储和独立 Migration Job                |
| [backend/Dockerfile](backend/Dockerfile)                                                         | 非 root、多阶段构建；移除 API 启动时自动迁移                                              |
| [frontend/Dockerfile](frontend/Dockerfile)                                                       | 多阶段镜像、非 root、生产健康检查                                                         |

---

## 五、统一验证与发布门槛

### 1. 自动化测试

将现有 smoke 脚本迁移为 pytest + Testcontainers，并增加：

- 事件 replay/property tests。
- 每币种借贷平衡测试。
- Transfer/FX linked events。
- 幂等重试。
- 并发投影。
- RLS/IDOR。
- Agent confirmation/reversal。
- OCR/RAG ACL。

前端增加：

- Vitest。
- React Testing Library。
- Playwright。
- 375px、768px、桌面端视口。
- 上传、WebSocket、2FA 和关键交易流程。

### 2. 契约管理

- 使用 FastAPI OpenAPI 生成 TypeScript Client。
- CI 阻止未重新生成客户端的 API 变更。
- CI 检查 SQLAlchemy Model 与 Alembic Migration 是否一致。
- 每个迁移验证 upgrade、downgrade 和从现有生产副本升级。

### 3. CI/CD

流水线包含：

- lint。
- typecheck。
- unit/integration tests。
- 安全扫描。
- SBOM。
- 依赖与镜像漏洞扫描。
- Shadow Database 迁移演练。
- Canary API/Worker 发布。

### 4. 财务对账

每次部署前验证：

- Ledger postings 每币种平衡。
- Holdings replay checksum。
- PostgreSQL ↔ ClickHouse 日终对账。
- 估值汇率来源。
- stale price/FX 告警。

### 5. SLO 与监控

监控并告警：

- API p95。
- Celery queue lag。
- RAG latency/cost。
- OCR failure rate。
- 市场数据 Provider availability。
- Redis cache hit rate。
- WebSocket delivery。
- Backup age。
- Restore drill status。

---

## 六、决策与范围边界

- AI 演示可与安全闸并行开发，但不得在绕过账本或 Family Scope 的前提下合并。
- PostgreSQL 始终是唯一事实源；ClickHouse 可随时删除重建。
- 前三个 Sprint 只使用 pgvector，不部署 Pinecone/Milvus。
- 使用 LlamaIndex，不同时引入 LangChain。
- 私有组合页面使用 RSC + SSR；ISR 只用于公共参考数据。
- 不在三个 Sprint 内交付真实银行或券商生产连接，仅交付 OAuth2/连接器框架和 sandbox。
- 不实现无确认自动落账、高频交易、原生移动 App、多区域双活或完整税务/遗产规划。
- 在当前 3 人容量下，这是偏激进但可落地的 P0 路线；任何新增真实机构连接或第二个生产 OCR 供应商都应置换现有范围，而不是追加。

---

## 七、三 Sprint 总览

| Sprint   | 核心交付                                                                       | 主要技术                                                                                                                        | 人日 |
| -------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------- | ---: |
| Sprint 1 | 家庭隔离、事件安全闸、复式 postings、文档中心、OCR/Vision、RAG、Agent 交易草案 | PostgreSQL、pgvector、Redis、RabbitMQ、Celery、LlamaIndex、Tesseract/Textract/Form Recognizer、GPT-4V、OSS、函数计算、WebSocket |   30 |
| Sprint 2 | 市场数据自动化、ClickHouse 分析、收益/归因/风险/基准/敞口、新仪表盘            | ClickHouse、Celery Beat、Redis 缓存、Outbox、Recharts、ECharts、D3.js、RSC、SSR/ISR                                             |   30 |
| Sprint 3 | 家庭知识 Agent、AI 记忆、自动报告提醒、JWT/OAuth2/2FA/API Key、AES-256、灾备   | RAG 管线、pgvector、JWT、OAuth2、2FA/TOTP、AES-256-GCM、KMS Secrets、API 网关、RLS、OSS Object Lock、Serverless                 |   30 |

**总工作量：约 90 人日，历时 6 周。**
