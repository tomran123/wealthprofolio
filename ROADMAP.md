# WealthPortfolio — Phase 2–5 Implementation Plan

> Phase 1 (基础数据库 + 跨账户聚合) 已完成。本文档描述后续四个阶段的详细实施计划，作为开发路线图和上下文参考。

---

## Phase 2 — 价格刷新引擎 (Price Refresh Engine)

**前置条件**：Phase 1 模型（Instrument、Holding、PriceSnapshot、FXRateSnapshot）已存在。

### 目标
用户点击一次"Refresh All Prices"，系统自动获取所有上市资产的最新报价，换算为家庭基准币种，重新计算总资产，并保存历史快照。

---

### 2.1 后端：行情适配器层

新建 `backend/app/providers/price/` 目录，每个适配器实现同一接口：

```python
class PriceResult(BaseModel):
    symbol: str
    price: Decimal
    currency: str
    as_of: datetime
    source_provider: str
    quote_status: QuoteStatus   # realtime | delayed | close | manual | fixed

class PriceProviderAdapter(Protocol):
    async def fetch_prices(self, symbols: list[str]) -> list[PriceResult]: ...
    async def can_handle(self, instrument: Instrument) -> bool: ...
```

| 适配器文件 | 覆盖资产类型 | 数据源 | Key 需要？ |
|---|---|---|---|
| `yahoo_adapter.py` | 美股、港股、ETF、美国公募基金 | yfinance / Yahoo Finance v8 API | 否 |
| `akshare_adapter.py` | A 股、沪深 ETF、国内公募基金 NAV | akshare | 否 |
| `coingecko_adapter.py` | 加密货币 | CoinGecko public API | 否（限速 30 次/分） |
| `metals_adapter.py` | 黄金、白银、铂金等贵金属 | metals-api 免费层 或 Yahoo `GC=F` 期货 proxy | 否（fallback Yahoo） |
| `manual_adapter.py` | 房产、私募、非上市资产 | 无请求；保留最近一次 PriceSnapshot | N/A |

FX 适配器独立：

| 文件 | 数据源 | 频率 |
|---|---|---|
| `providers/fx/frankfurter_adapter.py` | Frankfurter.app（ECB 汇率，无需 Key） | 每日更新，请求当日最新 |

**路由逻辑**（`price_router.py`）：根据 `Instrument.market` 和 `Instrument.asset_class` 分配适配器：

```
market=US or HK  →  yahoo_adapter
market=CN, asset_class=equity/etf  →  akshare_adapter (东方财富/新浪行情)
asset_class=fund, market=CN  →  akshare_adapter (天天基金 NAV)
asset_class=crypto  →  coingecko_adapter
asset_class=gold (commodity)  →  metals_adapter 或 yahoo_adapter (GC=F)
price_source_type=manual  →  manual_adapter (skip, keep last)
price_source_type=fx_derived or fixed_principal  →  skip (仅刷新汇率)
```

---

### 2.2 后端：刷新编排器

新建 `backend/app/services/price_refresh_service.py`：

```python
MAX_CONCURRENCY = 10   # asyncio.Semaphore

async def refresh_all_prices(db: AsyncSession) -> RefreshResult:
    instruments = await load_instruments_needing_refresh(db)
    groups = route_to_adapters(instruments)          # dict[adapter, list[Instrument]]
    
    async with asyncio.TaskGroup() as tg:
        for adapter, group in groups.items():
            tg.create_task(fetch_and_save(db, adapter, group, sem))
    
    # FX 独立刷新
    currencies_needed = await collect_portfolio_currencies(db)
    await refresh_fx_rates(db, currencies_needed)
    
    # 重新计算并保存快照
    snapshot = await portfolio_service.create_valuation_snapshot(db)
    return RefreshResult(success=..., kept=..., failed=..., snapshot_id=snapshot.id)
```

- **部分失败容错**：单个资产抓取失败 → 记录错误、保留上次 PriceSnapshot、继续其他资产
- **并发限制**：用 `asyncio.Semaphore(MAX_CONCURRENCY)` 防止对免费 API 过度并发
- **结果格式**：`RefreshResult(success_count, kept_count, failed_count, failed_symbols)`

