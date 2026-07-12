# Story Agent 开发交接

更新时间：2026-07-12
当前阶段：第三阶段——真实模型完整闭环
执行方式：另一台电脑连续完成全部工作包，完成后统一审计
工作分支：`agent/model-provider-foundation`
审计基线：`5fd8015`
完整计划：`docs/plans/PHASE-3-MODEL-PROVIDER.md`

## 当前任务

完整实施第三阶段全部四个工作包，不在工作包之间等待 GPT-5.6：

1. 模型配置、Credential Manager 密钥安全、角色绑定和高保真设置 UI；
2. OpenAI 兼容 Provider、SSE 流式规划 Agent、调用审计和停止/重试 UI；
3. JSON 结构化规划提案、白名单校验及现有接受/拒绝/撤销闭环；
4. 备份恢复、审计时间线、模型调用记录和错误诊断 UI。

每个工作包完成后先运行相关测试并独立提交，然后继续下一包。全部完成后运行全量测试、更新本文件、推送并停止，等待 GPT-5.6 统一审计。

## 不得扩大范围

- 不实施 Canon、全文/向量检索、章节正文自动写作或短剧功能。
- 不重构与第三阶段无关的第一、二阶段代码。
- 不更换 React/FastAPI/SQLite 技术栈。
- 不把特定厂商写死在业务层。

## 当前架构基线

```text
React UI
├── React Query：业务服务端状态
└── Zustand：选区、Agent 折叠和宽度等 UI 状态
        │
        ▼
FastAPI /api/v1
        │
        ├── .data/catalog.db
        └── .data/projects/{project-id}-{slug}/story.db
```

现有能力包括作品隔离、规划 revision、模拟 Agent、提案接受/拒绝、审计、撤销和带 SHA-256 的备份恢复。第三阶段必须在此基础上增量实现，不得破坏这些闭环。

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

## 全阶段安全规则

- API Key 只能进入 Windows Credential Manager；自动化测试使用内存 SecretStore。
- SQLite、日志、HTTP 响应、错误详情、备份 ZIP、截图和 Git 中不得出现完整密钥。
- 自动化测试使用本地假 OpenAI 服务，不得调用真实付费模型。
- 模型失败必须明确失败，不允许回退模拟内容冒充成功。
- 模型生成的规划修改必须先成为待确认提案。
- 正式状态改变必须遵守 revision、事务和审计规则。

## 完成前验证

必须运行并记录真实结果：

```powershell
npm run build
npm run test
npm run test:e2e
```

必须验证 1440×1024 和 1280×800，且右侧 Agent 不遮挡设置、审计和恢复界面。

## 完成后的交接要求

完成后把本文件更新为：

- 四个工作包的实际完成内容；
- 未完成内容和已知问题；
- 数据库迁移、表和 API 清单；
- 密钥安全实现及验证结果；
- 构建、API、Web、Playwright 的真实测试结果；
- 每个工作包的提交号；
- 审计起点 `5fd8015` 和最终审计终点；
- 明确状态“第三阶段已完成，停止开发，等待 GPT-5.6 审计”。

推送 `agent/model-provider-foundation` 后立即停止，不合并 `main`。

## 禁止事项

- 不修改或提交 `Story agent/` 和 `openclaw skill/`。
- 不提交 API Key、`.data/`、`apps/web/.e2e-data/`、日志、备份 ZIP 或临时文件。
- 不绕过 revision、事务和提案确认机制。
- 不合并 `main`，不提前进入第四阶段。
- 如果交接文件与实际代码冲突，以代码为准，记录差异后选择最保守兼容实现。

## 返回 GPT-5.6 的口令

```text
另一台电脑已经完成第三阶段并推送，请读取 HANDOFF.md，以 5fd8015 为基线审计全部提交，修复问题并运行全量测试。
```
