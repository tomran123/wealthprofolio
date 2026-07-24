# WealthPortfolio

家庭全球资产管理系统。Phase 1–5 已实现：跨账户聚合、市场价格与汇率刷新、交易账本、可审计 AI Agent，以及备份/恢复。

## 启动

```bash
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# 将输出写入 .env 的 LLM_ENCRYPTION_KEY，并替换所有 change-me 值
docker compose up --build
```

- 前端：http://localhost:3000
- API：http://localhost:8000/api/health
- 首次启动会自动执行 Alembic `0001`–`0006` 并创建管理员账户。

## Phase 2–5 功能

- Yahoo Finance、AKShare、CoinGecko 与 Frankfurter 行情/汇率适配器，单项失败自动保留旧价。
- 全组合估值快照、净资产历史曲线、报价来源与 24 小时过期提示。
- 买入、卖出、存取、内部转账、换汇、分红、利息、手续费与人工调整账本。
- 删除交易自动回滚持仓；冲销保留原始记录；可从账本重建当前持仓。
- OpenAI、MiniMax、DeepSeek、Seed/Doubao 或自定义 OpenAI-compatible LLM；Chat/Vision 独立激活。
- 中文自然语言工具调用、图片/PDF 识别、会话历史、逐工具 before/after 审计。
- 60+ 个类型化投资组合工具覆盖核心 CRUD；查询立即执行，所有业务写入先生成一次性确认清单，点击确认后原子提交。
- Agent 可自动补建明确缺失的 owner、机构和账户，并保留交易日期与具体成交时间；支持分钟级历史行情参考查询。
- Agent 操作一键撤销；CSV ZIP、完整 JSON、PostgreSQL SQL 备份与恢复。
- `backup` 容器每日生成 SQL，30 天后清理旧文件。

## 验证

```bash
cd frontend
npx tsc --noEmit
npm run lint
npm run build

cd ../backend
python -m compileall -q app alembic
alembic history
```

PostgreSQL 端到端 smoke test 需要一个空的、已迁移测试数据库：

```bash
cd backend
PYTHONPATH=. python tests/integration_smoke.py
PYTHONPATH=. python tests/api_smoke.py
```

## 重要安全设置

- 生产环境必须替换 `POSTGRES_PASSWORD`、`JWT_SECRET`、管理员密码和 `LLM_ENCRYPTION_KEY`。
- LLM API Key 使用 Fernet 加密，API 与前端只返回 `has_api_key`，永不回显密钥。
- 数据恢复必须上传 `.json`/`.sql` 并显式输入 `RESTORE`；恢复会替换现有数据库。
- 上传仅接受 JPEG、PNG、WebP、PDF，总大小上限 20 MB；文档内容始终作为不可信数据处理。