---

### 2.3 后端：ValuationSnapshot 模型

新增 `ValuationSnapshot` 模型（Alembic migration `0003`）：

```sql
valuation_snapshots (
  id UUID PK,
  created_at TIMESTAMPTZ,
  base_currency VARCHAR(3),
  total_assets NUMERIC(24,2),
  total_liabilities NUMERIC(24,2),
  net_worth NUMERIC(24,2),
  allocation_json JSONB,   -- breakdowns by all 8 dimensions
  refresh_result_json JSONB  -- success/kept/failed counts
)
```

---

### 2.4 后端：新增 API 端点

```
POST  /api/portfolio/refresh          → 触发刷新，返回 RefreshResult
GET   /api/portfolio/snapshots        → 历史快照列表（分页）
GET   /api/portfolio/snapshots/latest → 最近一次快照
GET   /api/instruments/{id}/price-history  → (已有，Phase 1 实现)
```

---

### 2.5 前端更新

**Dashboard 页**：
- 顶部工具栏增加 `Refresh All Prices` 按钮（loading 状态），刷新完成后自动重新 fetch summary + aggregate
- 刷新结果 toast：`成功更新 86 项 · 保持原价 7 项 · 失败 3 项`
- 增加最后刷新时间戳显示
- Net Worth 历史折线图（recharts LineChart）：从 `ValuationSnapshot` 拉取时间序列数据

**Assets 页**：
- 每个资产 group 详情行展示价格来源 Badge：
  - `实时` (green) / `延迟` (yellow) / `收盘价` (gray) / `人工估值` (orange)
  - 附报价时间：`2026-07-21 15:42`
- 价格过期警告（距上次报价 > 24h）

---

### 2.6 新增 Python 依赖

```
yfinance>=0.2.54
akshare>=1.14.0
httpx>=0.28      # 已有，用于 coingecko/frankfurter
```

`requirements.txt` 相应更新。

---

### Phase 2 交付物

> 用户点击一次按钮，系统自动从 Yahoo/akshare/CoinGecko/Frankfurter 获取最新报价和汇率，换算成基准币种，重新计算总资产，Dashboard 实时更新，净值历史曲线开始积累数据。

---

---

## Phase 3 — 交易账本 (Transaction Ledger)

**前置条件**：Phase 1 服务层（Holding、Instrument、Account）；Phase 2 价格服务（用于实时估值）。

### 目标
系统记录每一笔导致持仓和现金变化的操作，事务性地保持 `holdings` 表与交易历史一致。

---

### 3.1 交易类型定义

```python
class TransactionType(str, Enum):
    BUY = "buy"
    SELL = "sell"
    DEPOSIT = "deposit"          # 现金存入
    WITHDRAW = "withdraw"        # 现金取出
    TRANSFER_IN = "transfer_in"  # 从另一账户转入
    TRANSFER_OUT = "transfer_out"
    FX_EXCHANGE = "fx_exchange"  # 换汇
    DIVIDEND = "dividend"        # 股息/分红
    INTEREST = "interest"        # 利息
    FEE = "fee"                  # 手续费
    MANUAL_ADJUSTMENT = "manual_adjustment"
    VALUATION_UPDATE = "valuation_update"  # 人工估值变更记录
```

---

### 3.2 Transaction 模型（Alembic migration `0004`）

```sql
transactions (
  id UUID PK,
  created_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ,
  account_id UUID FK → accounts,
  instrument_id UUID FK → instruments NULLABLE,   -- NULL for cash-only ops
  transaction_type VARCHAR(30),
  quantity NUMERIC(24,6),             -- + for in, - for out (stock/bond)
  price NUMERIC(24,6) NULLABLE,       -- per-unit price
  currency VARCHAR(3),
  amount NUMERIC(24,2),               -- total cash impact
  fee NUMERIC(24,6) DEFAULT 0,
  fee_currency VARCHAR(3),
  trade_date DATE,
  settlement_date DATE NULLABLE,
  external_ref VARCHAR(100) NULLABLE, -- broker reference
  linked_transaction_id UUID NULLABLE, -- transfer counterpart / reversal link
  note TEXT NULLABLE,
  source VARCHAR(20),                 -- manual | import | agent | screenshot
  is_reversed BOOLEAN DEFAULT false,
  reversed_by_id UUID NULLABLE
)
```

