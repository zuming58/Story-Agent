# Story Agent 开发交接

更新时间：2026-07-12  
当前阶段：第二阶段——本地数据基础  
当前分支：`agent/local-data-foundation`  
最新代码提交：`751eee0`（并发迁移锁、端到端测试与布局加固）
草稿 PR：`https://github.com/zuming58/Story-Agent/pull/1`

## 阶段目标与完成状态

本阶段目标是把第一阶段的高保真模拟原型升级为可重启、可审计、可备份的本地数据闭环。核心实现已经完成：

- FastAPI、SQLAlchemy、Alembic 与 SQLite；
- `catalog.db` 作品目录库及每部作品独立 `story.db`；
- 作品创建、列表、打开和规划保存；
- 后端模拟 Agent、会话、消息、字段级提案、接受和拒绝；
- revision 乐观并发控制与 HTTP 409；
- 规划更新、提案状态和审计事件同事务提交；
- 基于审计事件的撤销；
- 带 SHA-256 清单的 ZIP 备份、损坏拒绝和恢复为新项目；
- React Query 接管业务数据，Zustand 只保存 UI 状态；
- 1440×1024 与 1280×800 端到端验证。

## 架构与数据权威关系

```text
React UI
├── React Query：作品、规划、会话、提案、审计的服务端缓存
└── Zustand：当前选区、Agent 折叠和宽度等非业务状态
        │
        ▼
FastAPI /api/v1
        │
        ├── .data/catalog.db
        │   └── 作品目录、路径、最近打开状态
        └── .data/projects/{project-id}-{slug}/
            ├── project.json
            ├── story.db
            ├── canon/story-core.md
            ├── backups/
            └── exports/
```

SQLite 是正式业务数据权威；浏览器 localStorage 不保存作品、规划、消息或提案。`project.json` 是项目可读元数据，Canon Markdown 为后续故事内核和 RAG 预留。

## 数据库表

目录库：

- `projects`
- `app_settings`

作品库：

- `project_meta`
- `plans`
- `plan_nodes`
- `story_markers`
- `agent_sessions`
- `agent_messages`
- `change_proposals`
- `change_operations`
- `proposal_impacts`
- `audit_events`

## API 清单

- `GET /api/v1/health`
- `GET|POST /api/v1/projects`
- `GET|PATCH /api/v1/projects/{projectId}`
- `GET /api/v1/projects/{projectId}/plan`
- `PATCH /api/v1/projects/{projectId}/plan/nodes/{nodeId}`
- `GET|POST /api/v1/projects/{projectId}/agent/sessions`
- `POST /api/v1/agent/sessions/{sessionId}/messages`
- `GET /api/v1/projects/{projectId}/change-proposals`
- `POST /api/v1/change-proposals/{proposalId}/apply`
- `POST /api/v1/change-proposals/{proposalId}/reject`
- `GET /api/v1/projects/{projectId}/audit-events`
- `POST /api/v1/projects/{projectId}/audit-events/{eventId}/undo`
- `POST /api/v1/projects/{projectId}/backups`
- `POST /api/v1/projects/restore`

## 启动、构建和测试

要求 Node.js 24、Python 3.13 与 `uv`。API 使用 `127.0.0.1:8765`，因为当前电脑的 `8000` 被 Incredibuild 占用。

```powershell
npm install
npm --prefix apps/web install
uv sync --project apps/api --dev
npm run dev
```

```powershell
npm run build
npm run test
npm run test:e2e
```

## 测试结果

- API：7 passed；另有 1 条 Starlette TestClient/httpx 弃用警告。
- Web 单元测试：3 files、5 tests passed。
- Playwright：4 passed，覆盖 1440×1024 与 1280×800。
- Web 生产构建：通过。

## 未完成与已知问题

- 尚未接入 DeepSeek 或其他 OpenAI 兼容模型，目前为确定性后端模拟 Agent。
- Canon、全文检索、向量索引、章节契约自动写作和双层质量复核尚未实现。
- 备份与恢复已有 API，但尚未完成独立的前端管理页面。
- Node.js 运行时目标是 24 LTS；当前电脑已有 Node 25，Node 24 MSI 安装返回 1603，因此接力机器应直接使用 Node 24。
- Starlette TestClient 产生上游弃用警告，不影响当前测试结果。

## 下一位 Agent 的任务

1. 首先复核运行本文件中的三条验证命令，不要直接开始大改。
2. 完成备份列表、恢复上传和审计时间线 UI，使已有 API 可在界面中操作。
3. 增加并发读取回归测试，确保 Alembic 迁移锁和“每项目仅首次迁移”机制不退化。
4. 设计 OpenAI 兼容模型配置层，但不要把密钥写入仓库或数据库备份。
5. 每次结束前更新本文件并推送同一功能分支。

## 禁止事项与恢复点

- 不修改或提交 `Story agent/` 和 `openclaw skill/` 两个本地参考目录。
- 不提交 `.data/`、`apps/web/.e2e-data/`、密钥、日志、ZIP 备份和临时文件。
- 不绕过 revision 检查，不把提案未经确认直接写入正式规划。
- 不拆开“规划更新 + 提案状态 + 审计事件”的事务边界。
- 当前可恢复点为本分支最终发布提交及对应草稿 PR。
