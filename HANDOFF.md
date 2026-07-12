# Story Agent 开发交接

更新时间：2026-07-12
当前阶段：第三阶段——真实模型基础
当前关卡：关卡一——模型配置基础
工作分支：`agent/model-provider-foundation`
基线：当前 PR #1 合并后的 `main`
完整计划：`docs/plans/PHASE-3-MODEL-PROVIDER.md`

## 当前任务

只实施关卡一，不得提前修改 Agent 消息接口、接入流式输出、生成真实模型回复或结构化提案。

本关交付：

- Provider、模型配置和角色绑定表及 catalog Alembic 迁移；
- OpenAI 兼容 Provider 配置、编辑、删除和连接测试 API；
- DeepSeek 官方预设与自定义中转地址；
- Windows Credential Manager SecretStore 和测试用内存 SecretStore；
- 高保真“模型与费用设置”页面；
- Provider、密钥安全、角色绑定和两档桌面布局测试。

详细字段、接口、验收和错误规则必须按完整计划执行。

## 当前架构基线

```text
React UI
├── React Query：作品、规划、会话、提案、审计
└── Zustand：选区、Agent 折叠和宽度等 UI 状态
        │
        ▼
FastAPI /api/v1
        │
        ├── .data/catalog.db
        └── .data/projects/{project-id}-{slug}/story.db
```

现有正式能力包括作品隔离、规划 revision、模拟 Agent、提案接受/拒绝、审计、撤销和带 SHA-256 的备份恢复。关卡一只能在此基础上增加模型配置，不得破坏这些闭环。

## 开始前必须阅读

1. `HANDOFF.md`
2. `docs/plans/PHASE-3-MODEL-PROVIDER.md`
3. `docs/prd/PRD-001.md`
4. `docs/ui/UI-DESIGN-BASELINE.md`
5. `design-qa.md`

## 环境与启动

目标运行时为 Node.js 24 LTS、Python 3.13 和 `uv`。API 使用 `127.0.0.1:8765`。

```powershell
npm install
npm --prefix apps/web install
uv sync --project apps/api --dev
npm run dev
```

## 完成前验证

必须运行：

```powershell
npm run build
npm run test
npm run test:e2e
```

测试不得调用真实付费模型，必须使用内存 SecretStore 和本地假 OpenAI 服务。

## 完成后的交接要求

另一台 Agent 完成关卡一后必须把本文件更新为：

- 实际完成内容；
- 未完成内容和已知问题；
- 数据库迁移与新增 API；
- 测试命令及真实结果；
- 最新提交号；
- 审计起点和审计终点；
- 明确状态“停止开发，等待 GPT-5.6 审计”。

提交并推送 `agent/model-provider-foundation` 后立即停止，不合并 `main`，不开放关卡二。

## 禁止事项

- 不修改或提交 `Story agent/` 和 `openclaw skill/`。
- 不提交 API Key、`.data/`、`apps/web/.e2e-data/`、日志、备份 ZIP 或临时文件。
- 不在 SQLite、日志、API 响应和备份中保存完整密钥。
- 不绕过 revision、事务和提案确认机制。
- 不提前实施关卡二、三、四。
- 如果交接文件与实际代码冲突，以代码为准，记录差异并停止扩大范围。

## 返回 GPT-5.6 的口令

```text
另一台电脑已经完成关卡一并推送，请读取 HANDOFF.md 和最新提交，进行完整代码审计和修复。
```