---

### 3.3 TransactionService

`backend/app/services/transaction_service.py`：

每种交易类型对应一个方法，每个方法在单一 `AsyncSession` 事务中同时写入：
1. `transactions` 行
2. `holdings` 行（upsert，增加或减少 quantity）
3. 现金工具的 `holdings` 行（如有影响）

**关键方法**：

```python
async def create_buy_transaction(db, account_id, instrument_id, quantity, price, currency, fee, trade_date) → Transaction
async def create_sell_transaction(db, ...) → Transaction
async def create_transfer(db, from_account_id, to_account_id, instrument_id, quantity, ...) → tuple[Transaction, Transaction]
async def create_currency_exchange(db, account_id, from_currency, from_amount, to_currency, to_amount, rate, fee, ...) → Transaction
async def create_income_transaction(db, account_id, instrument_id, amount, currency, tx_type, ...) → Transaction
async def create_fee_transaction(db, account_id, amount, currency, ...) → Transaction
async def delete_transaction(db, transaction_id) → None      # 物理删除 + 反向调整 Holding
async def reverse_transaction(db, transaction_id) → Transaction  # 创建冲销交易
async def recalculate_holdings_from_ledger(db, account_id) → None  # 从零重建 Holding
```

---

### 3.4 新增 API 端点

```
GET   /api/transactions                     → 列表（分页 + 过滤：account/type/date/instrument）
POST  /api/transactions/buy                 → 买入
POST  /api/transactions/sell                → 卖出
POST  /api/transactions/transfer            → 内部转账
POST  /api/transactions/fx-exchange         → 换汇
POST  /api/transactions/income              → 分红/利息
POST  /api/transactions/fee                 → 手续费
DELETE /api/transactions/{id}               → 删除（附带 Holding 回滚）
POST  /api/transactions/{id}/reverse        → 冲销
POST  /api/portfolio/recalculate            → 从 Transaction 重建所有 Holding
```

---

### 3.5 前端：Transactions 页

路由：`/transactions`（加入 AppShell nav）

功能：
- 可筛选账本表格：按账户、类型、日期范围、资产过滤
- 表格列：日期 | 账户 | 类型 | 资产 | 数量 | 价格 | 金额 | 货币 | 手续费 | 备注 | 来源
- 表格行操作：删除 / 冲销（确认 Dialog）
- 快速新建交易 Dialog（支持全部类型，字段按类型动态显示）
- 汇总栏：当前筛选范围内的总买入 / 卖出 / 净现金流

---

### Phase 3 交付物

> 所有买卖、转账、换汇、分红、利息、手续费操作原子性地更新持仓和现金；Transactions 页面完整展示账本。

---

---

## Phase 4 — AI Agent

**前置条件**：Phase 1–3 服务层全部存在（Agent 工具调用这些服务）。

### 目标
AI Agent 通过自然语言、截图、照片、文件，直接在数据库层面创建/修改/删除资产、持仓和交易，支持中文复杂金融语境。

---

### 4.1 LLM 供应商抽象层

`backend/app/providers/llm/`：

```
providers/llm/
  client.py          # 统一 async LLM client（openai SDK + per-provider base_url）
  models.py          # LLMProviderConfig DB 模型
  registry.py        # 从 DB 读取激活的 chat/vision 供应商配置
```

**`LLMProviderConfig` 模型**（Alembic migration `0005`）：

```sql
llm_provider_configs (
  id UUID PK,
  name VARCHAR(60),           -- 显示名
  provider_key VARCHAR(30),   -- openai | minimax | deepseek | seed
  role VARCHAR(10),           -- chat | vision
  base_url VARCHAR(300),      -- 覆盖默认 endpoint
  api_key_encrypted TEXT,     -- Fernet 加密（server secret via env var LLM_ENCRYPTION_KEY）
  model_name VARCHAR(80),
  is_active BOOLEAN,
  created_at, updated_at
)
```

**支持供应商**（均兼容 OpenAI `/chat/completions` 接口）：

| 供应商 | Role | 默认 base_url |
|---|---|---|
| OpenAI | chat + vision | `https://api.openai.com/v1` |
| MiniMax | chat + vision | `https://api.minimax.chat/v1` |
| DeepSeek | chat（无 vision） | `https://api.deepseek.com/v1` |
| Seed (Doubao) | chat + vision | `https://ark.cn-beijing.volces.com/api/v3` |

Vision 角色独立配置：用户可选"聊天用 DeepSeek，识图用 GPT-4o"。

---

### 4.2 工具调度器 (Tool Dispatcher)

`backend/app/agent/tools.py`：将 Phase 1–3 服务方法包装为 OpenAI function-calling schema。

**全部 22 个工具**（均调用已有服务，无裸 SQL）：

```python
# 查询类
search_owner(query: str)
search_institution(query: str)
search_account(query: str)
search_instrument(query: str)

# 持仓管理
get_holdings(account_id: str | None, instrument_id: str | None)
set_holding_snapshot(account_id, instrument_id, quantity)
adjust_holding(account_id, instrument_id, delta_quantity)

# 账户/资产创建
create_account(name, institution_id, owner_id, account_type, base_currency)
create_instrument(name, symbol, asset_class, currency, price_source_type)
update_instrument(instrument_id, **fields)

# 交易（调用 Phase 3 TransactionService）
create_buy_transaction(account_id, instrument_id, quantity, price, currency, fee, trade_date)
create_sell_transaction(...)
create_transfer(from_account_id, to_account_id, instrument_id, quantity)
create_currency_exchange(account_id, from_currency, from_amount, to_currency, to_amount, rate, fee)
create_income_transaction(account_id, instrument_id, amount, currency, tx_type)  # dividend | interest
create_fee_transaction(account_id, amount, currency)

# 现金 / 估值
set_cash_balance(account_id, currency_instrument_id, balance)
set_manual_valuation(instrument_id, price, currency, as_of, note)

# 修正
delete_transaction(transaction_id)
reverse_transaction(transaction_id)

# 价格刷新 & 重算（调用 Phase 2/3 服务）
refresh_market_prices()
recalculate_portfolio()
create_valuation_snapshot()
```

---

### 4.3 Agent 对话后端

`backend/app/agent/agent.py`：

```python
async def run_agent_turn(
    db: AsyncSession,
    messages: list[ChatMessage],
    uploaded_files: list[UploadedFile] | None = None,
) -> AgentTurnResult:
    # 1. 如有上传文件 → 调 vision model 提取结构化数据
    # 2. 将结构化数据注入 messages 作为 tool-result 或 user message
    # 3. 调 chat model with tool_choice="auto" + tools 列表
    # 4. 循环执行 tool_calls 直到无更多工具调用
    # 5. 每次工具调用前后保存 AgentOperationLog（before/after diff）
    # 6. 返回最终 assistant 文本 + tool_call_trace
```

**Vision/OCR 流水线** (调 vision model)：

```python
class ExtractedDocumentData(BaseModel):
    institution: str | None
    account: str | None
    items: list[ExtractedLineItem]  # 每行：instrument, quantity, price, amount, currency, date, type, fee

async def extract_from_image(image_bytes: bytes, vision_client: LLMClient) -> ExtractedDocumentData
```

支持三种场景：
1. **持仓截图**：提取当前持仓 → `set_holding_snapshot` 逐行调用
2. **交易截图/银行流水**：提取交易细节 → 相应 `create_*_transaction` 调用
3. **全量覆盖模式**（用户明确说"用图片数据覆盖"）：先 diff 再批量 upsert

---

### 4.4 AgentOperationLog 模型（Alembic migration `0006`）

```sql
agent_operation_logs (
  id UUID PK,
  created_at TIMESTAMPTZ,
  session_id UUID,              -- 一次对话 = 一个 session_id
  turn_index INT,
  user_message TEXT,
  tool_calls_json JSONB,        -- [{tool, args, result}]
  before_state_json JSONB,      -- 相关 Holding/Transaction 快照（调用前）
  after_state_json JSONB,       -- （调用后）
  is_undone BOOLEAN DEFAULT false,
  undone_at TIMESTAMPTZ NULLABLE
)
```

---

### 4.5 新增 API 端点

```
POST  /api/agent/chat              → { messages, session_id }
POST  /api/agent/chat-with-files   → multipart: messages + files
GET   /api/agent/sessions          → 历史对话列表
GET   /api/agent/sessions/{id}     → 对话详情（含 tool trace）

GET   /api/settings/llm-providers  → 已配置的 LLM 供应商列表
POST  /api/settings/llm-providers  → 新增供应商配置
PATCH /api/settings/llm-providers/{id}
DELETE /api/settings/llm-providers/{id}
```

---

### 4.6 前端：AI Agent 页

路由：`/agent`

布局：
```
┌─────────────────────────────────────────────────────┐
│  AI Agent                          [设置 LLM 供应商] │
├─────────────────────────────────────────────────────┤
│                                                     │
│  [对话消息区]                                        │
│  User: 昨天在 Morgan Stanley 用 20 万买了 800 股 SPY │
│  Assistant: 已完成...                                │
│    ▼ 工具调用详情                                    │
│       search_account("Morgan Stanley") → {...}      │
│       create_buy_transaction({...}) → {...}          │
│                                                     │
├─────────────────────────────────────────────────────┤
│  [图片上传区]  [文件上传]  [输入框]  [发送]           │
└─────────────────────────────────────────────────────┘
```

**Settings → LLM 供应商配置**：
- 每个供应商：name / provider / base_url / model / role（chat/vision）/ 是否激活
- API Key 输入（不回显；保存后后端加密存储）
- 激活当前 chat 供应商 / vision 供应商各一个

---

### Phase 4 交付物

> 用户可以：说一句中文 → Agent 自动建交易更新数据库；上传券商截图 → Agent OCR 解析后批量更新持仓；上传银行流水照片 → Agent 识别后创建转账记录。

---

---

## Phase 5 — 数据安全与恢复 (Data Safety & Recovery)

**前置条件**：Phase 4 `AgentOperationLog` 已记录所有 Agent 操作的前后状态差异。

### 目标
任何 Agent 操作可以一键撤销；数据库定期自动备份；用户可随时导出和恢复数据。

---

### 5.1 一键撤销 (Undo)

`backend/app/services/undo_service.py`：

```python
async def undo_agent_operation(db: AsyncSession, log_id: UUID) -> None:
    log = await db.get(AgentOperationLog, log_id)
    # 读取 before_state_json
    # 在单个 DB 事务中：
    #   - 对每个被修改的 Holding → 恢复到 before_state quantity
    #   - 对每个被创建的 Transaction → delete
    #   - 对每个被删除的 Transaction → recreate
    #   - 对每个被修改的 PriceSnapshot → 恢复 manual valuation
    log.is_undone = True
    log.undone_at = datetime.now(UTC)
```

**约束**：
- 只有 Agent 操作（来源 = agent/screenshot）可以撤销，手动 CRUD 不在此流程
- 撤销操作本身也写入一条 `AgentOperationLog`（type=undo，linked_to=原 log_id）
- 不支持"撤销的撤销"（防止状态混乱）

---

### 5.2 定时备份

**容器内 cron（pg_dump）**：

`docker-compose.yml` 增加 `backup` service：

```yaml
backup:
  image: postgres:16-alpine
  environment:
    PGPASSWORD: ${POSTGRES_PASSWORD}
  volumes:
    - ./backups:/backups
  entrypoint: >
    sh -c "while true; do
      pg_dump -h postgres -U wealthportfolio wealthportfolio
        > /backups/backup_$$(date +%Y%m%d_%H%M%S).sql;
      find /backups -name '*.sql' -mtime +30 -delete;
      sleep 86400;
    done"
  depends_on:
    - postgres
```

备份文件保留 30 天，按日生成，文件名含时间戳。

---

### 5.3 手动导出/恢复

**导出**（`backend/app/api/routes/data_management.py` 扩展）：

```
GET /api/data/export/csv       → 导出所有 Holdings + Instruments + Accounts（CSV ZIP）
GET /api/data/export/json      → 导出完整数据库状态（JSON，可用于恢复）
GET /api/data/backup/download  → 触发 pg_dump 并提供下载（流式）
POST /api/data/backup/restore  → 上传 SQL 文件 → psql 恢复（需要管理员确认）
```

---

### 5.4 操作历史界面

**Data Management 页扩展**：

新增 tab：`操作历史 / Operation History`

```
┌─────────────────────────────────────────────────────┐
│  操作历史                                            │
├──────────┬──────────────────────────────┬───────────┤
│ 时间      │ 操作描述                      │ 操作       │
├──────────┼──────────────────────────────┼───────────┤
│ 15:42:08 │ Agent: 买入 800 SPY @ $250   │ [撤销]     │
│ 15:40:01 │ Agent: 上传持仓截图，更新 5 项│ [撤销]     │
│ 15:35:22 │ Import: CSV 导入 23 行        │ -          │
├──────────┴──────────────────────────────┴───────────┤
│  [导出 CSV]  [导出 JSON]  [下载数据库备份]  [恢复备份]│
└─────────────────────────────────────────────────────┘
```

点击"撤销"→ 弹出确认 Dialog（显示将要回滚的变更摘要）→ 确认 → 调 `/api/agent/logs/{id}/undo` → toast 成功 / 失败。

---

### 5.5 新增 API 端点

```
GET   /api/agent/logs              → Agent 操作日志列表（分页）
POST  /api/agent/logs/{id}/undo    → 撤销指定操作
GET   /api/data/export/csv
GET   /api/data/export/json
GET   /api/data/backup/download
POST  /api/data/backup/restore
```

---

### Phase 5 交付物

> Agent 任何操作可在操作历史界面一键撤销；数据库每天自动备份，保留 30 天；用户可随时下载完整数据快照，并可上传恢复。

---

---

## 技术债与注意事项

### 跨 Phase 通用规则
- **所有 Agent 工具不生成裸 SQL**：只调用 `services/` 层，降低 prompt injection 影响范围
- **文件上传安全**：MIME 白名单（`image/jpeg`, `image/png`, `image/webp`, `application/pdf`），大小上限 20MB，存储路径用 UUID（非原始文件名），仅通过鉴权端点提供下载
- **API Key 加密**：LLM provider API keys 用 Fernet 加密存储，server-side master key 通过环境变量 `LLM_ENCRYPTION_KEY` 注入，不出现在 DB 明文中
- **每个 Phase 完成后立即跑 `tsc --noEmit` + `npm run lint` + `npm run build`**

### 已知边界条件
- **单只债券**：免费实时报价源缺乏，默认归入 `price_source_type=MANUAL`（同房产/私募），除非持有的是可公开交易的债券 ETF
- **DeepSeek vision**：截至 2026-07-21，DeepSeek 官方 API 主力对话模型不支持视觉，vision 角色应单独配置为 GPT-4o 或 Seed（Doubao pro 系列支持）
- **akshare 接口稳定性**：akshare 封装第三方行情，接口偶有变化，建议在适配器层包一层 try/except 并回退到 `quote_status=manual`
- **Frankfurter.app 汇率**：ECB 欧洲央行汇率，以 EUR 为基准计算，每个工作日更新一次；HKD/CNY 跨合约计算通过 EUR 桥接。若需 USD 计 CNY 直接汇率，建议增加补充源（人民银行官方 API 或 Yahoo FX）

### 生产部署检查单
- [ ] 替换 `.env.example` 中所有 `change-me` 值
- [ ] 配置 Caddy（或 Nginx + certbot）域名 + HTTPS
- [ ] 设置 `ENVIRONMENT=production` → 触发 secure cookie flag
- [ ] 确认 `CORS_ORIGINS` 只包含实际生产域名
- [ ] 设置 `LLM_ENCRYPTION_KEY`（32 字节随机 base64）
- [ ] 验证 Docker volume 挂载路径的磁盘空间
- [ ] 验证 backup service 生成的 SQL 文件可以正常恢复

---

*最后更新：2026-07-21*
